# ui

Reusable visual primitives. `PageFlow` links Career Goal, Skills Profile and Roadmap and marks the current page.
`Toast` (`useToast`) is the short confirmation pill used on Home. `JourneyVisual` is the illustration on the signed-out entry page. `PathMark`
is retained as an unused primitive; decorative path graphics do not appear on workspace pages.
`ProcessingCard`, `SkeletonRows` and `SkeletonRoad` (`processing-card.tsx`, styled in `styles/processing.css`) are the shared
progress card and placeholders for the Career Goal "Skills needed" and Roadmap generating screens.
`PremiumDialog` (mounted once in the workspace layout) opens on the `elo:premium-required` window event that the Career, CV and Roadmap API clients dispatch for a 402 `premium_required` response; it names the blocked feature and only offers Close.
