import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import { OnboardingFlow } from './onboarding-flow';
import { ProfileProvider } from './profile-provider';
import { WorkspaceGuard } from '@/features/auth/workspace-guard';
const replace = vi.hoisted(() => vi.fn());
const location = vi.hoisted(() => ({ path: '/onboarding' }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ replace }), usePathname: () => location.path }));
const categories = [{ id: 'university', label: 'University' }, { id: 'secondary', label: 'Secondary School' }];
let saved: Record<string, unknown>;
let failure = '';
beforeEach(() => {
  replace.mockReset(); failure = ''; location.path = '/onboarding';
  vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
  saved = { version: 0, onboarding_complete: false, occupational_status: null, school_category: null, education_review_required: false, education: {} };
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/auth-config')) return Response.json({ mode: 'local_test', development_tools_enabled: true });
    if (url.endsWith('/school-categories')) return Response.json(categories);
    if (url.endsWith('/school-countries')) return Response.json([{ code: 'SG', name: 'Singapore' }]);
    if (url.includes('/institutions?')) return Response.json({ items: [], total: 0, snapshot_date: '2026-10-24', coverage_note: 'Synthetic schools' });
    if (url.endsWith('/auth/session')) return Response.json({ id: 'synthetic', name: 'Synthetic', provider: 'local_test', email_verified: true });
    if (url.endsWith('/auth/logout')) return Response.json({ ok: true });
    if (init?.method === 'PATCH' || url.endsWith('/onboarding/complete')) {
      if (failure === 'outage') return Response.json({ detail: 'Synthetic save outage' }, { status: 503 });
      if (failure === 'conflict') return Response.json({ detail: 'Synthetic version conflict' }, { status: 409 });
      const fields = JSON.parse(String(init?.body));
      saved = { ...saved, ...fields, education: { ...(saved.education as object), ...fields.education }, employment: { ...(saved.employment as object), ...fields.employment }, version: Number(saved.version) + 1, onboarding_complete: url.endsWith('/onboarding/complete') };
      if (failure === 'lost') throw new TypeError('Synthetic lost committed response');
    }
    return Response.json(saved);
  }));
});
async function open() {
  render(<ProfileProvider><WorkspaceGuard><OnboardingFlow /></WorkspaceGuard></ProfileProvider>);
  await screen.findByRole('heading', { name: 'Where are you right now?' });
}
async function workAnswers() {
  await screen.findByRole('textbox', { name: 'Place of employment' });
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Synthetic company' } });
  fireEvent.click(screen.getByRole('button', { name: /Continue/ }));
  await screen.findByRole('textbox', { name: 'Role' });
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Synthetic analyst' } });
  fireEvent.click(screen.getByRole('button', { name: /Continue/ }));
  await screen.findByRole('textbox', { name: 'Industry' });
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Synthetic industry' } });
  fireEvent.click(screen.getByRole('button', { name: /Continue/ }));
}
async function noEducation() {
  await open(); fireEvent.click(screen.getByRole('button', { name: 'Employed' }));
  await workAnswers();
  await screen.findByRole('heading', { name: 'Your last education path.' });
  fireEvent.click(screen.getByRole('button', { name: 'No applicable previous education' }));
  await screen.findByRole('button', { name: /Enter Coachify/ });
}
test('one question at a time; saves do not unlock the app; completion does', async () => {
  await noEducation();
  expect(saved.onboarding_complete).toBe(false);
  expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  expect(replace).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: /Enter Coachify/ }));
  await waitFor(() => expect(replace).toHaveBeenCalledWith('/dashboard'));
  expect(saved.no_previous_education).toBe(true);
});
test('student unlisted school, optional course, extended year and review use existing endpoints', async () => {
  await open(); fireEvent.click(screen.getByRole('button', { name: 'Student' }));
  await screen.findByRole('heading', { name: 'Choose your education path.' });
  expect(saved.version).toBe(0); // Student + category are one valid initial save.
  fireEvent.click(screen.getByRole('button', { name: 'University' }));
  await screen.findByRole('heading', { name: 'Where are you studying?' });
  fireEvent.click(screen.getByRole('button', { name: 'My school isn’t listed' }));
  fireEvent.change(screen.getByRole('textbox', { name: 'School name' }), { target: { value: 'Synthetic college' } });
  fireEvent.click(screen.getByRole('button', { name: /Continue/ }));
  await screen.findByRole('heading', { name: 'What course are you studying?' });
  fireEvent.click(screen.getByRole('button', { name: /No applicable named course/ }));
  await screen.findByRole('heading', { name: 'Which year are you in?' });
  fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '6' } });
  fireEvent.click(screen.getByRole('button', { name: /Continue/ }));
  await screen.findByRole('button', { name: /Enter Coachify/ });
  expect(saved.education).toMatchObject({ institution: { kind: 'custom', name: 'Synthetic college' }, course: null, study_year: 6 });
  expect(saved.onboarding_complete).toBe(false);
  fireEvent.click(screen.getByRole('button', { name: /Enter Coachify/ }));
  await waitFor(() => expect(replace).toHaveBeenCalledWith('/dashboard'));
});
test('failed save retains the current question and draft, and supports retry', async () => {
  await noEducation(); failure = 'outage';
  fireEvent.click(screen.getByRole('button', { name: /Enter Coachify/ }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Synthetic save outage');
  expect(saved.onboarding_complete).toBe(false); expect(replace).not.toHaveBeenCalled();
  failure = ''; fireEvent.click(screen.getByRole('button', { name: /Enter Coachify/ }));
  await waitFor(() => expect(replace).toHaveBeenCalledWith('/dashboard'));
});
test('lost committed finish is confirmed by server readback without another POST', async () => {
  await noEducation(); failure = 'lost'; fireEvent.click(screen.getByRole('button', { name: /Enter Coachify/ }));
  await waitFor(() => expect(replace).toHaveBeenCalledWith('/dashboard'));
  expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith('/onboarding/complete'))).toHaveLength(1);
});
test('conflict keeps the draft and requires canonical reconciliation before retry', async () => {
  await noEducation(); failure = 'conflict'; fireEvent.click(screen.getByRole('button', { name: /Enter Coachify/ }));
  await screen.findByRole('button', { name: 'Load latest version and keep my draft' });
  expect(screen.getByRole('button', { name: /Enter Coachify/ })).toBeDisabled();
  saved = { ...saved, version: 7 }; failure = '';
  fireEvent.click(screen.getByRole('button', { name: 'Load latest version and keep my draft' }));
  await waitFor(() => expect(screen.getByRole('button', { name: /Enter Coachify/ })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: /Enter Coachify/ }));
  await waitFor(() => expect(replace).toHaveBeenCalledWith('/dashboard'));
  expect(saved.version).toBe(8);
});
test('X signs out and clears the account rather than skipping onboarding', async () => {
  await open(); fireEvent.click(screen.getByRole('button', { name: 'Exit setup and sign out' }));
  await waitFor(() => expect(sessionStorage.getItem('coachify.session')).toBeNull());
  expect(replace).toHaveBeenCalledWith('/');
  expect(screen.queryByRole('heading', { name: 'Where are you right now?' })).not.toBeInTheDocument();
});

