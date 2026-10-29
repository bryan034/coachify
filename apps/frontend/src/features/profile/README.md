# Profile

P07/P08 controls and school browsing are implemented here. Institution/course/study-year entry (P01–P03) is implemented with partial updates and context review. The frontend calls profile APIs through the gateway; it never writes MongoDB directly.

`ProfileProvider` supplies shared auth/profile state to the workspace. `AccountPanel` renders inline account controls. The editor sends versioned PATCH requests and only publishes successful saves to Home and the sidebar.

The editor waits until the loaded background values have populated its fields
before enabling edits or Save. This prevents initialization from overwriting the
first selection after a delayed Profile response. Student, National Service,
employed and both unemployed branches keep their existing validation rules.

Session revalidation preserves mounted drafts during temporary connection failures
and offers retry without a page refresh. Confirmed expiry or an account change
clears private state. See the [authentication behavior](../../lib/auth/README.md).
