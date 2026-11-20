"""Ruff plus elo quick-fix rules, compared against a per-service baseline that may only shrink."""
import argparse
import ast
import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

BASELINES = Path(__file__).resolve().parent / 'baselines'
MONGO_METHODS = frozenset({
    'aggregate', 'bulk_write', 'count_documents', 'delete_many', 'delete_one', 'distinct', 'find',
    'find_one', 'find_one_and_delete', 'find_one_and_replace', 'find_one_and_update', 'insert_many',
    'insert_one', 'replace_one', 'update_many', 'update_one',
})
DATABASE_NAMES = frozenset({'db', 'database'})
LOWER_LAYERS = ('ai', 'clients', 'confirmation', 'domain', 'repositories', 'schemas', 'workers', 'workflows')
HEURISTIC_LAYERS = ('confirmation', 'domain', 'workflows')
OWNERS_OF_PROVIDER_LIMITS = ('ai', 'clients')
WORD_LIST_SIZE = 10
LARGE_LENGTH = 1000
MAPPING_VERSION = re.compile(r'skills-v\d+')
PROVIDER_KEYS = frozenset({'backend', 'provider'})
RULE_CODE = re.compile(r'[A-Z]+[0-9]+')
RETIRED_WORDS = frozenset({'legacy', 'compat', 'compatibility', 'backcompat', 'preupgrade'})
MESSAGES = {
    'QF001': 'Duplicate-key errors must be handled, not silently ignored.',
    'QF002': 'Lower layers must not import from app.api.',
    'QF003': 'API routes must use repository methods instead of collection calls.',
    'QF004': 'Behaviour must not depend on error or user-facing message text.',
    'QF005': 'Only provider adapters and clients may raise rate_limited.',
    'QF006': 'Workflows must not suspend the request deadline.',
    'QF007': 'Hardcoded word lists and long regex alternations must not drive domain decisions.',
    'QF008': 'Legacy and compatibility code paths must be migrated, not kept.',
    'QF009': 'Size limits must use named constants or token budgets, not literal lengths.',
    'QF010': 'Mapping versions and providers must come from configuration, not literals.',
    'QF011': 'API routes must not keep process-local state on app.state.',
}


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    code: str
    message: str
    text: str
    scope: str = ''

    def key(self):
        return self.path, self.code, self.scope, self.text


def name_of(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def string(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def prose(node):
    value = string(node)
    return value is not None and value.count(' ') >= 2


def alternations(value):
    """True for regex-style alternations such as `a|b|c`, not for prose or table text containing pipes."""
    parts = value.split('|')
    return len(parts) >= WORD_LIST_SIZE and all(p.strip() for p in parts) and not re.search(r'\s\|\s', value)


def retired(name):
    words = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', '_', name).lower().split('_')
    joined = [a + b for a, b in zip(words, words[1:])]
    return any(word in RETIRED_WORDS for word in words + joined)


def target_names(target):
    if isinstance(target, (ast.Tuple, ast.List)):
        for item in target.elts:
            yield from target_names(item)
    elif isinstance(target, ast.Starred):
        yield from target_names(target.value)
    elif isinstance(target, ast.Name):
        yield target


def mentions_message_text(node):
    while isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        node = node.func.value
    return (isinstance(node, ast.Call) and name_of(node.func) == 'str' and bool(node.args)
            or isinstance(node, ast.Attribute) and node.attr == 'message')


def is_app_state(node):
    return isinstance(node, ast.Attribute) and node.attr == 'state' and name_of(node.value) == 'app'


def database(node):
    if isinstance(node, ast.Subscript):
        return name_of(node.value) in DATABASE_NAMES
    return isinstance(node, ast.Attribute) and name_of(node.value) in DATABASE_NAMES


def collection_attributes(tree):
    """Attribute names bound to MongoDB collections, e.g. `rows` in `self.rows = db.career_goals`."""
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            pairs = (zip(target.elts, node.value.elts) if isinstance(target, ast.Tuple) and isinstance(node.value, ast.Tuple)
                     and len(target.elts) == len(node.value.elts) else [(target, node.value)])
            for left, right in pairs:
                if isinstance(left, ast.Attribute) and (database(right) or isinstance(right, ast.Call)
                                                        and name_of(right.func) == 'get_collection'):
                    found.add(left.attr)
    return found


def word_list(node):
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)) and len(node.elts) >= WORD_LIST_SIZE:
        values = [string(item) for item in node.elts]
        return all(v is not None for v in values) and any(re.search(r'[^a-z0-9_]', v) for v in values)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'split' and not node.args:
        value = string(node.func.value)
        return value is not None and len(value.split()) >= WORD_LIST_SIZE
    value = string(node)
    return value is not None and alternations(value)


