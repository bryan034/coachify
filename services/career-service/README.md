# Career service

Prepares temporary job-description previews for the **Career Goal** page. It uses
Profile's session API to authenticate imports. Preview endpoints have no database writes or AI calls. Internal AI and MongoDB
contract foundations are available for later Career Goal stories.

## Pasted description — J01

Pasted text stays in browser memory; no API call is made. The page preserves line
breaks and Unicode, counts up to 20,000 characters and flags longer input without
cutting it off. Refreshing or leaving the page discards it.

## URL preview — J06

`POST /api/v1/career/imports/url` accepts `{"url":"https://example.com/job"}`
and returns an editable text preview with its website name, final URL and notices.
Public HTTP/HTTPS HTML pages only. Blocked, unavailable, multi-job and unsupported
pages explain how to retry or use paste/upload instead. No sign-in bypass or
JavaScript rendering is attempted.

## Document preview — J07

`POST /api/v1/career/imports/document` accepts one multipart field named `file`:
PDF, DOCX or UTF-8 TXT, up to **10 MiB**. Returns text, filename and notices.
Scanned PDFs require a text alternative; OCR is not included. Overlong previews
are rejected, not truncated. Source limits and parser safeguards are described in
[SPECIFICATION.md](SPECIFICATION.md).

## Access and scope

Both endpoints require the existing Coachify session as `Authorization: Bearer …`
and server-confirmed initial setup completion. Unfinished accounts receive 403.
Preview responses use `Cache-Control: no-store`. Upload originals may be spooled
into private temporary storage and are closed/deleted after each request. Text is
not written to MongoDB, browser storage, logs or saved processing records.

This is the input/preview slice of J01/J06/J07. Saved goals, restart recovery,
interpretation and J02–J05 review are not implemented. No Groq key is required for previews.
MongoDB contracts now accept approved structured fields and bounded evidence;
full raw/extracted JD text is rejected. See [setup](../../docs/setup.md) and [the API contract](../../contracts/api/career.yaml).

## AI and data foundations — SCRUM-282 / SCRUM-310

A configurable Groq adapter, validated collection models and opt-in repositories
are implemented internally. **No new HTTP endpoints** are exposed. They support
`career_goals`, public interview research and versioned gap analyses; CV owns its
own records. Existing user accounts are reused.

See [configuration and contracts](ANALYSIS_CONTRACTS.md). AI stays disabled by
default; later chat/extraction stories will connect it to the frontend.
