const base = process.env.NEXT_PUBLIC_API_BASE_URL || '/api/v1';

export type JobType = 'internship' | 'graduate' | 'full_time' | 'part_time' | 'contract' | 'temporary' | 'unknown';
export type Workplace = 'onsite' | 'hybrid' | 'remote' | 'unknown';
export type ApplicationStatus = 'saved' | 'applied' | 'interviewing' | 'offer' | 'rejected' | 'withdrawn';

export type Posting = {
 id: string; title: string; company: string; industry: string; location: string; department: string | null;
 job_type: JobType; workplace: Workplace; posted_at: string; posted_at_estimated: boolean; application_deadline: string | null;
 excerpt: string; listing_url: string; apply_url: string; provider: string; status: 'open' | 'closed';
};
export type SearchResult = { items: Posting[]; total: number; next_cursor: string | null; retrieved_at?: string | null; unavailable_sources?: string[] };
export type FilterOption = { value: string; count: number };
export type FilterOptions = { job_types: FilterOption[]; industries: FilterOption[]; workplaces: FilterOption[]; companies: FilterOption[]; last_synced_at: string | null };
export type Application = {
 id: string; posting_id: string; version: number; status: ApplicationStatus; posting_status: 'open' | 'closed' | 'removed' | 'unknown';
 snapshot: { title: string; company: string; location: string; job_type: JobType; listing_url: string; apply_url: string };
 history: { status: ApplicationStatus; at: string }[]; created_at: string; updated_at: string;
};
export type JobFilters = {
 q?: string; job_type?: string[]; industry?: string[]; workplace?: string[]; company?: string[];
 posted_within_days?: number; posted_from?: string; posted_to?: string; cursor?: string;
};

export class JobsError extends Error { constructor(message: string, public status: number, public code: string) { super(message); } }

const invalid = () => new JobsError('The job service returned an unexpected response. Retry shortly.', 502, 'invalid_response');
const isOptions = (value: unknown) => Array.isArray(value) && value.every(o => typeof o?.value === 'string' && Number.isInteger(o?.count));
const isApplication = (value: Application) => typeof value?.id === 'string' && Number.isInteger(value?.version) && typeof value?.status === 'string' && typeof value?.snapshot?.title === 'string';

async function request(path: string, token: string, init: RequestInit = {}): Promise<unknown> {
 const response = await fetch(`${base}/jobs${path}`, { cache: 'no-store', ...init, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } });
 if (response.status === 204) return null;
 const value = await response.json().catch(() => ({}));
 if (!response.ok) {
  if (response.status === 401) window.dispatchEvent(new CustomEvent('elo:expired', { detail: token }));
  throw new JobsError(typeof value.detail === 'string' ? value.detail : 'The job service is temporarily unavailable. Retry shortly.', response.status, value.code || 'request_failed');
 }
 return value;
}

export function searchQuery(filters: JobFilters) {
 const query = new URLSearchParams();
 for (const [key, value] of Object.entries(filters)) {
  if (Array.isArray(value)) value.forEach(item => query.append(key, item));
  else if (value !== undefined && value !== '') query.set(key, String(value));
 }
 const text = query.toString();
 return text ? `?${text}` : '';
}

export async function searchJobs(token: string, filters: JobFilters, signal?: AbortSignal) {
 const value = await request(`/search${searchQuery(filters)}`, token, { signal }) as SearchResult;
 if (!Array.isArray(value?.items) || !Number.isInteger(value?.total) || !value.items.every(p => typeof p?.id === 'string' && typeof p?.title === 'string' && typeof p?.apply_url === 'string')) throw invalid();
 return value;
}

export async function readJobFilters(token: string, signal?: AbortSignal) {
 const value = await request('/filters', token, { signal }) as FilterOptions;
 if (!isOptions(value?.job_types) || !isOptions(value?.industries) || !isOptions(value?.workplaces) || !isOptions(value?.companies)) throw invalid();
 return value;
}

export async function listApplications(token: string, signal?: AbortSignal) {
 const value = await request('/applications', token, { signal }) as { items: Application[] };
 if (!Array.isArray(value?.items) || !value.items.every(isApplication)) throw invalid();
 return value.items;
}

async function application(path: string, token: string, init: RequestInit) {
 const value = await request(path, token, init) as Application;
 if (!isApplication(value)) throw invalid();
 return value;
}

export const saveApplication = (token: string, postingId: string) =>
 application('/applications', token, { method: 'POST', body: JSON.stringify({ posting_id: postingId }) });

export const updateApplication = (token: string, item: Application, status: ApplicationStatus) =>
 application(`/applications/${item.id}`, token, { method: 'PATCH', body: JSON.stringify({ expected_version: item.version, status }) });

export const removeApplication = (token: string, item: Application) =>
 request(`/applications/${item.id}?expected_version=${item.version}`, token, { method: 'DELETE' });