def large_constant(node):
    return isinstance(node, ast.Constant) and type(node.value) is int and node.value >= LARGE_LENGTH


def provider_default(node):
    if isinstance(node, ast.Call) and name_of(node.func) in ('get', 'getattr'):
        args = node.args[1:] if name_of(node.func) == 'getattr' else node.args
        return len(args) == 2 and string(args[0]) in PROVIDER_KEYS and string(args[1]) is not None
    return False


def scopes(tree):
    """Return (first body line, last line, qualified name) for every function and class in the module."""
    found = []

    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f'{prefix}.{child.name}' if prefix else child.name
                found.append((child.body[0].lineno, child.end_lineno, name))
                walk(child, name)
            else:
                walk(child, prefix)

    walk(tree, '')
    return found


def scope_at(index, line):
    inside = [(start, name) for start, end, name in index if start <= line <= end]
    return max(inside)[1] if inside else ''


def source_text(lines, first, last):
    return ' '.join(' '.join(lines[first - 1:min(last, len(lines))]).split())


class Rules(ast.NodeVisitor):
    def __init__(self, path, lines, index, collections):
        self.path, self.lines, self.index, self.collections, self.found = path, lines, index, collections, []
        self.state_aliases, self.listed = set(), set()
        parts = PurePosixPath(path).parts
        self.layer = parts[1] if len(parts) > 2 and parts[0] == 'app' else None

    def report(self, node, code, last=None):
        end = last or getattr(node, 'end_lineno', None) or node.lineno
        text = source_text(self.lines, node.lineno, end)
        self.found.append(Violation(self.path, node.lineno, code, MESSAGES[code], text, scope_at(self.index, node.lineno)))

    def header(self, node):
        return max(node.lineno, node.body[0].lineno - 1)

    def visit_ExceptHandler(self, node):
        types = node.type.elts if isinstance(node.type, ast.Tuple) else [node.type] if node.type else []
        if any(name_of(t) == 'DuplicateKeyError' for t in types) and all(isinstance(s, ast.Pass) for s in node.body):
            self.report(node, 'QF001')
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if self.layer in LOWER_LAYERS and (node.module or '').startswith('app.api'):
            self.report(node, 'QF002')
        for alias in node.names:
            if alias.asname and retired(alias.asname):
                self.report(node, 'QF008')
        self.generic_visit(node)

    def visit_Import(self, node):
        if self.layer in LOWER_LAYERS and any(alias.name.startswith('app.api') for alias in node.names):
            self.report(node, 'QF002')
        self.generic_visit(node)

    def visit_Attribute(self, node):
        receiver = node.value
        if (self.layer == 'api' and node.attr in MONGO_METHODS and isinstance(receiver, (ast.Attribute, ast.Subscript))
                and (database(receiver) or isinstance(receiver, ast.Attribute) and receiver.attr in self.collections)):
            self.report(node, 'QF003')
        self.generic_visit(node)

    def visit_Compare(self, node):
        if any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops) and any(mentions_message_text(c) for c in node.comparators):
            self.report(node, 'QF004')
        sides = [node.left, *node.comparators]
        if any(isinstance(side, ast.Call) and name_of(side.func) == 'len' for side in sides) and any(large_constant(side) for side in sides):
            self.report(node, 'QF009')
        self.generic_visit(node)

    def state(self, node):
        return is_app_state(node) or isinstance(node, ast.Name) and node.id in self.state_aliases

    def visit_Call(self, node):
        method = node.func.attr if isinstance(node.func, ast.Attribute) else None
        if method in ('startswith', 'endswith', 'replace') and node.args and prose(node.args[0]):
            self.report(node, 'QF004')
        if method == 'reschedule' and self.layer != 'ai' and len(node.args) == 1 and isinstance(node.args[0], ast.Constant) and node.args[0].value is None:
            self.report(node, 'QF006')
        if method == 'split' and self.layer in HEURISTIC_LAYERS and word_list(node):
            self.report(node, 'QF007')
        if provider_default(node):
            self.report(node, 'QF010')
        if self.layer == 'api' and name_of(node.func) in ('hasattr', 'setattr') and node.args and self.state(node.args[0]):
            self.report(node, 'QF011')
        self.generic_visit(node)

    def visit_Raise(self, node):
        exc = node.exc
        if (self.layer not in OWNERS_OF_PROVIDER_LIMITS and isinstance(exc, ast.Call) and name_of(exc.func) == 'AIError'
                and exc.args and string(exc.args[0]) == 'rate_limited'):
            self.report(node, 'QF005')
        self.generic_visit(node)

    def visit_Expr(self, node):
        if string(node.value) is None:
            self.generic_visit(node)

    def visit_Constant(self, node):
        value = string(node)
        if value is not None and MAPPING_VERSION.fullmatch(value):
            self.report(node, 'QF010')
        if value is not None and self.layer in HEURISTIC_LAYERS and id(node) not in self.listed and alternations(value):
            self.report(node, 'QF007')

    def visit_List(self, node):
        if self.layer in HEURISTIC_LAYERS and word_list(node):
            self.report(node, 'QF007')
            self.listed.update(id(item) for item in node.elts)
        self.generic_visit(node)

    visit_Tuple = visit_Set = visit_List

    def assigned(self, node, targets):
        for target in targets:
            if any(retired(name.id) for name in target_names(target)):
                self.report(node, 'QF008')
            if self.layer == 'api' and isinstance(target, ast.Attribute) and self.state(target.value):
                self.report(node, 'QF011')

    def visit_Assign(self, node):
        self.assigned(node, node.targets)
        if self.layer == 'api' and is_app_state(node.value):
            self.state_aliases.update(name.id for target in node.targets for name in target_names(target))
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        self.assigned(node, [node.target])
        self.generic_visit(node)

    def visit_AugAssign(self, node):
        self.assigned(node, [node.target])
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        if retired(node.name):
            self.report(node, 'QF008', self.header(node))
        positional = [*node.args.posonlyargs, *node.args.args]
        for arg, default in zip(reversed(positional), reversed(node.args.defaults)):
            if arg.arg in PROVIDER_KEYS and string(default) is not None:
                self.report(default, 'QF010')
        for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
            if default is not None and arg.arg in PROVIDER_KEYS and string(default) is not None:
                self.report(default, 'QF010')
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        if retired(node.name):
            self.report(node, 'QF008', self.header(node))
        self.generic_visit(node)


