from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

Identifier = Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
WebLink = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2048)]
Duration = Literal[30, 60]
BookingStatus = Literal['submitting', 'requested', 'accepted', 'declined', 'expired', 'slot_unavailable']
Version = Annotated[int, Field(ge=1)]


def https_host(link: str) -> str:
    if any(character.isspace() or ord(character) < 32 or character == '\\' for character in link):
        raise ValueError('Enter a valid HTTPS link.')
    parts = urlsplit(link)
    if parts.scheme != 'https' or not parts.hostname or parts.username is not None or parts.password is not None:
        raise ValueError('Enter a valid HTTPS link.')
    if parts.port == 0:
        raise ValueError('Enter a valid HTTPS link.')
    return parts.hostname


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ExpertProfile(Contract):
    name: ShortText
    role: ShortText
    field: ShortText
    organisation: ShortText
    linkedin_url: WebLink | None = None

    @field_validator('linkedin_url')
    @classmethod
    def linkedin_profile(cls, link):
        if link is not None:
            host = https_host(link)
            if not (host == 'linkedin.com' or host.endswith('.linkedin.com')) or not urlsplit(link).path.startswith('/in/'):
                raise ValueError('Enter a LinkedIn profile link.')
        return link


class Expert(ExpertProfile):
    id: Identifier
    open_slots: int


class ExpertUpdate(ExpertProfile):
    account_id: Identifier
    aliases: Annotated[list[ShortText], Field(max_length=20)] = Field(default_factory=list)
    active: bool = True


class Recommendation(Contract):
    expert_id: Identifier
    role: ShortText


class Slot(Contract):
    id: UUID
    version: Version
    starts_at: datetime
    durations: Annotated[tuple[Duration, ...], Field(min_length=1, max_length=2)]


class SlotCreate(Contract):
    mutation_id: UUID
    starts_at: AwareDatetime
    durations: Annotated[tuple[Duration, ...], Field(min_length=1, max_length=2)]

    @field_validator('starts_at')
    @classmethod
    def whole_minute(cls, starts_at):
        if starts_at.second or starts_at.microsecond:
            raise ValueError('Choose a start time on the minute.')
        return starts_at

    @field_validator('durations')
    @classmethod
    def distinct_durations(cls, durations):
        if len(set(durations)) != len(durations):
            raise ValueError('List each duration once.')
        return tuple(sorted(durations))


class Booking(Contract):
    id: UUID
    version: Version
    expert_id: Identifier
    expert_name: ShortText
    starts_at: datetime
    duration_minutes: Duration
    status: BookingStatus
    question: str
    meeting_url: str | None
    credits: int
    prep_done: bool
    notes: str
    member_name: str


class Workspace(Contract):
    access: Literal['locked', 'enabled']
    credits: int
    experts: list[Expert]
    recommendation: Recommendation | None
    bookings: list[Booking]
    expert_inbox: bool


class Mutation(Contract):
    mutation_id: UUID


class RequestChat(Mutation):
    expert_id: Identifier
    slot_id: UUID
    slot_version: Version
    duration_minutes: Duration
    question: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
    adult_attested: Literal[True]

    @field_validator('adult_attested', mode='before')
    @classmethod
    def requires_age_attestation(cls, value):
        if value is not True:
            raise ValueError('Confirm that you are at least 18.')
        return value


class BookingMutation(Mutation):
    expected_version: Version


class DecideChat(BookingMutation):
    decision: Literal['accept', 'decline']
    meeting_url: WebLink | None = None

    @model_validator(mode='after')
    def meeting_details(self):
        if self.decision == 'accept':
            if self.meeting_url is None:
                raise ValueError('Add an HTTPS meeting link to accept the request.')
            https_host(self.meeting_url)
        elif self.meeting_url is not None:
            raise ValueError('A declined request has no meeting link.')
        return self


class FollowUp(BookingMutation):
    prep_done: bool
    notes: Annotated[str, StringConstraints(max_length=4000)]


class AccessUpdate(Mutation):
    enabled: bool
    credits: Annotated[int, Field(ge=0)] = 0


class Access(Contract):
    access: Literal['locked', 'enabled']
    credits: int


class ReportCreate(Mutation):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class ReportReceipt(Contract):
    id: UUID


class Report(ReportReceipt):
    booking_id: UUID
    reporter_id: Identifier
    reason: str
    created_at: datetime
