# First workspace UI

`coachify-web-v1.html` is the user-supplied original design reference, preserved
without executing its scripts in the application. The live app uses typed React
components, Next.js page navigation and existing profile endpoints.

The visual reference defines the sidebar, typography, colour tokens, cards, tables
and responsive layouts. Sample users and activity are not live application data:
the integrated screens use empty states until the relevant service is implemented.
Timeframe, upload, bookings, networking, event and task mutation controls are disabled.
Roadmap/expert filters and week/month calendar toggles change presentation only.

Current connections:

- `GET /api/v1/profile/auth-config`: validated auth mode.
- `GET /api/v1/profile`: saved background for Home, sidebar and editor.
- `PATCH /api/v1/profile`: editor save using expected version.
- `GET /api/v1/profile/school-categories`: school category choices.
- `GET /api/v1/profile/school-countries`: university search filter.
- `GET /api/v1/profile/institutions`: paginated school snapshot search.

The existing historical-version endpoint remains available to API clients; no
history viewer is introduced here. No routes are added to the backend.

Google sign-in stays inline; `/login` redirects to My profile. Local-test mode
continues to work without Google. Profile saves update the shared workspace state.
Home never substitutes a progress percentage for unavailable roadmap data.

## Typography revision

The original condensed Barlow headings were replaced at the user's request after
checking Revolut's Singapore page. Revolut declares Aeonik Pro for headings and
Inter for body text; the font publisher also identifies Aeonik Pro in its Revolut
case study: https://cotypefoundry.com/fonts-in-use/revolut.

Coachify currently bundles Inter for both headings and body text. Headings use
medium weight, normal case and tighter tracking; labels/buttons no longer use the
condensed, widely spaced uppercase style. This is a visual approximation for the
display face, not a claim to include Aeonik Pro. An exact heading match requires
licensed Aeonik Pro webfonts. Once provided, declare those with `@font-face` and
change `--font-heading` in `src/styles/globals.css` (under `apps/frontend`).
