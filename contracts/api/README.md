# API contracts

`profile.yaml`, `career.yaml` and `cv.yaml` describe the implemented APIs and are
generated from their FastAPI applications. Roadmap, Dashboard and Review remain
scaffolds. The target-bound CV input is a producer contract; it does not imply a
working assessment or roadmap consumer.

Individual endpoint explanations live in each service README; the
[API overview](../../docs/api/README.md) maps prefixes to services. Keep schemas
aligned with implementation. Private internal routes stay behind the gateway.
