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

See `docs/development/profile-setup.md` from the repository root for refresh steps.