def check_source(path, source, collections=frozenset(), tree=None):
    """Return the elo quick-fix violations in one module; `path` is relative to the service root."""
    tree = tree or ast.parse(source, filename=path)
    rules = Rules(path, source.splitlines(), scopes(tree), collections)
    rules.visit(tree)
    return sorted(rules.found, key=lambda v: (v.line, v.code))


def ruff_violations(service, modules):
    result = subprocess.run([sys.executable, '-m', 'ruff', 'check', '--no-fix', '--ignore-noqa', '--output-format', 'json', 'app'],
                            cwd=service, capture_output=True, text=True)
    if result.returncode not in (0, 1) or not result.stdout.strip():
        raise SystemExit(result.stderr or 'Ruff failed to run.')
    found, errors = [], []
    for item in json.loads(result.stdout):
        path = Path(item['filename']).resolve().relative_to(service.resolve()).as_posix()
        line = item['location']['row']
        if not RULE_CODE.fullmatch(item.get('code') or ''):
            errors.append(f"{service / path}:{line}: {item['message']}")
            continue
        lines, index = modules[path]
        text = source_text(lines, line, item.get('end_location', {}).get('row', line))
        found.append(Violation(path, line, item['code'], item['message'], text, scope_at(index, line)))
    if errors:
        raise SystemExit('\n'.join(['Ruff could not check these files:', *errors]))
    return found


