import json
import subprocess
from collections import Counter

import pytest

import quickfix_check
from quickfix_check import Violation, check_source, collect, compare, load_baseline, main, ruff_violations, write_baseline


def codes(path, source, collections=frozenset()):
    return [v.code for v in check_source(path, source, collections)]


@pytest.mark.parametrize('path,source,expected', [
    ('app/repositories/x.py', 'try:\n    insert()\nexcept DuplicateKeyError:\n    pass\n', ['QF001']),
    ('app/repositories/x.py', 'try:\n    insert()\nexcept DuplicateKeyError:\n    replay()\n', []),
    ('app/workflows/x.py', 'from app.api.v1.jd import validate\n', ['QF002']),
    ('app/workflows/x.py', 'def f():\n    import app.api.v1.jd\n', ['QF002']),
    ('app/api/v1/x.py', 'from app.domain.review import prepare\n', []),
    ('app/api/v1/x.py', 'thread(repo.save, {})\n', []),
    ('app/api/v1/x.py', 'thread(store.db.career_goals.find_one, {})\n', ['QF003']),
    ('app/api/v1/x.py', "rows = request.app.db['goals'].find({})\n", ['QF003']),
    ('app/api/v1/x.py', 'self.repo.find(query)\n', []),
    ('app/api/v1/x.py', 'request.app.state.search.find(query)\n', []),
    ('app/api/v1/x.py', 'deps.cache.distinct(field)\n', []),
    ('app/workflows/x.py', "retry = any(v in str(error).casefold() for v in ('timed out',))\n", ['QF004']),
    ('app/workflows/x.py', "found = word in error.message\n", ['QF004']),
    ('app/workflows/x.py', "ok = w.startswith('Overall summary unavailable;')\n", ['QF004']),
    ('app/workflows/x.py', "ok = key in linked(str(goal_id))\n", []),
    ('app/workflows/x.py', "ok = url.startswith('https://')\n", []),
    ('app/workflows/x.py', "raise AIError('rate_limited', retry_after=1)\n", ['QF005']),
    ('app/ai/adapter.py', "raise AIError('rate_limited', retry_after=1)\n", []),
    ('app/workflows/x.py', 'budget.reschedule(None)\n', ['QF006']),
    ('app/ai/adapter.py', 'budget.reschedule(None)\n', []),
    ('app/workflows/x.py', 'budget.reschedule(deadline)\n', []),
    ('app/domain/x.py', "NAMES = r'\\b(a|b|c|d|e|f|g|h|i|j)\\b'\n", ['QF007']),
    ('app/domain/x.py', "ASK = r'(?:what(?: is| are)?|a|b|c|d|e|f|g|h|i)'\n", ['QF007']),
    ('app/domain/x.py', "WORDS = frozenset('a b c d e f g h i j'.split())\n", ['QF007']),
    ('app/domain/x.py', "PLACES = ['new york', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j']\n", ['QF007']),
    ('app/domain/x.py', "PLACES = ['new|york', 'b|c|d|e|f|g|h|i|j|k', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j']\n", ['QF007']),
    ('app/domain/x.py', "FIELDS = ('a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j')\n", []),
    ('app/domain/x.py', "def f():\n    '''a|b|c|d|e|f|g|h|i|j'''\n", []),
    ('app/domain/x.py', "log.info('| a | b | c | d | e | f | g | h | i | j |')\n", []),
    ('app/schemas/x.py', "NAMES = r'\\b(a|b|c|d|e|f|g|h|i|j)\\b'\n", []),
    ('app/domain/x.py', 'LEGACY_COPY = 1\n', ['QF008']),
    ('app/domain/x.py', 'def compatibility():\n    pass\n', ['QF008']),
    ('app/domain/x.py', 'def read_legacy_context():\n    pass\n', ['QF008']),
    ('app/domain/x.py', 'class LegacyAdapter:\n    pass\n', ['QF008']),
    ('app/domain/x.py', 'pre_upgrade: bool = True\n', ['QF008']),
    ('app/domain/x.py', 'first, legacy_rows = load()\n', ['QF008']),
    ('app/domain/x.py', 'legacy_count += 1\n', ['QF008']),
    ('app/domain/x.py', 'is_compatible = incompatible = legacyish = 1\n', []),
    ('app/main.py', 'from app.api.v1.targets import router as legacy_router\n', ['QF008']),
    ('app/domain/x.py', 'if len(text) > 40000:\n    pass\n', ['QF009']),
    ('app/domain/x.py', 'if len(text) > MAX_TEXT:\n    pass\n', []),
    ('app/domain/x.py', "version = 'skills-v1'\n", ['QF010']),
    ('app/domain/x.py', "name = getattr(source, 'provider', 'brave')\n", ['QF010']),
    ('app/domain/x.py', "name = row.get('provider', 'brave')\n", ['QF010']),
    ('app/domain/x.py', "def f(retry, provider='brave'):\n    pass\n", ['QF010']),
    ('app/domain/x.py', "def f(a, b='x', /, provider='brave'):\n    pass\n", ['QF010']),
    ('app/domain/x.py', "def f(provider='brave', /, retry=1):\n    pass\n", ['QF010']),
    ('app/domain/x.py', "def f(a, backend='x', /, retry=1):\n    pass\n", ['QF010']),
    ('app/domain/x.py', "def f(provider, retry='x'):\n    pass\n", []),
    ('app/domain/x.py', "name = getattr(source, 'provider', None)\n", []),
    ('app/api/v1/x.py', 'request.app.state.tasks = {}\n', ['QF011']),
    ('app/api/v1/x.py', 'request.app.state.tasks: dict = {}\n', ['QF011']),
    ('app/api/v1/x.py', 'request.app.state.count += 1\n', ['QF011']),
    ('app/api/v1/x.py', "state = request.app.state\nif not hasattr(state, 'tasks'):\n    state.tasks = {}\n", ['QF011', 'QF011']),
    ('app/api/v1/x.py', "if not hasattr(state, 'tasks'):\n    state.tasks = {}\n", []),
    ('app/api/v1/x.py', 'request.state.user = user\n', []),
    ('app/main.py', 'app.state.tasks = {}\n', []),
])
def test_rules(path, source, expected):
    assert codes(path, source) == expected


