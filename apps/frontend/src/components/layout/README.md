# layout

`WorkspaceShell` provides a persistent left sidebar on desktop and a Menu button
that expands the same navigation above content on mobile. Selecting a link closes
the mobile menu; Escape closes it and returns focus to Menu. Nested routes keep
their parent navigation item active. CV review retains its focused full-screen layout.

The sidebar uses `BrandLogo` and the Elo visual tokens in
`src/styles/elo-theme.css`. Profile details and sign-out use the existing Profile
provider. Skills Profile (`/cv`) and Search Jobs (`/jobs`) remain separate destinations.
