# Socials service

Chats & Socials lets invited members book online coffee chats with curated
experts. Socials owns availability, bookings, pilot credits, prep and notes,
and reports. Profile verifies sessions and Career supplies the current goal
for optional expert matching.

All routes below are under `/api/v1/socials`.

## Member and expert workspace

- `GET /workspace` returns access, credits, expert recommendations and own bookings.
- `GET /experts/{expert_id}/slots` returns bookable times and durations.
- `POST /bookings` requests a chat and reserves one credit per 30 minutes.
- `GET /expert/requests` lists the signed-in expert's pending and accepted bookings.
- `POST /bookings/{booking_id}/decision` accepts a pending request with an HTTPS meeting link or declines it and returns the held credits.
- `POST /bookings/{booking_id}/reports` records a participant's report.

## Roadmap follow-up

- `GET /agenda` returns the member's confirmed chat times and follow-up.
- `PATCH /bookings/{booking_id}/follow-up` updates the member's private prep and notes.

## Pilot operations

- `PUT /operator/members/{member_id}/access` changes access and grants pilot credits.
- `PUT /operator/experts/{expert_id}` creates or updates a curated expert.
- `POST /operator/experts/{expert_id}/slots` publishes an appointment window.
- `GET /operator/reports` returns up to 100 recent reports for review.

See the [pilot specification](SPEC.md) for operator payloads and booking rules
and the [OpenAPI contract](../../contracts/api/socials.yaml) for schemas.
Paid credits, in-person meetings, and CV sharing are planned.
