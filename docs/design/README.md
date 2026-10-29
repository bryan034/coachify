# First workspace UI

`coachify-web-v1.html` is the user-supplied original design reference, preserved
without executing its scripts in the application. The live app uses typed React
components, Next.js page navigation and existing profile endpoints.

The visual reference defines the sidebar, typography, colour tokens, cards, tables
and responsive layouts. Sample users and activity are not live application data:
the integrated screens use empty states until the relevant service is implemented.
Profile and planning-preference controls are connected to the Profile service;
the Roadmap screen shows their saved summary. Upload, bookings, networking,
event/task mutations and roadmap generation remain unavailable. Roadmap/expert
filters and week/month calendar toggles change presentation only.

See the [Profile service README](../../services/profile-service/README.md) for
available endpoints and service rules. Endpoint lists are maintained there rather
than duplicated in this design guide.

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

## Saved career briefing

The `/career-goal` overview follows the supplied career-briefing reference while
retaining live saved data and shared workspace navigation. See the
[data map, implemented limits and proposed database extensions](career-briefing.md).