def parse_modules(service):
    parsed = {}
    for file in sorted((service / 'app').rglob('*.py')):
        path = file.relative_to(service).as_posix()
        source = file.read_text(encoding='utf-8')
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError as error:
            raise SystemExit(f'{service / path}:{error.lineno}: cannot parse: {error.msg}') from error
        parsed[path] = source, tree
    return parsed


def collect(service):
    parsed = parse_modules(service)
    collections = set().union(*(collection_attributes(tree) for _, tree in parsed.values()))
    modules = {path: (source.splitlines(), scopes(tree)) for path, (source, tree) in parsed.items()}
    found = ruff_violations(service, modules)
    for path, (source, tree) in parsed.items():
        found.extend(check_source(path, source, collections, tree))
    return sorted(found, key=lambda v: (v.path, v.line, v.code))


def load_baseline(file):
    if not file.exists():
        return Counter()
    return Counter((item['path'], item['code'], item['scope'], item['text'])
                   for item in json.loads(file.read_text(encoding='utf-8')))


def write_baseline(file, keys):
    entries = [{'path': p, 'code': c, 'scope': s, 'text': t} for p, c, s, t in sorted(keys.elements())]
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def compare(found, baseline):
    """Split violations into those absent from the baseline and baseline entries no longer present."""
    current = Counter(v.key() for v in found)
    allowed = Counter(baseline)
    new = []
    for violation in found:
        if allowed[violation.key()]:
            allowed[violation.key()] -= 1
        else:
            new.append(violation)
    return new, baseline - current


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('service', type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--init', action='store_true', help='create the baseline when none exists')
    mode.add_argument('--prune', action='store_true', help='remove baseline entries that are fixed')
    args = parser.parse_args(argv)
    service = args.service
    if not (service / 'app').is_dir():
        raise SystemExit(f'{service} is not a service folder with an app/ directory.')
    file = BASELINES / (service.resolve().name + '.json')
    found = collect(service)
    if args.init:
        if file.exists():
            raise SystemExit(f'{file} already exists; use --prune after fixing violations.')
        write_baseline(file, Counter(v.key() for v in found))
        print(f'Baselined {len(found)} violations in {file}.')
        return 0
    if not file.exists():
        raise SystemExit(f'{file} does not exist; run with --init to create the first baseline.')
    baseline = load_baseline(file)
    new, fixed = compare(found, baseline)
    if args.prune and fixed:
        baseline -= fixed
        write_baseline(file, baseline)
        print(f'Removed {sum(fixed.values())} fixed entries from {file}.')
        fixed = Counter()
    for violation in new:
        print(f'{service / violation.path}:{violation.line}: {violation.code} {violation.message}')
    for path, code, scope, text in sorted(fixed.elements()):
        where = f' in {scope}' if scope else ''
        print(f'{service / path}: {code}{where} is fixed but still baselined ({text}). Run with --prune.')
    print(f'{len(new)} new, {sum(fixed.values())} stale, {sum(baseline.values())} baselined violations.')
    return 1 if new or fixed else 0


if __name__ == '__main__':
    sys.exit(main())
