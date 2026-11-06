# Jobs service specification

## Scope

Search fetches Singapore jobs live from the configured public Greenhouse, Lever and Ashby employer boards. A listing qualifies only when its location text or Ashby postal country names Singapore. Users apply on the employer site; Elo sends no CV/profile data and records application statuses as self-reported.

## Provider API references

The adapters follow the public [Greenhouse Job Board API](https://docs.greenhouse.io/job-board), [Lever Postings API](https://github.com/lever/postings-api) and [Ashby Public Job Posting API](https://developers.ashbyhq.com/docs/public-job-posting-api). Public access does not settle commercial reuse permissions; see Commercial terms below.

## Request-time reads

`jobs-service` calls fixed provider origins using the reviewed `app/sources.json` registry. Board names are validated. No scheduled sync worker runs and search does not read or write a listing database. All filters run against freshly normalised results in memory. Each read covers the configured registry so searches with different filters can share the same in-progress operation.

Each process runs one provider operation at a time, with up to eight concurrent board reads. Overlapping search, filter, posting and first-save requests join the active operation rather than starting duplicate reads or returning `providers_busy`. Successes and failures are delivered to all waiting callers, and the operation is then cleared so the next request fetches fresh data. Only public board data is shared; owner-specific application records remain separate. Queued board reads stop starting after 20 seconds; in-flight HTTP reads finish within their per-board budgets. The Jobs gateway timeout is 60 seconds. HTTP reads have a five-second timeout and elapsed response budget, a 48 MiB body limit, JSON validation and no redirects or environment proxy credentials. No provider credentials are required. Invalid records are skipped. `unavailable_sources` identifies failed or incomplete boards; all boards unavailable with no usable records returns 503 rather than a misleading empty result. `retrieved_at` records when the read started.

Every search, including subsequent pages, starts a fresh provider operation or joins one already in progress. Keyset cursors order by published date and stable ID. Results and totals can change between pages as providers change; the UI deduplicates appended results. There is no durable or process-local listing cache. `/filters` shares an overlapping live read with search; sequential reads can still have different counts.

## Search and untrusted content

Keyword matching requires all escaped terms, preserves C++, C# and .NET, and allows common word endings. Results sort newest first, without relevance ranking. Singapore calendar days define date ranges. Missing/implausible dates are marked `posted_at_estimated`, represented internally by the Unix epoch for stable sorting, shown as “Posting date not supplied”, and excluded from date filters. Retrieval time never establishes a publication date. `last_synced_at` remains null for compatibility; use `retrieved_at`.

HTML is reduced to visible text, scripts/styles are removed, text fields are bounded and contact details are removed from excerpts/search terms. Required links must be HTTPS without credentials or non-default ports. Full descriptions are transient; only bounded listing/application fields reach the client. No model calls occur.

## Persistence and applications

The Jobs-owned `elo_jobs` database stores only `job_applications`: private owner ID, listing snapshot, version and status history. Search/filter/posting reads work without database storage. Saving a job re-reads the provider data and snapshots a validated listing. Repeated saves return the existing owner-scoped record even when the provider is unavailable. Updates/removal require `expected_version`; stale writes return 409. History retains 50 changes and each owner can save 500 records. All routes require verified accounts and completed onboarding through Profile's API.

Application lists and updates make no provider calls and report `posting_status: unknown`, so a provider outage or missing catalogue never falsely labels a saved job removed. The UI directs users to check the employer site. Existing snapshots remain valid; legacy `job_postings` and `job_sources` collections are ignored and never destructively migrated. Legacy catalogue helpers/tests remain for compatibility, but are not used by the deployed API.

## Pasted job links

`POST /applications/link` saves a job the user found elsewhere. The user supplies the link, title and employer; elo never fetches the link, so no private address or third-party page is reached and no listing content is copied. Links must be HTTPS on a public-looking host, without credentials or a non-default port. Fragments and `utm_` parameters are dropped so the same job is one record per owner. A link already saved, including one matching a saved listing, returns that record. These records use `source: link`, report `posting_status: unknown` and share the 500-record limit.

## External search links

`GET /external-searches` builds links to Prosple, Huzzle, LinkedIn and Indeed from fixed addresses. They are outbound links only, not listing sources. Huzzle has no location parameter, so its results are not limited to Singapore.

## Commercial terms

Checked on 5 November 2026; not legal advice. The Greenhouse, Lever and Ashby terms that could be read bind their customers. They neither clearly permit nor clearly prohibit an outside company's commercial use of public listings, and job content appears to belong to employers. This design therefore limits exposure by storing and showing an excerpt rather than the full description, crediting the employer and provider, linking to the employer's site, and supporting per-employer removal.

Before launch, get written confirmation from each provider and review each provider's terms and Singapore personal-data obligations with a qualified adviser. Adzuna is deliberately excluded because its licence terms did not suit this product. MyCareersFuture is excluded because no official API or terms were found.

## Known limits

Coverage is limited to configured employer boards, with an emphasis on technology and finance. This is not a search across the entire web, LinkedIn, Indeed or MyCareersFuture. External search links are separate and their results are not part of elo's search. Industry is assigned per employer in the registry. Many providers omit employment type, work arrangement and posting dates. Live reads increase latency and depend on provider availability; synthetic tests do not establish production throughput or provider permission.
