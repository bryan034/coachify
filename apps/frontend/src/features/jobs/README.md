# Search Jobs

`/jobs` is a separate authenticated workspace destination beside Skills Profile.
Users enter a job title/skill and location, then open encoded searches on LinkedIn
or Indeed in a new tab. The page does not fetch, scrape, rank or store listings,
track applications, or send CV/profile data. External sites own results, availability,
sign-in and applications; there is no integrated job-listing API in this slice.

Search fields and submitted links live only in page memory. Changing either field
clears stale links; there is no automatic search or browser storage. Links use fixed
HTTPS origins with URL-encoded parameters and `noopener noreferrer`. A separate
Career Goal link lets users bring a chosen job description into the existing intake.
Skills Profile remains at `/cv` with all existing upload/extraction/review behavior.
