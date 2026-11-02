# styles

Shared styling loads in this order: `globals.css` (layout, controls and feature
styles), `career-briefing.css` (saved-goal presentation), then `elo-theme.css`
(current brand tokens and responsive visual refinements). Update the named
palette in `elo-theme.css` when changing shared colours. Mint is an accent;
dark green provides readable text on mint-mist surfaces. Error/warning colours
remain semantic. Fonts are bundled locally under `public/fonts/`.

Sent message bubbles in CV/manual intake, Career Discovery, saved-goal chat and
Roadmap adviser use the shared mint accent (`--mint`) with ink text. CV question
shortcuts appear in the scrollable conversation, without a separate question-review
panel above the composer.
