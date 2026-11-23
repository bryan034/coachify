# Chats & Socials pilot

## Pilot setup

Place the Profile account IDs of pilot operators in
`SOCIALS_OPERATOR_ACCOUNT_IDS` in the central Docker configuration. Each
operator, expert, and member uses a verified Profile session and completes
onboarding. Send API calls through the gateway under `/api/v1/socials`.

1. Create an expert with `PUT /operator/experts/{expert_id}`. Supply an
   `account_id`, `name`, `role`, `field`, and `organisation`. Optional
   `aliases` support Career goal matching. Supply `linkedin_url` when a
   verified public profile is available. Set `active: false` to remove the
   expert from the directory. The account assignment is fixed and the
   expert can still see existing pending and accepted bookings.
2. Publish a window with `POST /operator/experts/{expert_id}/slots`.
   Supply a fresh UUID as `mutation_id`, an offset-aware ISO date and time
   as `starts_at`, and `durations` such as `[30, 60]`. The maximum
   advertised duration defines the exclusive window for that expert.
   Times sit on the minute and fit within one Singapore day. Keep the UUID
   on retries so the same window is returned.
3. Invite a member with `PUT /operator/members/{member_id}/access`. Supply
   a fresh UUID as `mutation_id`, set `enabled: true`, and set `credits`
   to the grant amount. Credits are additive. Retry the same grant with the
   same UUID. Use a separate mutation with `enabled: false` and
   `credits: 0` to revoke directory and booking access.
4. Assign an operator to check `GET /operator/reports`. Each entry identifies
   the booking, reporter account, reason, and submission time. Follow up with
   the people involved through your existing support process.

## Booking, time, and privacy

Adults request an offered time with the slot's current version. A 30-minute
chat reserves one credit and a 60-minute chat reserves two. A pending request
expires at its scheduled start if the expert has yet to decide. Accepting
consumes the held credits. Decline or expiry returns them and releases the
window. Each command uses a unique mutation ID that binds it to its payload.
Updates check the supplied booking version.

The Mongo wallet document owns access, available credits, booking state,
private notes, and mutation receipts for one member. A separate schedule
document owns all the slots for one expert and Singapore date. Slot claims
advance the slot version. To resolve an expired open slot, the service
closes it with a Mongo clock check before returning the credit hold.
The in-process worker retries unfinished claims, overdue decisions, and
pending releases when the process restarts. It uses Socials data alone.

The expert sees the member's display name, question, and booked time.
The member controls their private prep and notes. The member's Career goal
is used privately to match the directory. A failure to load the goal leaves
the directory available after session verification. An accepted chat can
appear in Roadmap independently of a study plan. Both participants retain
reporting after a member loses booking access.

## Verification

Run `python -m pytest` in the service with its test dependencies. Set
`MONGODB_TEST_URI` explicitly to a disposable standalone Mongo instance to
exercise concurrency, recovery, and the API. Each test creates and removes
its own database.
