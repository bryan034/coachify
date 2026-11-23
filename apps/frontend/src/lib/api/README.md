# API clients

Typed HTTP clients call authenticated FastAPI services through the same-origin gateway. `browser-request.ts` sends a public session marker
and same-origin HttpOnly cookies, strips Authorization headers and rejects redirects.
The gateway alone translates browser cookies to private service bearers.
Career validates the JSON structures consumed by JD previews, saved workspaces,
progress, research, chat and completed background operations before rendering.
Malformed successful responses become safe recoverable errors rather than React
failures. Canonical schemas remain in `contracts/api/` and the owning service.

`jobs.ts` searches listings and manages the owner's tracked applications, validating responses before rendering.

`socials.ts` reads the expert directory and member agenda, and sends booking, decision, report and follow-up commands through the gateway.

`assessment.ts` reads the saved skill comparison for Career Goal. It is read-only and never starts an analysis.