test('retained education in a changed context waits for explicit review and preserves the old saved details', async () => {
  saved = { version: 4, onboarding_complete: false, occupational_status: 'student', school_category: 'university', education_review_required: true,
    education: { institution: { kind: 'custom', name: 'Synthetic old school' }, course: 'Previous course', study_year: 3, study_year_category: 'secondary' } };
  render(<ProfileProvider><WorkspaceGuard><OnboardingFlow /></WorkspaceGuard></ProfileProvider>);
  await screen.findByRole('textbox', { name: 'School name' });
  fireEvent.change(screen.getByRole('textbox', { name: 'School name' }), { target: { value: 'Synthetic new school' } });
  fireEvent.click(screen.getByRole('button', { name: /Continue/ }));
  await screen.findByRole('heading', { name: 'What course are you studying?' });
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'New course' } });
  fireEvent.click(screen.getByRole('button', { name: /Continue/ }));
  await screen.findByRole('spinbutton'); fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '1' } });
  fireEvent.click(screen.getByRole('button', { name: /Continue/ }));
  await screen.findByRole('button', { name: /Enter Coachify/ });
  expect(saved.version).toBe(4);
  expect(saved.education).toMatchObject({ institution: { name: 'Synthetic old school' } });
  expect(screen.getByRole('button', { name: /Enter Coachify/ })).toBeDisabled();
  fireEvent.click(screen.getByRole('checkbox', { name: /I have reviewed/ }));
  fireEvent.click(screen.getByRole('button', { name: /Enter Coachify/ }));
  await waitFor(() => expect(replace).toHaveBeenCalledWith('/dashboard'));
  expect(saved.education).toMatchObject({ institution: { name: 'Synthetic new school' }, course: 'New course', study_year: 1 });
  expect(saved.confirm_education_context).toBe(true);
});