@pytest.mark.parametrize('source,expected', [
    ('thread(repo.rows.update_one, {})\n', ['QF003']),
    ('thread(goals(request).rows.find_one, {})\n', ['QF003']),
    ('thread(repo.save, {})\n', []),
    ('thread(repo.search.find, {})\n', []),
])
def test_collection_calls_use_service_collection_attributes(source, expected):
    assert codes('app/api/v1/x.py', source, {'rows'}) == expected


def test_collection_attributes_come_from_database_bindings():
    import ast
    tree = ast.parse('class R:\n    def __init__(self, db):\n        self.rows, self.state = db.goals, db.state\n'
                     "        self.cache = db['cache']\n        self.other = db.get_collection('x')\n"
                     '        self.db = db\n        self.client = Client(db)\n')
    assert quickfix_check.collection_attributes(tree) == {'rows', 'state', 'cache', 'other'}


def test_violation_text_is_whitespace_normalised():
    [violation] = check_source('app/domain/x.py', "version   =   'skills-v1'\n")
    assert violation.text == "version = 'skills-v1'"


def test_violation_text_covers_the_whole_statement():
    [violation] = check_source('app/domain/x.py', 'LEGACY = {\n    "a": 1,\n}\n')
    assert violation.text == 'LEGACY = { "a": 1, }'


def test_definition_text_is_the_header_only():
    [violation] = check_source('app/domain/x.py', 'def legacy(\n    a,\n):\n    return a\n')
    assert violation.text == 'def legacy( a, ):'


def test_violations_record_enclosing_scope():
    source = "class A:\n    def f(self):\n        return 'skills-v1'\n\ndef g():\n    return 'skills-v1'\n\nV = 'skills-v1'\n"
    assert [v.scope for v in check_source('app/domain/x.py', source)] == ['A.f', 'g', '']


def violation(text, line=1, scope=''):
    return Violation('app/x.py', line, 'QF001', '', text, scope)


def test_compare_accepts_baselined_and_reports_new_and_fixed():
    baseline = Counter({('app/x.py', 'QF001', '', 'old'): 1, ('app/x.py', 'QF001', '', 'gone'): 1})
    new, fixed = compare([violation('old', 4), violation('fresh', 9)], baseline)
    assert [v.text for v in new] == ['fresh']
    assert fixed == Counter({('app/x.py', 'QF001', '', 'gone'): 1})


def test_compare_counts_duplicate_lines():
    baseline = Counter({('app/x.py', 'QF001', '', 'same'): 1})
    new, fixed = compare([violation('same', 1), violation('same', 2)], baseline)
    assert [v.line for v in new] == [2]
    assert not fixed


def test_compare_does_not_let_a_new_violation_replace_one_fixed_in_another_scope():
    baseline = Counter({('app/x.py', 'QF001', 'f', 'try:'): 1})
    new, fixed = compare([violation('try:', 9, 'g')], baseline)
    assert [v.scope for v in new] == ['g']
    assert fixed == baseline


