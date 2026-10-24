# Profile service

Stores each user's background, education and planning preferences so future
assessments and roadmaps can use their saved information. P01–P16 are available.

## Shared profile — P01–P08

| Endpoint | What it does |
|---|---|
| `GET /api/v1/profile` | Load your latest saved details. |
| `PATCH /api/v1/profile` | Save changes to background, education, application date or weekly hours. |
| `GET /api/v1/profile/versions/{version}` | Read an earlier saved profile. |

## Education choices — P01–P03, P07/P08

| Endpoint | What it does |
|---|---|
| `GET /api/v1/profile/school-categories` | List the five school categories. |
| `GET /api/v1/profile/school-countries` | List countries for university searches. |
| `GET /api/v1/profile/institutions` | Search school suggestions by category, name and country. |

Users can also enter an unlisted institution. Students provide current education;
other occupational statuses use their last education.

## Planning preferences — P04–P06

The shared profile endpoints above save the application date (P04) and normal
weekly hours (P05). P06 adds temporary periods of lower availability:

| Endpoint | What it does |
|---|---|
| `POST /api/v1/profile/availability-periods` | Add a reduced-availability period. |
| `PATCH /api/v1/profile/availability-periods/{period_id}` | Change a period. |
| `DELETE /api/v1/profile/availability-periods/{period_id}` | Remove a period. |
| `GET /api/v1/profile/planning-inputs` | Read planning preferences and any issues that need attention. |

Periods use inclusive Singapore dates and cannot overlap. Planning preferences
supply inputs; they do not generate a roadmap.

## Account access — P09–P12

| Endpoint | What it does |
|---|---|
| `GET /api/v1/profile/auth-config` | Read safe email/Google capabilities and the server-selected mode. |
| `GET /api/v1/profile/auth/local-accounts` | Choose an existing development account (disabled in Google mode). |
| `POST /api/v1/profile/auth/attempts` | Start a registration or sign-in attempt. |
| `POST /api/v1/profile/auth/complete` | Register with email/password (or configured Google), or sign in; new accounts require email verification. |
| `POST /api/v1/profile/auth/attempts/cancel` | Cancel an access attempt. |
| `GET /api/v1/profile/auth/session` | Validate the current Coachify session. |
| `POST /api/v1/profile/auth/logout` | Revoke that session without deleting saved data. |

Private requests use a Coachify session bearer. Email accounts sign in with email
and password. The current local configuration disables Google sign-in. New registrations
accept any valid email address and require an emailed OTP. Development can use synthetic accounts with a chooser that only prefills email,
or email/password sign-in with real Gmail delivery; see the [setup guide](../../docs/setup.md#local-emailpassword-sign-in-and-real-gmail-delivery).

## Initial setup — P13/P14

| Endpoint | What it does |
|---|---|
| `POST /api/v1/profile/onboarding/complete` | Validate and atomically save initial background plus its completion marker. |

`GET /api/v1/profile` includes canonical `onboarding_complete` and `onboarding_state`.
Partial PATCH saves do not complete setup. Students provide category, institution
and current year; other statuses can explicitly choose no previous education.
Course and planning inputs are optional. Ordinary edits preserve initial completion.

## Email verification — P16

| Endpoint | What it does |
|---|---|
| `POST /api/v1/profile/auth/verify-email` | Activate a pending account using its six-digit emailed OTP. |
| `POST /api/v1/profile/auth/resend-verification` | Send a replacement code subject to cooldown/rate limits. |

Pending accounts have no private session. Codes expire in 10 minutes, allow five
incorrect guesses and are replaced on resend. Local mail appears at localhost:8025.

## Environment and legacy data — P15

`local_test` is development-only. `email` enables email/password production access;
`google` adds Google access. Production requires encrypted authenticated SMTP and a
server-only OTP hash key. Existing profiles are preserved; the explicit dry-run
[legacy mapping script](scripts/map_legacy_owner.py) can map a fixed local owner
without copying history. See [service rules](SPECIFICATION.md) for its procedure.

## Using the service

Only the signed-in owner can read or change private details. Writes include the
latest `expected_version`; planning and Finish setup writes also need an `Idempotency-Key` so retries
are safe. Deletion takes `expected_version` as a query parameter. Planning-input
reads require the device `time_zone`; optional `start_date` and `end_date` give a capacity window.

- [Run the application](../../docs/setup.md) · [Run tests](../../docs/testing.md)
- [Detailed service rules](SPECIFICATION.md) · [School data](app/data/README.md)
- [Request/response schemas](../../contracts/api/profile.yaml)
