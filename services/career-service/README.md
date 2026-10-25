# Career service

Helps users explore career directions and explicitly save a goal. It also prepares
temporary job-description previews. Sessions and completed onboarding are verified
through Profile; saved CVs are read through the CV service.

## Career exploration — J08

- `GET /api/v1/career/context` — Available saved CVs and AI availability.
- `POST /api/v1/career/explorations` — Start a private draft after AI-processing consent.
- `GET /api/v1/career/explorations/{id}` — Restore saved progress.
- `POST /api/v1/career/explorations/{id}/messages` — Answer, skip or refine with the assistant.
- `POST /api/v1/career/explorations/cv/document` — Read a temporary optional CV attachment (PDF/DOCX/TXT, up to 10 MiB).

A CV is optional. The UI recommends the dedicated CV upload section and explains
that this career-goal model may interpret current skills less accurately. Saved
processed CVs require explicit selection. Attachments here are temporary context,
not dedicated CV extraction or saved `cvs` records. The agent asks adaptive follow-ups
about aspirations, education, contribution, skills, interests and preferences. Vague
answers stay unresolved; explicit unknown/skip is allowed. The backend checks
quoted user evidence before updating context. Suggestions require addressed context
and stay guidance until confirmation.

## Confirm a career goal — J09

- `GET /api/v1/career/goals` — List saved goals and resumable exploration drafts.
- `GET /api/v1/career/goals/current` — Read the selected goal and selection version.
- `POST /api/v1/career/goals/confirm` — Save reviewed metadata and explicitly select it.

Company is optional. Replacing a goal needs explicit confirmation; prior records
are preserved. Requirements from J03/J10 are not implemented here, so newly saved
goals have **requirements pending** and cannot start gap analysis. Source-grounded
JD persistence/canonical skill mapping, interview research and skill-gap generation remain separate work.

## Job-description previews — J01/J06/J07

Pasted text stays in browser memory. `POST /api/v1/career/imports/url` prepares an
editable public-page preview; `POST /api/v1/career/imports/document` reads one
PDF/DOCX/TXT file up to 10 MiB. Selecting a document reads it automatically; URL
imports still need a click. These previews remain transient and do not call AI.
The imported-source strip is omitted from the editor.

## Extract and clarify JD skills — J02/J03 (temporary review)

- `POST /api/v1/career/jd/extract` — Send a reviewed JD to the configured AI and return role/context plus skill candidates with source quotes.
- `POST /api/v1/career/jd/messages` — Explain reviewed skills and return proposed additions/corrections for explicit approval.

**Extract career goal** opens the same `/career-goal/chat` route used by exploration.
JD facts require exact quotes; user additions and AI recommendations are labelled
separately. Changes are proposals until applied. JD extraction uses native strict
schemas on Groq GPT-OSS 20B/120B when the configured mode is `json_object`; other
models/modes stay explicit. Invalid extraction gets one correction attempt within
the same time budget. Whitespace-only quote differences recover the exact JD span;
paraphrased or invented evidence is still rejected. These two endpoints do not write
MongoDB, assign canonical skill IDs or confirm a goal. Source, transcript and review
stay in account-scoped browser memory; refresh discards them. Publishing reviewed
skills, canonical mapping and the remaining J02/J03 acceptance criteria are future work.

An unavailable configured model returns `model_unavailable`; invalid model JSON
returns `invalid_output` with a safe validation reason and known field names only. See [AI setup/troubleshooting](../../docs/setup.md#optional-groq-configuration).

All routes require the existing bearer session. POST draft/message/confirmation
requests need a UUID `Idempotency-Key`; mutable actions also check expected versions.
Responses are no-store. Full JD/CV source text is not saved; temporary CV text must
be reattached after reload. See [configuration/contracts](ANALYSIS_CONTRACTS.md),
[processing safeguards](SPECIFICATION.md), [API schema](../../contracts/api/career.yaml)
and [application setup](../../docs/setup.md).

For Python code reload in Docker, use the [development Compose override](../../infrastructure/docker/README.md#hot-reload-during-development). Dependency changes need a rebuild; JSON snapshot changes need an API restart.
