# Workspace UI

## Current visual system

The October 2026 revision uses the user-supplied Elo SVG and palette, drawing its
broad hero composition, generous spacing, large left-aligned sans-serif headings
and restrained controls from the [Ebury reference](https://land-book.com/websites/94987-ebury-global-growth-unlocked).
The public entry has a mint-mist hero and an original SVG illustration based on
the three connected points in the logo. Login/registration keep the same header
and typography with a dedicated form. Dashboard, navigation, onboarding, CV chat
and career briefings share the visual language without changing their APIs.

| Token | Hex | Use |
|---|---|---|
| Ink | `#111827` | Wordmark, primary text, buttons, dark panels |
| Mint | `#34D399` | Goal point, status and visual accents |
| Snow | `#F8FAFC` | Application background |
| Mint Mist | `#ECFDF5` | Hero, selected navigation and soft accents |
| Cloud | `#F1F5F9` | Neutral controls and surfaces |
| Slate | `#475569` | Secondary text |
| White | `#FFFFFF` | Logo surfaces and form panels |

Inter remains bundled locally. Display headings use regular/medium weights and
tight spacing. Dark green (`#116149`) is an accessible text companion to mint;
error and warning colours keep their semantic meaning. Mobile navigation scrolls
inside its own row. Keyboard focus and reduced-motion support are preserved.

`apps/frontend/public/brand/elo-logo.svg` contains the supplied artwork with its
non-rendering provenance metadata removed and whitespace cropped via its viewBox.
`elo-mark.svg` reuses the supplied symbol for the favicon and chat identities.
`JourneyVisual` is a decorative code-native illustration, not a progress indicator.
No external fonts, images or additional dependencies are needed at runtime.
The final shared overrides live in `apps/frontend/src/styles/elo-theme.css`.

## Original reference

`coachify-web-v1.html` is the user-supplied original design reference, preserved
without executing its scripts in the application. The live app uses typed React
components, Next.js page navigation and existing profile endpoints.

The visual reference defines the sidebar, typography, colour tokens, cards, tables
and responsive layouts. Sample users and activity are not live application data:
the integrated screens use empty states until the relevant service is implemented.
Profile and planning-preference controls are connected to the Profile service;
the Roadmap screen shows their saved summary. Saved CV upload, review and clarification
are available. Bookings, networking, event/task mutations and roadmap generation
remain unavailable. Roadmap/expert
filters and week/month calendar toggles change presentation only.

See the [Profile service README](../../services/profile-service/README.md) for
available endpoints and service rules. Endpoint lists are maintained there rather
than duplicated in this design guide.

Google sign-in stays inline on the account form when enabled. Successful access
opens onboarding or the dashboard according to the saved profile. Local-test mode
continues to work without Google. Profile saves update the shared workspace state.
Home never substitutes a progress percentage for unavailable roadmap data.

## Earlier typography revision

The original condensed Barlow headings were replaced at the user's request after
checking Revolut's Singapore page. Revolut declares Aeonik Pro for headings and
Inter for body text; the font publisher also identifies Aeonik Pro in its Revolut
case study: https://cotypefoundry.com/fonts-in-use/revolut.

Coachify bundles Inter for both headings and body text. The earlier revision used
medium weight, normal case and tighter tracking; labels/buttons no longer use the
condensed, widely spaced uppercase style. This is a visual approximation for the
display face, not a claim to include Aeonik Pro. An exact heading match requires
licensed Aeonik Pro webfonts. Once provided, declare those with `@font-face` and
change `--font-heading` in `src/styles/globals.css` (under `apps/frontend`).

## Saved career briefing

The `/career-goal` overview follows the supplied career-briefing reference while
retaining live saved data and shared workspace navigation. See the
[data map, implemented limits and proposed database extensions](career-briefing.md).