def test_baseline_round_trip(tmp_path):
    file = tmp_path / 'service.json'
    keys = Counter({('app/x.py', 'QF001', 'f', 'a'): 2, ('app/y.py', 'E402', '', 'b'): 1})
    write_baseline(file, keys)
    assert load_baseline(file) == keys
    assert load_baseline(tmp_path / 'missing.json') == Counter()


RUFF_CONFIG = '[tool.ruff]\ninclude = ["app/**/*.py"]\n\n[tool.ruff.lint]\nselect = ["BLE001"]\n'
BLIND = 'def {name}():\n    try:\n        work()\n    except Exception:\n        recover()\n'


@pytest.fixture
def service(tmp_path, monkeypatch):
    root = tmp_path / 'demo-service'
    (root / 'app' / 'domain').mkdir(parents=True)
    (root / 'pyproject.toml').write_text(RUFF_CONFIG, encoding='utf-8')
    monkeypatch.setattr(quickfix_check, 'BASELINES', tmp_path / 'baselines')
    return root


def write(service, path, source):
    (service / path).write_text(source, encoding='utf-8')


def baseline_file(service):
    return quickfix_check.BASELINES / 'demo-service.json'


def test_collect_combines_ruff_and_quickfix_rules(service):
    write(service, 'app/domain/x.py', BLIND.format(name='f') + "VERSION = 'skills-v1'\n")
    found = collect(service)
    assert [(v.path, v.line, v.code, v.scope) for v in found] == [
        ('app/domain/x.py', 4, 'BLE001', 'f'), ('app/domain/x.py', 6, 'QF010', '')]


def test_ruff_ignores_inline_suppressions(service):
    write(service, 'app/domain/x.py', '# ruff: noqa\n' + BLIND.format(name='f').replace('Exception:', 'Exception:  # noqa: BLE001'))
    assert [v.code for v in collect(service)] == ['BLE001']


def test_ruff_text_covers_the_reported_range(service):
    write(service, 'app/domain/x.py', BLIND.format(name='f'))
    [violation] = ruff_violations(service, {'app/domain/x.py': (BLIND.format(name='f').splitlines(), [(2, 5, 'f')])})
    assert violation.text == 'except Exception:'


def test_ruff_diagnostics_without_a_rule_code_stop_the_check(service, monkeypatch):
    output = [{'filename': str(service / 'app/domain/x.py'), 'code': code, 'message': 'Expected an expression',
               'location': {'row': 3}, 'end_location': {'row': 3}} for code in (None, 'invalid-syntax')]
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 1, json.dumps(output), ''))
    with pytest.raises(SystemExit, match='x.py:3: Expected an expression'):
        ruff_violations(service, {'app/domain/x.py': ([], [])})


def test_syntax_errors_stop_the_check_with_a_readable_message(service):
    write(service, 'app/domain/x.py', 'def f(:\n')
    with pytest.raises(SystemExit, match=r'x\.py:1: cannot parse'):
        collect(service)


def test_main_initialises_checks_and_prunes_the_baseline(service, capsys):
    write(service, 'app/domain/x.py', BLIND.format(name='f') + BLIND.format(name='g'))
    assert main([str(service), '--init']) == 0
    assert len(json.loads(baseline_file(service).read_text(encoding='utf-8'))) == 2
    with pytest.raises(SystemExit, match='already exists'):
        main([str(service), '--init'])

    assert main([str(service)]) == 0

    write(service, 'app/domain/x.py', BLIND.format(name='g') + BLIND.format(name='h'))
    assert main([str(service)]) == 1
    output = capsys.readouterr().out
    assert 'x.py:9: BLE001' in output
    assert 'BLE001 in f is fixed but still baselined' in output

    write(service, 'app/domain/x.py', BLIND.format(name='g'))
    assert main([str(service)]) == 1
    assert main([str(service), '--prune']) == 0
    assert load_baseline(baseline_file(service)) == Counter({('app/domain/x.py', 'BLE001', 'g', 'except Exception:'): 1})
    assert main([str(service)]) == 0


def test_main_rejects_folders_without_app_code(tmp_path, monkeypatch):
    monkeypatch.setattr(quickfix_check, 'BASELINES', tmp_path / 'baselines')
    with pytest.raises(SystemExit, match='not a service folder'):
        main([str(tmp_path / 'missing-service'), '--init'])
    assert not (tmp_path / 'baselines').exists()


def test_main_requires_an_existing_baseline(service):
    write(service, 'app/domain/x.py', 'VALUE = 1\n')
    with pytest.raises(SystemExit, match='run with --init'):
        main([str(service)])
