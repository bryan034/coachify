# Search Jobs

`/jobs` is a separate authenticated workspace destination beside Skills Profile. It uses the [Jobs service](../../../../../services/jobs-service/README.md) through [`lib/api/jobs.ts`](../../lib/api/jobs.ts).

**Find jobs** fetches live Singapore jobs and internships, newest first. Users search by keyword and filter by job type, industry, date posted (preset or custom range), work arrangement and employer. Filters apply as they change; keywords apply on submit. Search state stays in page memory, with no browser storage. Each search reads configured employer boards again, including repeated searches with unchanged keywords. Partial provider failures are shown and no publication date is invented when the provider omits one.

Each listing shows an excerpt and links to the employer's site for the full job and the application. Choosing **Apply on employer site** opens the employer's form in a new tab, saves the job, and asks whether the user submitted it. The status becomes `applied` only if the user confirms. Elo sends nothing to employers.

**My applications** lists saved jobs with a self-reported status. Listings stay readable from their saved copy. Their current availability is unknown until checked on the employer site. A change made in another session shows a message and reloads the saved state instead of overwriting it.

After a keyword search, LinkedIn and Indeed links offer a wider search, sending only the keywords and Singapore as the location. A separate link lets users bring a chosen job description into Career Goal intake. Links open with `noopener noreferrer`, and listing links render only when they use HTTPS.
