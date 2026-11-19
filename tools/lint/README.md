# Lint

`quickfix_check.py` runs Ruff and the elo quick-fix rules over a service's `app/` code and compares the result with `baselines/<service>.json`. CI fails on any violation that is not baselined, and on any baselined violation that has been fixed but not pruned, so the baseline can only shrink. Ruff runs with `--ignore-noqa`, so `# noqa` and `# ruff: noqa` comments have no effect; a violation is either fixed or baselined. Files that cannot be parsed stop the check with their location, and `--init` refuses a folder without `app/`.

Enabled for: `career-service`.

```sh
python3.12 -m pip install -r tools/lint/requirements.txt
python -m pytest tools/lint
python tools/lint/quickfix_check.py services/career-service           # check
python tools/lint/quickfix_check.py services/career-service --prune   # drop fixed entries after a fix
python tools/lint/quickfix_check.py services/<name>-service --init    # first baseline for a new service only
```

A baseline entry matches by file, rule, enclosing function or class, and the whitespace-normalised source of the reported statement (the header only, for a function or class), so editing a baselined statement requires fixing it. Identical statements in the same scope are counted, not told apart.

## Rules

Ruff rules are selected in each service's `pyproject.toml`.

| Rule | Flags |
|---|---|
| BLE001, S110, SIM105 | Broad or silently swallowed exceptions |
| E402, PLC0415 | Imports that are not at the top of the module |
| PLR2004 | Magic numbers in comparisons |
| QF001 | `except DuplicateKeyError: pass` |
| QF002 | `app.api` imported from `ai`, `clients`, `confirmation`, `domain`, `repositories`, `schemas`, `workers` or `workflows` |
| QF003 | MongoDB collection methods in `app/api` called on `db`/`database` attributes or on attributes the service binds to collections (`self.rows = db.career_goals`) |
| QF004 | Behaviour that depends on `str(error)`, `.message` or prose literals (`startswith`, `endswith`, `replace`) |
| QF005 | `AIError('rate_limited')` raised outside `app/ai` and `app/clients` |
| QF006 | `reschedule(None)` outside `app/ai` |
| QF007 | Word lists of ten or more entries and regex alternations of ten or more branches in `domain`, `workflows` and `confirmation` (docstrings excluded) |
| QF008 | Definitions, assignments or aliases whose name contains the word `legacy`, `compat`, `compatibility` or `pre_upgrade` |
| QF009 | `len(...)` compared with a literal of 1000 or more |
| QF010 | Literal `skills-vN` mapping versions and literal provider or backend defaults |
| QF011 | Process-local state set on `app.state` (or a name bound to it) from `app/api` |
