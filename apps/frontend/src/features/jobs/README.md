# Search Jobs

`/jobs` is a separate authenticated workspace destination beside Skills Profile. It uses the [Jobs service](../../../../../services/jobs-service/README.md) through [`lib/api/jobs.ts`](../../lib/api/jobs.ts).

**Find jobs** fetches live Singapore jobs and internships, newest first. Users search by keyword and filter by job type, industry, date posted (preset or custom range), work arrangement and employer. Filters apply as they change; keywords apply on submit. Search state stays in page memory, with no browser storage. Each search reads configured employer boards again, including repeated searches with unchanged keywords. Partial provider failures are shown and no publication date is invented when the provider omits one.

Each listing shows an excerpt and links to the employer's site for the full job and the application. Choosing **Apply on employer site** opens the employer's form in a new tab and records nothing in the Jobs service. When the user returns to any workspace page, Elo asks whether they applied, one job at a time. **Yes** adds the job to **My applications** as `applied`; **No** leaves it as it was. Jobs already past `saved` are not asked about. Until answered, the job's ID, title and employer stay in this browser's local storage under the account, so the question survives a reload or closed tab but does not follow the user to another browser. Elo sends nothing to employers.

**My applications** lists saved jobs with a self-reported status. Listings stay readable from their saved copy. Their current availability is unknown until checked on the employer site. A change made in another session shows a message and reloads the saved state instead of overwriting it.

The search bar stays above both views and suggests the current Career Goal's role and skills, read from the Career service. **My applications** is a board with Saved, Applied, Interviewing and Offer columns, plus Closed for rejected or withdrawn jobs when there are any.

**+ Save a job** adds a job found elsewhere from its link, title and employer. Elo doesn't open the link. After a keyword search, the Jobs service's `GET /external-searches` supplies links to Prosple, Huzzle, LinkedIn and Indeed, sending only the keywords, plus Singapore where the site supports a location. A separate link lets users bring a chosen job description into Career Goal intake. Links open with `noopener noreferrer`, and listing links render only when they use HTTPS.
