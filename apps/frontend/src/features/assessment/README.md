# Shared comparison

`useComparison` reads the current owner-scoped Assessment and its admissible source
context. Reads never start a comparison. Home, Career Goal and Skills Profile reuse
this result.

`EvaluateBanner` sits on Career Goal and Skills Profile until a current evaluation
exists. It shows exactly one of: the setup step still open (set a goal, add skills, or
finish the CV review, linking to the other page when the step lives there), a wait
for goal research, progress, or the **Evaluate skills** button that submits the
versioned command. A stale result brings it back as “Your goal or skills changed”.
`ComparisonPanel` remains Home's entry point.

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
