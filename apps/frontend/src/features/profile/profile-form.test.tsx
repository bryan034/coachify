import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import { ProfileForm } from './profile-form';
import { ProfileProvider } from './profile-provider';
import { educationQuestions } from './types';
vi.mock('@/lib/auth/google-sign-in', () => ({ GoogleSignIn: ({ onCredential }: { onCredential: (t: string) => void }) => <button onClick={() => onCredential('test-only')}>Test sign in</button> }));
vi.mock('./school-browser', () => ({ SchoolBrowser: () => <p>Directory browser</p> }));
const categories = [
  { id: 'secondary', label: 'Secondary School' }, { id: 'ite', label: 'Institute of Technical Education' },
  { id: 'polytechnic', label: 'Polytechnic / Diploma' }, { id: 'junior_college', label: 'Junior College' },
  { id: 'university', label: 'University' },
];
const initial = { version: 0, occupational_status: null, school_category: null, education_context: null, education_review_required: false, education: {} };
let saved: typeof initial | Record<string, unknown>;
let fail: boolean;
let mode: 'google' | 'local_test';
let configFails: boolean;
beforeEach(() => {
  saved = initial; fail = false; mode = 'google'; configFails = false;
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit) => {
    if (url.includes('planning-inputs')) return new Response(JSON.stringify({ profile_version: saved.version, planning_revision: 0, ready: false, issues: [], availability_periods: [] }));
    if (url.includes('auth-config')) return new Response(JSON.stringify(configFails ? { detail: 'Unavailable' } : { mode }), { status: configFails ? 503 : 200 });
    if (url.includes('school-categories')) return new Response(JSON.stringify(categories));
    if (init?.method === 'PATCH') {
      if (fail) return new Response(JSON.stringify({ detail: 'Storage unavailable. Retry.' }), { status: 503 });
      const input = JSON.parse(init.body as string);
      saved = { ...saved, ...input, education: { ...(saved.education as object), ...input.education }, version: Number(saved.version) + 1 };
    }
    return new Response(JSON.stringify(saved));
  }));
});