test('employed onboarding asks workplace and role separately, persists both and restores the next unanswered question', async () => {
  saved = { ...saved, version: 2, occupational_status: 'employed', employment: { employer: 'Synthetic saved employer', role: null } };
  render(<ProfileProvider><WorkspaceGuard><OnboardingFlow /></WorkspaceGuard></ProfileProvider>);
  await screen.findByRole('heading', { name: 'What is your role?' });
  expect(screen.queryByRole('textbox', { name: 'Place of employment' })).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole('textbox', { name: 'Role' }), { target: { value: 'Synthetic role' } });
  fireEvent.click(screen.getByRole('button', { name: /Continue/ }));
  await screen.findByRole('textbox', { name: 'Industry' });
  fireEvent.change(screen.getByRole('textbox', { name: 'Industry' }), { target: { value: 'Synthetic industry' } });
  fireEvent.click(screen.getByRole('button', { name: /Continue/ }));
  await screen.findByRole('heading', { name: 'Your last education path.' });
  expect(saved.employment).toEqual({ employer: 'Synthetic saved employer', role: 'Synthetic role', industry: 'Synthetic industry' });
  expect(saved.onboarding_complete).toBe(false);
});

test('development preview starts fresh and makes no writes or completion reset', async () => {
  location.path = '/onboarding/preview';
  saved = { ...saved, version: 12, onboarding_complete: true, occupational_status: 'student', school_category: 'secondary', education: { course: 'Saved private course' } };
  const original = structuredClone(saved);
  render(<ProfileProvider><WorkspaceGuard><OnboardingFlow preview /></WorkspaceGuard></ProfileProvider>);
  await screen.findByRole('heading', { name: 'Where are you right now?' });
  expect(screen.queryByText('Saved private course')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Employed' })); await workAnswers();
  fireEvent.click(await screen.findByRole('button', { name: 'No applicable previous education' }));
  fireEvent.click(await screen.findByRole('button', { name: /Finish preview/ }));
  expect(replace).toHaveBeenCalledWith('/profile'); expect(saved).toEqual(original);
  expect(vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === 'PATCH' || init?.method === 'POST')).toHaveLength(0);
});

