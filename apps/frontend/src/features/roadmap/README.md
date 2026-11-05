# Roadmap

`roadmap-planner.tsx` is the shell: it loads and polls the workspace, sends messages and writes, and recovers lost responses. It shows one of two views, each with a button that opens the chat helper.

- **Configure:** `settings-panel.tsx` is the fixed planner form and the confirmed record, with `blackout-rules.tsx` for repeating blackout days and time slots. Every runway number and duration resolution comes from `POST /planner/runway`.
- **Roadmap page:** tabs for Roadmap (`roadmap-review.tsx`, `milestone-timeline.tsx`) and Starting point. `RouteMap` draws the plan as a rising route to the goal, solid up to today and dotted for what is projected; the numbered milestone list carries the same facts as text. A preview applies only when accepted, and projections stay separate from completed sessions.
- **Chat helper:** closed, the view fills the screen with two columns on wide screens: the form beside a pinned runway, and milestones and sessions beside outcomes and gaps. Open, `adviser-chat.tsx` docks beside the view, which narrows to one column, or overlays it on narrow screens. It starts on the first required detail the runway reports as missing, lists what is still needed, and fills in the form. With a plan, it requests a preview. It closes for a new preview and opens when a saved message failed, so that message can be retried.

Private drafts stay in account-keyed React state. An unsent helper message survives closing the helper. Unsaved settings are saved before a chat message or generation. Unknown outcomes retry the original mutation identity, and account changes clear private display and ignore late responses. See the [Roadmap specification](../../../../../services/roadmap-service/SPEC.md).

New preview navigation is applied with the workspace update, before the preview becomes interactive. Returning to Configure retains the preview and is not reversed by a deferred view effect.
