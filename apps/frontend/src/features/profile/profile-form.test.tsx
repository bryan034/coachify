import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import { ProfileForm } from './profile-form';
import { ProfileProvider } from './profile-provider';
import { educationQuestions } from './types';
vi.mock('next/navigation', () => ({useRouter:()=>({replace:vi.fn()})}));
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
    if (url.endsWith('/auth/session')) return new Response(JSON.stringify({id:'synthetic',name:'Synthetic',provider:mode,onboarding_complete:false}));
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
  expect(screen.getByRole('combobox', {name:'Occupational status'})).toHaveValue('');
  expect(screen.getAllByRole('option').map(option => option.textContent)).toEqual(['Choose your status','Student','National Service','Unemployed','Employed']);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Save background' })).toBeEnabled());
  fireEvent.change(screen.getByRole('combobox', { name: 'Occupational status' }), { target: { value: 'student' } });
  expect(screen.getByText('Current education')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Save background' }));
  expect(screen.getByRole('alert')).toHaveTextContent('Choose a school category');
  fireEvent.change(screen.getByRole('combobox', {name:'Education path'}), {target:{value:'university'}});
  fail = true;
  fireEvent.click(screen.getByRole('button', { name: 'Save background' }));
  await screen.findByText('Storage unavailable. Retry.');
  expect(screen.getByRole('combobox', {name:'Education path'})).toBeInTheDocument();
  expect(screen.queryByText('Profile saved.')).not.toBeInTheDocument();
  fail = false;
  fireEvent.click(screen.getByRole('button', { name: 'Save background' }));
  expect(await screen.findByText('Profile saved.')).toBeInTheDocument();
});

test('nonstudent can leave school unanswered; status changes prompt review', async () => {
  saved = { ...initial, version: 1, occupational_status: 'student', school_category: 'university' };
  render(<ProfileProvider><ProfileForm /></ProfileProvider>);
  await waitFor(() => expect(screen.getByRole('combobox', { name: 'Occupational status' })).toHaveValue('student'));
  fireEvent.change(screen.getByRole('combobox', { name: 'Occupational status' }), { target: { value: 'employed' } });
  expect(screen.getByText('Last education')).toBeInTheDocument();
  expect(screen.getByText(/Please review your education details/)).toBeInTheDocument();
  fireEvent.change(screen.getByRole('combobox', { name: 'Education path' }), { target: { value: 'none' } });
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
  await waitFor(() => expect(screen.getByRole('button', { name: 'Save background' })).toBeEnabled());
  fireEvent.change(screen.getByRole('combobox', { name: 'Occupational status' }), { target: { value: 'student' } });
  fireEvent.change(await screen.findByRole('combobox', {name:'Education path'}), {target:{value:'university'}});
  fireEvent.click(screen.getByRole('button', { name: 'My institution is not listed' }));
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
  fireEvent.change(screen.getByRole('combobox', { name: 'Occupational status' }), { target: { value: 'unemployed' } });
  expect(screen.getByRole('textbox', { name: 'What course did you study?' })).toHaveValue('Computing & Design');
  expect(screen.queryByRole('spinbutton', { name: /Current study level/ })).not.toBeInTheDocument();
  expect(screen.queryByText(/Previous study year retained:/)).not.toBeInTheDocument();
});


test('local account session loads and saves without Google', async () => {
  mode = 'local_test';
  render(<ProfileProvider><ProfileForm /></ProfileProvider>);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Save background' })).toBeEnabled());
  expect(screen.queryByText('Test sign in')).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole('combobox', { name: 'Occupational status' }), { target: { value: 'employed' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save background' }));
  await screen.findByText('Profile saved.');
  expect(saved.occupational_status).toBe('employed');
  const writes = vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === 'PATCH');
  expect(writes).toHaveLength(1);
  expect(writes[0][1]?.headers).toHaveProperty('Authorization', 'Bearer synthetic-session-token');
});

test('configuration failure does not unlock saving or fall back to local mode', async () => {
  configFails = true;
  render(<ProfileProvider><ProfileForm /></ProfileProvider>);
  await screen.findByText('Unavailable');
  expect(screen.getByRole('button', { name: 'Save background' })).toBeDisabled();
  expect(vi.mocked(fetch).mock.calls.some(([url, init]) => String(url).endsWith('/profile') && !init?.method)).toBe(false);
});

test('Google server mode still requires sign-in before loading a private profile', async () => {
  sessionStorage.clear();
  render(<ProfileProvider><ProfileForm /></ProfileProvider>);
  await waitFor(() => expect(screen.getByRole('button', {name:'Save background'})).toBeDisabled());
  expect(screen.getByRole('button', { name: 'Save background' })).toBeDisabled();
  expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).endsWith('/profile'))).toBe(false);
});


test('initial pageshow cannot restart profile loading or erase an unsaved status choice', async () => {
  render(<ProfileProvider><ProfileForm /></ProfileProvider>);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Save background' })).toBeEnabled());
  fireEvent.change(screen.getByRole('combobox', { name: 'Occupational status' }), { target: { value: 'student' } });
  expect(await screen.findByText('Current education')).toBeInTheDocument();
  const calls = vi.mocked(fetch).mock.calls.length;
  await act(async () => { window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: false })); });
  expect(screen.getByRole('combobox', { name: 'Occupational status' })).toHaveValue('student');
  expect(screen.getByText('Current education')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Save background' })).toBeEnabled();
  expect(vi.mocked(fetch).mock.calls).toHaveLength(calls);
});

test('saved school stays compact until Change school is chosen and a blank optional course clears it', async () => {
  saved = { ...initial, version: 2, occupational_status: 'student', school_category: 'university', education: { institution: {kind:'catalogue',id:'synthetic-school',name:'Synthetic school'}, course: 'Old course', study_year:3,study_year_category:'university' } };
  render(<ProfileProvider><ProfileForm /></ProfileProvider>);
  await screen.findByText('Synthetic school', {exact:true});
  expect(screen.queryByText('Directory browser')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', {name:'Change school'}));
  expect(screen.getByText('Directory browser')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', {name:'Close school search'}));
  expect(screen.queryByText('Directory browser')).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole('textbox', {name:'What course are you studying?'}), {target:{value:''}});
  fireEvent.click(screen.getByRole('button', {name:'Save background'}));
  await screen.findByText('Profile saved.');
  expect(saved.education).toMatchObject({institution:{name:'Synthetic school'},course:null});
});
