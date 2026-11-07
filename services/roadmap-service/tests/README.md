# Roadmap tests

Run this service separately with its pinned dependencies and `packages/elo-shared` installed (or on `PYTHONPATH`). Tests use synthetic model/source adapters and explicit in-memory stores, covering selected-day allocation, effort conservation, prerequisites/cycles, reduced periods, reviewed activation, stale-source/proposal guards, immutable history, completion/reopening, retries, quotas and process-independent saved state.

The shared runtime also has disposable MongoDB CAS/lease/result tests. `infrastructure/testing/planner-smoke.py` exercises real cross-service HTTP and MongoDB restart persistence with synthetic sources/models. Frontend unit/browser coverage lives with the Roadmap feature. See [testing guidance](../../../docs/testing.md#assessment-and-roadmap-adviser). No tests read environment files or call a live provider.

`planner_fixtures.py` holds the synthetic timed-roadmap scenario. `test_planner_capacity.py`, `test_planner_validator.py` and `test_planner_flow.py` cover runway arithmetic, each validation rule and the Configure → Generate → Review → Revise API flow. `test_planner_model.py` sends plans through the real model client and OpenAI SDK with a mock transport. `test_planner.py` covers chat retry, quota and restart recovery, and read-only earlier plans. `test_retired_settings.py` covers the startup removal of retired settings, using a small fake collection; the smoke script repeats it on real MongoDB. `test_contract.py` keeps the published contracts equal to the running models and free of untyped roadmap objects.

`test_editable_tasks.py` covers owner-scoped mutations, retries, stale versions and requirement links, unscheduled work, readiness, history, removal and revision decisions. `test_revision_reservations.py` checks saved schedule reservations and revision preservation, including multi-segment tasks. `test_task_schedule_warnings.py` checks conflict warnings and bounded overlap processing. These tests use synthetic accounts and model responses.

`test_dashboard_source.py` verifies the passive owner-scoped projection, no pending-operation launch or read-time migration, and immutable pace-baseline identity across acceptance, task progress, revision and retry.
`test_preview_receipts.py` verifies action-bound accept/discard retries and safe rejection of ambiguous older preview receipts.
