# Jobs service

Lets users find jobs and internships in Singapore live from public employer boards, then apply on the employer's own site and track their progress in elo. It owns the `elo_jobs` database. It does not submit applications or send CV or profile data to employers.

## API by feature

No Jira stories exist for this service yet; add the story IDs here once they are created. All endpoints are under `/api/v1/jobs` and require a verified account with completed onboarding.

| Feature | Available endpoints |
|---|---|
| Search and filter | `GET /search` accepts `q`, `job_type`, `industry`, `workplace`, `company`, `posted_within_days`, `posted_from`, `posted_to`, `cursor` and `limit`. `GET /filters` returns the available values and counts. `GET /postings/{id}` reads one listing. |
| Search elsewhere | `GET /external-searches?q=` returns search links for Prosple, Huzzle, LinkedIn and Indeed. Only the keywords go into the links, and elo reads nothing from those sites. |
| Track applications | `GET /applications` lists the owner's saved jobs. `POST /applications` saves a listing and is safe to repeat. `POST /applications/link` saves a job from a pasted link with its title and employer, and is also safe to repeat. `PATCH /applications/{id}` changes the self-reported status with `expected_version`. `DELETE /applications/{id}?expected_version=` removes it. |

**Not implemented:** submitting applications from elo, tailored application answers, fit scoring, alerts and setting a listing as the Career Goal automatically.

## Filters

| Filter | Source | Limit |
|---|---|---|
| Keywords | Title, employer, department and description terms | Results are newest first, with no relevance ranking |
| Job type | Provider field; a title naming an internship or graduate role takes priority | Roles with no stated type are labelled "Not stated" |
| Date posted | Provider's published date; unknown dates are excluded from date filters | Application deadlines are shown when supplied, but providers rarely supply them, so there is no deadline filter |
| Industry | Assigned per employer in [`sources.json`](app/sources.json), because providers do not supply it | One industry per employer |
| Work arrangement | Provider field, then location text | Roles with no stated arrangement are labelled "Not stated" |
| Employer | [`sources.json`](app/sources.json) | Only configured employers appear |

## Listing sources

Searches fetch public Greenhouse, Lever and Ashby boards at request time without an API key. There is no pre-populated listing database or scheduled worker. The reviewed employer registry is [`sources.json`](app/sources.json); edit it and rebuild `jobs-service` to change coverage. Overlapping search, filter and posting requests share one in-progress provider read per service process, with at most eight boards fetched concurrently. Once that read finishes, the next request fetches fresh data; completed listings are not cached. Partial failures are reported alongside results; total provider failure returns 503.

MongoDB stores only private application snapshots and status history. Listing availability is checked when reading a posting or first saving it; saved applications show availability as unknown until the user checks the employer site. Existing saved records remain readable. Existing catalogue/sync collections are ignored and are not automatically deleted.

Only an excerpt and an unordered word index are held transiently, not the full description, and users read the full job on the employer's site. See [SPEC.md](SPEC.md) for the rules and [Commercial terms](SPEC.md#commercial-terms) for what is still unconfirmed.

See the [contract](../../contracts/api/jobs.yaml), [tests](tests/README.md) and [setup](../../docs/setup.md#jobs-service).
