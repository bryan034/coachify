# Synthetic CV request-size replay

From `services/cv-service`, install the service's test dependencies and run:

```sh
python scripts/measure_request_sizes.py > /tmp/cv-request-sizes.json
python scripts/measure_request_sizes.py --baseline tests/fixtures/request-size-baseline.json
python scripts/measure_request_sizes.py --baseline tests/fixtures/request-size-before-7b33a07.json
python -m pytest tests/test_request_size_replay.py
```

The replay builds synthetic sparse, clear, long and ambiguous contexts using the
real interview projection and the real extraction, review and clarification
request builders. An in-memory HTTP transport supplies synthetic responses and
makes no provider calls. Its report contains only fixture names, operation stages,
and byte counts; it does not output the CV, answers, prompt, schema, credentials,
or provider response. The committed snapshot records the first post-change
baseline. `request-size-before-7b33a07.json` was generated using the same replay
script and synthetic inputs from an isolated archive of Git commit `7b33a07`,
including that revision's CV service and shared transport. Both use the same
synthetic provider settings and strict extraction mode. The review context is
rebuilt by each revision, so review changes include policy and projection changes;
they do not isolate prompt efficiency. Save another report from a known revision to compare later changes;
`--baseline` reports a request-byte delta for each matched fixture and stage.
Do not overwrite an earlier baseline when collecting a comparison.

`request_bytes` is the complete serialized request. `system_text_bytes` and
`user_text_bytes` are UTF-8 sizes of those message contents, while
`response_format_bytes` measures serialized decoder settings; these components
are not additive because the request also includes JSON escaping and metadata.
A prompt-embedded schema is counted within system text. These bytes are neither
token counts nor estimates of provider billing, cache hits, latency or model
quality. Fixture replies only exercise request construction and response parsing;
they do not establish end-to-end review success, attribution accuracy, a token
reduction, or the plan's 30% target. Provider-side usage and
same-tier labelled quality comparisons still require separate testing with
actual model responses.
