# Profile

P07/P08 controls and school browsing are implemented here. Institution/course/study-year entry (P01–P03) is implemented with partial updates and context review. The frontend calls profile APIs through the gateway; it never writes MongoDB directly.

`ProfileProvider` supplies shared auth/profile state to the workspace. `AccountPanel` renders inline account controls. The editor sends versioned PATCH requests and only publishes successful saves to Home and the sidebar.
