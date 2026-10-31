# layout

`WorkspaceShell` provides the persistent desktop sidebar and a two-row mobile
header with horizontally scrollable navigation. It uses the shared `BrandLogo`
and the Elo visual tokens from `src/styles/elo-theme.css`. Account details and
sign-out use the existing Profile provider; mobile keeps profile/sign-out controls
above the navigation row.

Skills Profile (`/cv`) and Search Jobs (`/jobs`) are separate main-navigation
items. Skills Profile retains CV upload and skill/evidence extraction; the former
Resume & Tracker combined label is removed. The navigation uses the same active-page
and horizontally scrollable mobile behavior for both destinations.
