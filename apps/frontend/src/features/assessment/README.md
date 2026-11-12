# Shared comparison

`useComparison` reads the current owner-scoped Assessment and its admissible source
context. Reads never start a comparison. Home, Career Goal and Skills Profile reuse
this result.

`EvaluateBanner` sits on Career Goal and Skills Profile until a current evaluation
exists. It shows exactly one of: the setup step still open (set a goal, add skills, or
finish the CV review, linking to the other page when the step lives there), a wait
for goal research, progress, or the **Evaluate skills** button that submits the
versioned command. It steps aside while an earlier result is out of date.
`ComparisonPanel` remains Home's entry point.

`ChangeBanner` (workspace layout) keeps the evaluation in step with the active CV and career goal.
On Career Goal and Skills Profile, once an evaluation exists and its inputs changed, it submits
the evaluation command on its own after the new skills are rated (the CV review is finished)
and goal research is done; each input hash is attempted once per page load, so a failure shows
**Try again** instead of looping. While an evaluation runs, those two pages show “Evaluating the
skill gap between you and your career goal…” at the top; otherwise nothing. Home shows “Your
roadmap is out of date” (with **Update roadmap**) until the active plan's `assessment_hash`
matches; “Not now” hides it for that change in this browser session. Roadmap shows its own
outdated-plan banner with a direct regeneration action. Other pages show nothing. Selecting a
CV, a new goal revision, finishing a CV review, starting an evaluation and route changes fire
`elo:comparison-refresh`, so every comparison re-reads.

Reads restore pending work without submitting a new comparison. Polling resumes
running operations; failed retries restore their command/checkpoint. Ambiguous
transport retries keep the mutation UUID. Source conflicts refresh versions;
changed-input failures start a fresh operation. Account changes abort old reads
and hide their results. Current/source hashes and page goal revisions guard stale
markings. Partial research is labelled before submission and in the saved result.

Outcome labels describe evidence, not tested mastery. Supported OR alternatives
remain distinct from personal support. Home's top gaps use confirmed-shortfall
components and Assessment priority order, excluding satisfied alternatives.

See the [Assessment specification](../../../../../services/assessment-service/SPEC.md)
and [published contract](../../../../../contracts/api/assessment.yaml).

`EvaluationStatusPanel` shows server-derived freshness, processing, completeness, evaluation date and change reasons on Roadmap. Roadmap offers explicit evaluation commands; reads only restore already-pending work. A source-check failure hides current skill markings and displays Unable to verify.
