import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import { ProfileForm } from './profile-form';
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
beforeEach(() => {
  saved = initial; fail = false;
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit) => {
    if (url.includes('school-categories')) return new Response(JSON.stringify(categories));
    if (init?.method === 'PATCH') {
      if (fail) return new Response(JSON.stringify({ detail: 'Storage unavailable. Retry.' }), { status: 503 });
      saved = { ...saved, ...JSON.parse(init.body as string), version: 1 };
    }
    return new Response(JSON.stringify(saved));
  }));
});

test('no default status, exact options, student category validation and save retry', async () => {
  render(<ProfileForm />);
  expect(screen.getAllByRole('radio')).toHaveLength(4);
  expect(screen.getAllByRole('radio').every(r => !(r as HTMLInputElement).checked)).toBe(true);
  fireEvent.click(screen.getByText('Test sign in'));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Save background' })).toBeEnabled());
  fireEvent.click(screen.getByRole('radio', { name: 'Student' }));
  expect(screen.getByText('Where are you studying?')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Save background' }));
  expect(screen.getByRole('alert')).toHaveTextContent('Choose a school category');
  fireEvent.click(screen.getByRole('radio', { name: 'Use this category: University', hidden: true }));
  fail = true;
  fireEvent.click(screen.getByRole('button', { name: 'Save background' }));
  await screen.findByText('Storage unavailable. Retry.');
  expect(screen.getByRole('radio', { name: 'Use this category: University', hidden: true })).toBeChecked();
  expect(screen.queryByText('Profile saved.')).not.toBeInTheDocument();
  fail = false;
  fireEvent.click(screen.getByRole('button', { name: 'Save background' }));
  expect(await screen.findByText('Profile saved.')).toBeInTheDocument();
});

test('nonstudent can leave school unanswered; status changes prompt review', async () => {
  saved = { ...initial, version: 1, occupational_status: 'student', school_category: 'university' };
  render(<ProfileForm />);
  fireEvent.click(screen.getByText('Test sign in'));
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
