# Shared comparison

`useComparison` reads the current owner-scoped Assessment and its admissible source
context. `ComparisonPanel` starts an explicit versioned comparison, independently
of Roadmap. Home, Career Goal and Skills Profile reuse this result.

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
