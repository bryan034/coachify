const base = process.env.NEXT_PUBLIC_API_BASE_URL || '/api/v1';
export class ApiError extends Error { constructor(message: string, public status: number) { super(message); } }
export async function profileApi<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
  const response = await fetch(`${base}/profile${path}`, {
    ...init, cache: 'no-store', headers: { 'Content-Type': 'application/json', ...init.headers,
      ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  if (!response.ok) {
    if (response.status === 401 && token && !path.startsWith('/auth/')) window.dispatchEvent(new CustomEvent('coachify:expired', { detail: token }));
    const body = await response.json().catch(() => ({}));
    const message = typeof body.detail === 'string' ? body.detail
      : Array.isArray(body.detail) ? body.detail.map((error: { loc?: (string | number)[]; msg?: string }) =>
        `${error.loc?.filter(p => p !== 'body').join('.') || 'Profile'}: ${error.msg || 'Invalid value'}`).join(' ')
      : response.status >= 500 ? 'Coachify is temporarily unavailable. Please retry.' : 'Please check your selections and try again.';
    throw new ApiError(message, response.status);
  }
  return response.json();
}
