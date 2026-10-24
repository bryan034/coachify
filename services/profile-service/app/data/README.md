# School reference snapshots

`schools.json` is bundled with the service, not stored as a directory collection
in MongoDB. Source metadata and snapshot date are inside the file. Public API
responses contain paginated suggestions and a coverage disclaimer.

Sources:

- MOE, **General information of schools**, accessed 24 October 2026:
  https://data.gov.sg/datasets/d_688b934f82c1059ed0a6993d2a829089/view
  Used under the Singapore Open Data Licence: https://data.gov.sg/open-data-licence.
  Only institution names/levels are retained; staff names/contact data are discarded.
- ITE colleges: https://www.ite.edu.sg/about-ite/colleges/
- Polytechnic names: https://www.moe.gov.sg/post-secondary/overview
- Hipo university-domains-list, commit
  `603e10f51b67c6553b9bca9aecc0db4c2417ed10`:
  https://github.com/Hipo/university-domains-list
  MIT licence reproduced in `HIPO-LICENSE.txt`.

`singapore-tertiary.json` is the small manually reviewed supplement. International
records are suggestions, not a complete/official/accreditation register. Former
institutions and non-university providers can appear upstream. Missing schools
must not make a user ineligible; P01 supports custom entry.

## Refresh

With Profile service dependencies installed, run from `services/profile-service`:

```sh
python scripts/refresh_schools.py
```

The script fetches MOE and the pinned Hipo revision, checks the inputs and replaces
`schools.json` after a successful build. Optional `--moe-file` and
`--universities-file` arguments accept downloaded JSON. MOE works at public limits
without a key; `DATA_GOV_SG_API_KEY` is optional for higher limits.

Review the diff and counts, run service tests, then rebuild the service. The current
snapshot includes 147 secondary schools, including mixed-level P1–S4 institutions.
IDs derive from country/name; reconcile renames explicitly without rewriting saved
user declarations. Updating Hipo requires reviewing its new revision and licence.
School data loads once per process; restart/redeploy after a refresh.

## Employment reference snapshot

`employment.json` contains **7,120 employer suggestions**, including **6,396 with
positive employee counts**, 551 with Singapore country codes, and 134 country codes
overall. Retrieved 25 October 2026 from [Wikidata](https://www.wikidata.org), whose
structured entity data is [CC0](https://www.wikidata.org/wiki/Wikidata:Licensing).
Each row retains its Wikidata ID/source URL, employee count, reporting date when
available, and country codes. The 26 industry labels remain editorial suggestions.

The source query selects up to 7,000 entities directly classified as a business,
company, public company, enterprise, corporation, brick-and-mortar business, record
label, publisher or joint-stock company, with reported headcounts and no recorded
dissolution. Existing reviewed seed organisations (including Singapore employers)
are retained through `employment-seeds.json`. The Singapore supplement now has
**713 entries**, selected using Singapore country or headquarters data, including
employers without reported headcounts. `singapore-employment-source.json` records
the two source queries and manually checked additions. Country-tagged candidates
with conflicting foreign headquarters were excluded; missing country tags can be
supplemented by Singapore headquarters or a cited company source. This is a
reference snapshot, not verification of current legal registration or operations.

Seed rows marked `singapore_based=true` retain that provenance in future refreshes;
the flag is not exposed as a profile field. Expanding the regional coverage requires
reviewing and updating seeds using those source queries; the ordinary refresh
updates retained names/counts without re-certifying headquarters. Missing English/multilingual names,
invalid counts and duplicate display names are excluded. The selection query and
ranking rules are embedded in the snapshot for inspection.

Suggestions sort by latest dated non-deprecated headcount; undated observations
are used only when no dated observation exists. Future dates are ignored. Ties
prefer preferred-rank statements, then higher count. Counts above five million,
more than tenfold a preceding dated observation, or manually flagged outliers are
withheld pending review; those names stay searchable without a count. This is a
bounded public-data directory, not a complete registry, employer verification or
live global ranking. Counts may be old, incomplete or inaccurate, and subsidiaries
can appear separately. Employee size is only a suggestion-ordering heuristic.

No API keys, user downloads or runtime external calls are needed. The directory
stays outside MongoDB; profile company/industry text still accepts manual names.

From `services/profile-service`, with its dependencies installed:

```sh
python scripts/refresh_companies.py
```

The refresh downloads candidates and dated employee observations, validates
coverage, then atomically replaces the snapshot only if at least 5,000 named
employers have positive counts. Failed/incomplete downloads preserve the existing
file. `--candidates-file` and `--details-dir` accept downloaded SPARQL JSON for an
offline rebuild; `--snapshot-date YYYY-MM-DD` makes its cutoff explicit. Review the
diff/counts and flagged outliers, run service tests, and rebuild/restart the service.
