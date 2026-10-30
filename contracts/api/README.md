# API contracts

`profile.yaml`, `cv.yaml` and `career.yaml` describe the implemented FastAPI boundaries. CV includes saved upload/review, source selection, clarification, capability input and resumable conversations. Career includes canonical goal/chat, research/discovery and explicit version-bound confirmation for CV context. `assessment.yaml` and `roadmap.yaml` describe the separate comparison and conversational planning services. Dashboard/Review endpoint contracts remain shells.

[models/](models/) contains JSON Schemas. `cv.schema.json` is the authoritative public saved-CV response. `career-cv-snapshot.schema.json` is Career's internal projection of that response and legacy CV reads; it is not a second CV store or a separate public CV API. Career goal/research/gap schemas describe their owning models without claiming that assessment computation is implemented.

Individual endpoint explanations live in service READMEs; the [API overview](../../docs/api/README.md) maps prefixes to services. Keep generated schemas aligned with implementation. Private internal routes stay behind the gateway.

`assessment.schema.json` describes the new Assessment-owned result; `roadmap.schema.json` describes a saved plan. The older `skill-gap-analysis.schema.json` remains Career analysis-v1 compatibility and is not the new service response. Producer schemas add canonical skill identities and Career source-grounded job dates without rewriting legacy references.