test('no default status, exact options, student category validation and save retry', async () => {
  render(<ProfileProvider><ProfileForm /></ProfileProvider>);
  expect(screen.getAllByRole('radio')).toHaveLength(4);
  expect(screen.getAllByRole('radio').every(r => !(r as HTMLInputElement).checked)).toBe(true);
  fireEvent.click(await screen.findByText('Test sign in'));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Save background' })).toBeEnabled());
  fireEvent.click(screen.getByRole('radio', { name: 'Student' }));
  expect(screen.getByText('Where are you studying?')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Save background' }));
  expect(screen.getByRole('alert')).toHaveTextContent('Choose a school category');
  fireEvent.click(screen.getByText('University', { exact: true }));
  fail = true;
  fireEvent.click(screen.getByRole('button', { name: 'Save background' }));
  await screen.findByText('Storage unavailable. Retry.');
  expect(screen.getByText('Selected')).toBeInTheDocument();
  expect(screen.queryByText('Profile saved.')).not.toBeInTheDocument();
  fail = false;
  fireEvent.click(screen.getByRole('button', { name: 'Save background' }));
  expect(await screen.findByText('Profile saved.')).toBeInTheDocument();
});

test('nonstudent can leave school unanswered; status changes prompt review', async () => {
  saved = { ...initial, version: 1, occupational_status: 'student', school_category: 'university' };
  render(<ProfileProvider><ProfileForm /></ProfileProvider>);
  fireEvent.click(await screen.findByText('Test sign in'));
  await waitFor(() => expect(screen.getByRole('radio', { name: 'Student' })).toBeChecked());
  fireEvent.click(screen.getByRole('radio', { name: 'Employed' }));
  expect(screen.getByText('Where did you last study?')).toBeInTheDocument();
  expect(screen.getByText(/Please review your education details/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('radio', { name: 'No applicable previous education' }));
  fireEvent.click(screen.getByRole('button', { name: 'Save background' }));
  await screen.findByText('Profile saved.');
  expect(saved.school_category).toBeNull();
});

test('question mapping applies to all statuses', () => {
  expect(educationQuestions('student')).toEqual({ institution: 'Where are you studying?', course: 'What course are you studying?', showYear: true });
  for (const status of ['national_service', 'unemployed', 'employed'] as const) {
    expect(educationQuestions(status)).toEqual({ institution: 'Where did you last study?', course: 'What course did you study?', showYear: false });
  }
});


test('custom institution, course and extended year survive a failed save and retry', async () => {
  render(<ProfileProvider><ProfileForm /></ProfileProvider>);
  fireEvent.click(await screen.findByText('Test sign in'));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Save background' })).toBeEnabled());
  fireEvent.click(screen.getByRole('radio', { name: 'Student' }));
  fireEvent.click(screen.getByText('University', { exact: true }));
  fireEvent.click(screen.getByRole('checkbox', { name: 'My institution is not listed' }));
  fireEvent.change(screen.getByRole('textbox', { name: 'Institution name' }), { target: { value: 'Unlisted International College' } });
  fireEvent.change(screen.getByRole('textbox', { name: 'What course are you studying?' }), { target: { value: 'Computing & Design' } });
  fireEvent.change(screen.getByRole('spinbutton', { name: /Current study level/ }), { target: { value: '6' } });
  fail = true;
  fireEvent.click(screen.getByRole('button', { name: 'Save background' }));
  await screen.findByText('Storage unavailable. Retry.');
  expect(screen.getByRole('textbox', { name: 'Institution name' })).toHaveValue('Unlisted International College');
  expect(screen.getByRole('spinbutton', { name: /Current study level/ })).toHaveValue(6);
  fail = false;
  fireEvent.click(screen.getByRole('button', { name: 'Save background' }));
  await screen.findByText('Profile saved.');
  expect(saved.education).toMatchObject({ institution: { kind: 'custom', name: 'Unlisted International College' }, course: 'Computing & Design', study_year: 6 });
  fireEvent.click(screen.getByRole('radio', { name: 'Unemployed' }));
  expect(screen.getByRole('textbox', { name: 'What course did you study?' })).toHaveValue('Computing & Design');
  expect(screen.queryByRole('spinbutton', { name: /Current study level/ })).not.toBeInTheDocument();
  expect(screen.getByText(/Previous study year retained: 6/)).toBeInTheDocument();
});


test('local server mode loads and saves without Google or a bearer token', async () => {
  mode = 'local_test';
  render(<ProfileProvider><ProfileForm /></ProfileProvider>);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Save background' })).toBeEnabled());
  expect(screen.queryByText('Test sign in')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('radio', { name: 'Employed' }));
  fireEvent.click(screen.getByRole('button', { name: 'Save background' }));
  await screen.findByText('Profile saved.');
  expect(saved.occupational_status).toBe('employed');
  const writes = vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === 'PATCH');
  expect(writes).toHaveLength(1);
  expect(writes[0][1]?.headers).not.toHaveProperty('Authorization');
});

test('configuration failure does not unlock saving or fall back to local mode', async () => {
  configFails = true;
  render(<ProfileProvider><ProfileForm /></ProfileProvider>);
  await screen.findByText('We could not connect to your profile. Please retry.');
  expect(screen.getByRole('button', { name: 'Save background' })).toBeDisabled();
  expect(vi.mocked(fetch).mock.calls.some(([url, init]) => String(url).endsWith('/profile') && !init?.method)).toBe(false);
});

test('Google server mode still requires sign-in before loading a private profile', async () => {
  render(<ProfileProvider><ProfileForm /></ProfileProvider>);
  await screen.findByText('Test sign in');
  expect(screen.getByRole('button', { name: 'Save background' })).toBeDisabled();
  expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).endsWith('/profile'))).toBe(false);
});
