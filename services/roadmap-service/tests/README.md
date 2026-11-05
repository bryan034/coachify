# Roadmap tests

Run this service separately with its pinned dependencies and `packages/elo-shared` installed (or on `PYTHONPATH`). Tests use synthetic model/source adapters and explicit in-memory stores, covering selected-day allocation, effort conservation, prerequisites/cycles, reduced periods, reviewed activation, stale-source/proposal guards, immutable history, completion/reopening, retries, quotas and process-independent saved state.

The shared runtime also has disposable MongoDB CAS/lease/result tests. `infrastructure/testing/planner-smoke.py` exercises real cross-service HTTP and MongoDB restart persistence with synthetic sources/models. Frontend unit/browser coverage lives with the Roadmap feature. See [testing guidance](../../../docs/testing.md#assessment-and-roadmap-adviser). No tests read environment files or call a live provider.

`planner_fixtures.py` holds the synthetic timed-roadmap scenario. `test_planner_capacity.py`, `test_planner_validator.py` and `test_planner_flow.py` cover runway arithmetic, each validation rule and the Configure → Generate → Review → Revise API flow. `test_planner_model.py` sends plans through the real model client and OpenAI SDK with a mock transport. `test_planner.py` covers chat retry, quota and restart recovery, and read-only earlier plans.

`test_planner_tasks.py` covers task actions, custom tasks, deterministic rescheduling, Undo and repeated or concurrent access. `test_planner_coach.py` covers staged generation, rolling detail, progress, pace, check-ins, pause, plan edits, archival, `roadmap-v2` reads and daylight-saving placement. `planner_fixtures.Staged` answers both generation stages from one synthetic draft.
