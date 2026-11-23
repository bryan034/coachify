import { browserRequest } from './browser-request';

export type ChatDuration = 30 | 60;
export type ChatStatus = 'submitting' | 'requested' | 'accepted' | 'declined' | 'expired' | 'slot_unavailable';
export type Expert = {
 id: string; name: string; role: string; field: string; organisation: string; linkedin_url: string | null; open_slots: number;
};
export type ChatSlot = { id: string; version: number; starts_at: string; durations: ChatDuration[] };
export type ChatBooking = {
 id: string; version: number; expert_id: string; expert_name: string; starts_at: string; duration_minutes: ChatDuration;
 status: ChatStatus; question: string; meeting_url: string | null; credits: number; prep_done: boolean; notes: string; member_name: string;
};
type Recommendation = { expert_id: string; role: string };
export type SocialsWorkspace = {
 access: 'enabled' | 'locked'; credits: number; experts: Expert[]; recommendation: Recommendation | null;
 bookings: ChatBooking[]; expert_inbox: boolean;
};
export type RequestChat = {
 expert_id: string; slot_id: string; slot_version: number; duration_minutes: ChatDuration; question: string; adult_attested: true;
};
export type DecideChat = { expected_version: number } & ({ decision: 'accept'; meeting_url: string } | { decision: 'decline' });
export type ChatFollowUp = { expected_version: number; prep_done: boolean; notes: string };
type Mutation<T> = T & { mutation_id: string };

export class SocialsError extends Error {
 constructor(message: string, public status: number) { super(message); }
}

const isObject = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null;
const isCount = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
const isDate = (value: unknown): value is string => typeof value === 'string' && Number.isFinite(Date.parse(value));
const isDuration = (value: unknown): value is ChatDuration => value === 30 || value === 60;
const isStatus = (value: unknown): value is ChatStatus => value === 'submitting' || value === 'requested' || value === 'accepted'
 || value === 'declined' || value === 'expired' || value === 'slot_unavailable';
const isLink = (value: unknown): value is string => {
 if (typeof value !== 'string') return false;
 try { return new URL(value).protocol === 'https:'; } catch { return false; }
};
const isList = <T>(value: unknown, check: (item: unknown) => item is T): value is T[] => Array.isArray(value) && value.every(check);
const isExpert = (value: unknown): value is Expert => isObject(value) && typeof value.id === 'string' && typeof value.name === 'string'
 && typeof value.role === 'string' && typeof value.field === 'string' && typeof value.organisation === 'string'
 && (value.linkedin_url === null || isLink(value.linkedin_url)) && isCount(value.open_slots);
const isSlot = (value: unknown): value is ChatSlot => isObject(value) && typeof value.id === 'string' && isCount(value.version)
 && isDate(value.starts_at) && isList(value.durations, isDuration) && value.durations.length > 0;
const isBooking = (value: unknown): value is ChatBooking => isObject(value) && typeof value.id === 'string' && isCount(value.version)
 && typeof value.expert_id === 'string' && typeof value.expert_name === 'string' && isDate(value.starts_at) && isDuration(value.duration_minutes)
 && isStatus(value.status) && typeof value.question === 'string' && (value.meeting_url === null || isLink(value.meeting_url))
 && isCount(value.credits) && typeof value.prep_done === 'boolean' && typeof value.notes === 'string' && typeof value.member_name === 'string';
const isRecommendation = (value: unknown): value is Recommendation => isObject(value) && typeof value.expert_id === 'string' && typeof value.role === 'string';
const isWorkspace = (value: unknown): value is SocialsWorkspace => isObject(value) && (value.access === 'enabled' || value.access === 'locked')
 && isCount(value.credits) && isList(value.experts, isExpert) && (value.recommendation === null || isRecommendation(value.recommendation))
 && isList(value.bookings, isBooking) && typeof value.expert_inbox === 'boolean';
const isReport = (value: unknown): value is { id: string } => isObject(value) && typeof value.id === 'string';
const isBookingList = (value: unknown): value is ChatBooking[] => isList(value, isBooking);
const isSlotList = (value: unknown): value is ChatSlot[] => isList(value, isSlot);

async function request<T>(path: string, token: string, check: (value: unknown) => value is T, init?: RequestInit): Promise<T> {
 const response = await fetch(`/api/v1/socials${path}`, browserRequest({
  cache: 'no-store', headers: { 'Content-Type': 'application/json' }, ...init,
 }, token));
 const value: unknown = await response.json().catch(() => null);
 if (!response.ok) {
  if (response.status === 401) window.dispatchEvent(new CustomEvent('elo:expired', { detail: token }));
  throw new SocialsError(isObject(value) && typeof value.detail === 'string' ? value.detail : 'Chats & Socials is temporarily unavailable.', response.status);
 }
 if (!check(value)) throw new SocialsError('Chats & Socials returned an unexpected response. Try again shortly.', 502);
 return value;
}

export const loadSocials = (token: string, signal?: AbortSignal) => request('/workspace', token, isWorkspace, { signal });
export const loadChatSlots = (token: string, expertId: string, signal?: AbortSignal) => request(`/experts/${encodeURIComponent(expertId)}/slots`, token, isSlotList, { signal });
export const loadExpertInbox = (token: string, signal?: AbortSignal) => request('/expert/requests', token, isBookingList, { signal });
export const loadChatAgenda = (token: string, signal?: AbortSignal) => request('/agenda', token, isBookingList, { signal });
export const requestChat = (token: string, body: Mutation<RequestChat>) => request('/bookings', token, isBooking, { method: 'POST', body: JSON.stringify(body) });
const bookingPath = (id: string) => `/bookings/${encodeURIComponent(id)}`;
export const decideChat = (token: string, id: string, body: Mutation<DecideChat>) => request(`${bookingPath(id)}/decision`, token, isBooking, { method: 'POST', body: JSON.stringify(body) });
export const reportChat = (token: string, id: string, body: Mutation<{ reason: string }>) => request(`${bookingPath(id)}/reports`, token, isReport, { method: 'POST', body: JSON.stringify(body) });
export const saveChatFollowUp = (token: string, id: string, body: Mutation<ChatFollowUp>) => request(`${bookingPath(id)}/follow-up`, token, isBooking, { method: 'PATCH', body: JSON.stringify(body) });
