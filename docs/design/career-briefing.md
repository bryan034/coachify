# Saved career briefing

The saved `/career-goal` screen follows the supplied career-briefing HTML reference:
role banner, expandable learning focus, starting-point sidebar, next step and
collapsible opportunity context. It keeps the shared workspace navigation and
new-goal/refinement flows. New accounts still see the existing goal intake.

## Available now

All personalised content continues through the existing Career APIs; the browser
never accesses MongoDB directly. No database migration or new API is needed for
this layout.

| Briefing content | Existing saved source |
| --- | --- |
| Role, employer, location, employment type | `career_goals` identity fields |
| Learning-focus rows | `career_goals.skills`: name, category, priority, context, proficiency/experience expectations, evidence, origin and source URLs |
| Eligibility and commitment | `career_goals.non_skill_requirements`, including linked AND/OR alternatives |
| Responsibilities and role summary | `career_goals.responsibilities` and `summary` |
| Interviews and company research | Linked `interview_research` Opportunity Intelligence, retaining dates, uncertainty, conflicts and citations |
| Starting-point panel | Existing owner-scoped CV assessment-status API; presence of extracted skills only |

Rows retain saved order; numbers are a reading aid, not a skill-gap ranking or a
recommended sequence. Requirements are not labelled as personal deficiencies.
An extracted CV does not establish a match against individual goal requirements.
The CV link opens the saved upload/review and conversational clarification workflow.
Clarification requires explicit confirmation of the current goal and selection revision;
an automatically saved goal is not sufficient. Assessment computation remains planned.
Research progress/retry remains available, with findings inside the research
accordion. No mock DBS data or reference-draft self-check is copied into accounts.

## Changes needed for the richer reference content (proposed, not implemented)

1. **Save generated learning guidance in Career.** Add an optional versioned
   briefing to the goal aggregate, with per-skill references to stable `item_id`s:
   an action-oriented title, rationale, learning outcomes and practice idea. Store
   an explicit sequence only when generated, plus `goal_version`, generation
   timestamp, model/prompt/schema versions and supporting requirement references.
   Keep employer evidence separate from AI guidance. Backend generation must
   validate references, lengths and provenance before saving. Existing goals
   would show their requirements until guidance is generated; no invented
   backfill. A goal edit/replacement must invalidate or regenerate stale guidance.
2. **Persist self-checks in Profile.** The service boundaries assign declared
   capabilities to Profile. Extend its versioned aggregate/API with stable skill
   identity (and a reference for unmapped goal items), self-reported level,
   optional project evidence and update time. Keep “not assessed”, “new”,
   “developing” and “project experience” distinct from verified proficiency.
   Career must read these through the authenticated Profile API. Do not put
   private self-checks in shared research or browser storage. Goal-specific
   references must not carry over blindly to a replaced goal.
3. **Keep assessed gaps separate.** A CV comparison belongs to Career's planned
   `skill_gap_analyses`, pinning the CV, profile and goal versions. Do not infer
   gaps from CV absence or self-check answers. A practice recommendation can use
   an explicit self-check and sequence, but must say so. Milestones, scheduling
   and task progress remain Roadmap-owned.
4. **Update contracts together before enabling controls.** Extend backend models,
   JSON/OpenAPI contracts, frontend types and collection/embedded-object diagrams.
   Add owner/version-checked save APIs, input validation, idempotent retry and
   stale-input handling. Cover persistence/reload, account isolation, concurrent
   edits and goal replacement with synthetic data. Optional fields allow existing
   records to remain readable without a destructive migration.

These additions require backend feature work. The implemented layout does not
present a self-check form or generated outcomes as if they were already saved.
