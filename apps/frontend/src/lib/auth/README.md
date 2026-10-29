# Authentication

Profile owns email/password access, email verification and optional Google sign-in.
Successful access creates a Coachify session; protected APIs validate that session
and derive the owner on the server. The frontend keeps its bearer and access epoch
in tab-scoped session storage. Cross-tab epoch changes clear the old account's
private state. Google credentials are used for the access exchange, rather than
being the credential for every subsequent workspace request.

`ProfileProvider` validates the saved session before loading private data. Visible
tabs revalidate every 30 seconds and when returning to the foreground. Healthy
periodic checks run silently, leaving typing and focus uninterrupted. A temporary
validation failure keeps unfinished forms mounted behind the workspace recovery
screen. **Retry session** rechecks access without reloading the page or discarding
drafts. Back/forward cache restoration also checks the saved Profile before access
resumes. Checks are bounded and overlapping triggers share the same request.

Malformed validation responses also remain locked and retryable. There is no
inactivity timeout. Actual session expiry, logout or an account change
clears private state. Failed server logout remains locally locked and offers retry;
it cannot automatically restore the old session. CV contents and unsaved forms
remain in page memory, not browser storage, and an ordinary page reload or explicit
navigation may discard them.

Recovery preserves C-series drafts. An ordinary Profile background refresh can
still populate its editor with changed server values; reconciling concurrent
background edits across tabs is outside this compatibility change.

See the [application setup guide](../../../../../docs/setup.md) and
[Profile service](../../../../../services/profile-service/README.md).
