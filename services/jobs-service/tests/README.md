# Jobs tests

Tests use synthetic listings and adapters; none calls a live provider or reads environment files. Store, sync and API tests run on `mongomock`, and also on real MongoDB when `MONGODB_TEST_URI` points to a disposable server. Each run creates and drops a uniquely named database.

```sh
python -m pip install -e ../../packages/elo-shared -e '.[test]'
python -m pytest
MONGODB_TEST_URI=mongodb://localhost:27017 python -m pytest
```

| File | Covers |
|---|---|
| `test_normalise.py` | Job type and work arrangement rules, link safety, text cleaning, excerpts, search terms and dates |
| `test_live.py` | Request-time refresh, shared overlapping reads, concurrency bounds, failure recovery, filtering/paging, no catalogue writes and independent saved applications |
| `test_sync.py` | Legacy catalogue compatibility: Provider mapping, Singapore scope, closing rules, outages and backoff, leases, registry validation and removal |
| `test_api.py` | Authentication, every search filter, paging, owner isolation, version conflicts, capacity, pasted job links and external search links |
| `test_contract.py` | `contracts/api/jobs.yaml` matches the running service |