test.each([true, false])('unemployed work history branch: previously employed %s', async answer => {
  await open(); fireEvent.click(screen.getByRole('button', { name: 'Unemployed' }));
  await screen.findByRole('heading', { name: 'Have you worked before?' });
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: answer ? 'Yes, I have' : 'No, not yet' }));
  if (answer) {
    await screen.findByRole('textbox', { name: 'Previous employer' });
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Unlisted previous company' } });
    fireEvent.click(screen.getByRole('button', { name: /Continue/ }));
    await screen.findByRole('textbox', { name: 'Role' });
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Previous role' } });
    fireEvent.click(screen.getByRole('button', { name: /Continue/ }));
    await screen.findByRole('textbox', { name: 'Industry' });
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Unlisted industry' } });
    fireEvent.click(screen.getByRole('button', { name: /Continue/ }));
  }
  await screen.findByRole('heading', { name: 'Your last education path.' });
  expect(saved.previously_employed).toBe(answer);
  expect(saved.employment).toEqual(answer ? { employer: 'Unlisted previous company', role: 'Previous role', industry: 'Unlisted industry' } : {});
  fireEvent.click(screen.getByRole('button', { name: 'No applicable previous education' }));
  fireEvent.click(await screen.findByRole('button', { name: /Enter Coachify/ }));
  await waitFor(() => expect(replace).toHaveBeenCalledWith('/dashboard'));
});

test('never-employed users answer graduation immediately after their school and save it', async () => {
  await open(); fireEvent.click(screen.getByRole('button', { name: 'Unemployed' }));
  fireEvent.click(await screen.findByRole('button', { name: 'No, not yet' }));
  fireEvent.click(await screen.findByRole('button', { name: 'University' }));
  fireEvent.click(await screen.findByRole('button', { name: 'My school isn’t listed' }));
  fireEvent.change(screen.getByRole('textbox', { name: 'School name' }), { target: { value: 'Synthetic graduate school' } });
  fireEvent.click(screen.getByRole('button', { name: /Continue/ }));
  await screen.findByRole('heading', { name: 'When did you graduate?' });
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole('spinbutton', { name: 'Year of graduation' }), { target: { value: '9999' } });
  fireEvent.click(screen.getByRole('button', { name: /Continue/ }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Enter a graduation year');
  expect((saved.education as Record<string, unknown>).graduation_year).toBeUndefined();
  fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '2024' } });
  fireEvent.click(screen.getByRole('button', { name: /Continue/ }));
  await screen.findByRole('heading', { name: 'What course did you study?' });
  expect(saved.education).toMatchObject({ graduation_year: 2024 });
  fireEvent.click(screen.getByRole('button', { name: /No applicable named course/ }));
  expect(await screen.findByText('2024')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /Enter Coachify/ }));
  await waitFor(() => expect(replace).toHaveBeenCalledWith('/dashboard'));
});

test('resumes missing graduation year before course for a never-employed account', async () => {
  saved = { ...saved, occupational_status: 'unemployed', previously_employed: false, school_category: 'university',
    education: { institution: { kind: 'custom', name: 'Synthetic saved school' }, course: 'Saved course' } };
  render(<ProfileProvider><WorkspaceGuard><OnboardingFlow /></WorkspaceGuard></ProfileProvider>);
  await screen.findByRole('heading', { name: 'When did you graduate?' });
  expect(screen.getByText('Synthetic saved school')).toBeInTheDocument();
});

test('an empty education record can save a new school despite the context review flag', async () => {
  saved = { ...saved, occupational_status: 'unemployed', previously_employed: false, school_category: 'university',
    education_review_required: true, education: {} };
  render(<ProfileProvider><WorkspaceGuard><OnboardingFlow /></WorkspaceGuard></ProfileProvider>);
  fireEvent.click(await screen.findByRole('button', { name: 'My school isn’t listed' }));
  fireEvent.change(screen.getByRole('textbox', { name: 'School name' }), { target: { value: 'Synthetic first school' } });
  fireEvent.click(screen.getByRole('button', { name: /Continue/ }));
  await screen.findByRole('heading', { name: 'When did you graduate?' });
  expect(saved.education).toMatchObject({ institution: { kind: 'custom', name: 'Synthetic first school' } });
  expect(saved.version).toBe(1);
});
