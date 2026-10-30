# Roadmap adviser

`roadmap-planner.tsx` hosts the saved career-adviser chat with its proposed/active plan beside it. Source readiness, comparison and domain decisions come from the backend. Selected weekdays use daily workload estimates without fixed clock times. Users review activation, adjust preferences, edit/add/remove activities, and start/complete/reopen work. The starting-point tab shows captured evidence-linked comparison outcomes.

Private drafts stay in account-keyed React state. Polls do not overwrite the next message; unknown outcomes retry the original mutation identity. Account changes clear private display and late responses. Messages/plans/history persist server-side. See the [Roadmap specification](../../../../../services/roadmap-service/SPEC.md) for source versions, limits and remaining features.
