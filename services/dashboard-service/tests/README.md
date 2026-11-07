# Dashboard tests

Run separately with the pinned service dependencies and `packages/elo-shared` installed, or on `PYTHONPATH`:

```sh
cd services/dashboard-service
PYTHONPATH=../../packages/elo-shared:. python -m pytest
```

Tests use synthetic authenticated source adapters and snapshots. They cover account isolation, empty and unavailable data, task and milestone counts, assessment freshness, source races, calendar boundaries, split work, completion history and pace baselines. They do not call a model provider.
