import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import { ProfileDashboard } from './profile-dashboard';
import type { Profile } from './types';
let profile: Profile; let developmentToolsEnabled = false; let fail = false;
vi.mock('./profile-provider', () => ({ useProfile: () => ({ profile, developmentToolsEnabled, mode: 'email', token: 'synthetic-session', categories: [{id:'university',label:'University'}], loading: false, configError: '', loadError: '', setProfile: (next: Profile) => { profile=next; return true; }, account: { name: 'Synthetic user', email: 'synthetic@example.test' } }) }));
beforeEach(() => {
  developmentToolsEnabled = false; fail = false;
  vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
    if (fail) return Response.json({ detail: 'Synthetic storage outage' }, { status: 503 });
    const fields = JSON.parse(String(init?.body));
    return Response.json({ ...profile, ...fields, version: profile.version + 1, education: { ...profile.education, ...fields.education } });
  }));
  profile = { version: 1, occupational_status: 'student', school_category: 'university', education_context: 'current', education_review_required: false,
    education: { institution: { kind: 'custom', id: null, name: 'Synthetic school', country_code: 'SG' }, course: 'Synthetic course', study_year: 3 }, current_study_year: 3 };
});
test('summary shows saved education and active student year without the edit form', () => {
  render(<ProfileDashboard />);
  expect(screen.getByText('Synthetic school')).toBeInTheDocument(); expect(screen.getByText('Synthetic course')).toBeInTheDocument();
  expect(screen.getByText('Year 3')).toBeInTheDocument(); expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Edit profile/ })).toBeEnabled();
  expect(screen.queryByRole('link', { name: /Preview onboarding/ })).not.toBeInTheDocument();
});
test('employed users see last education, employer and role but no retained study year', () => {
  profile.occupational_status = 'employed'; profile.employment = { employer: 'Synthetic company', role: 'Synthetic analyst' };
  render(<ProfileDashboard />);
  expect(screen.getByText('Place of last education')).toBeInTheDocument();
  expect(screen.getByText('Synthetic company')).toBeInTheDocument(); expect(screen.getByText('Synthetic analyst')).toBeInTheDocument();
  expect(screen.queryByText('Year of study')).not.toBeInTheDocument(); expect(screen.queryByText('Year 3')).not.toBeInTheDocument();
});
test('non-students do not display historical employment, and no-education choice hides preserved education', () => {
  profile.occupational_status = 'unemployed'; profile.no_previous_education = true; profile.school_category = null;
  profile.employment = { employer: 'Historical company', role: 'Historical role' };
  render(<ProfileDashboard />);
  expect(screen.getByText('No previous education')).toBeInTheDocument();
  expect(screen.queryByText('Historical company')).not.toBeInTheDocument(); expect(screen.queryByText('Synthetic school')).not.toBeInTheDocument();
});
test('development offers a non-destructive onboarding preview', () => {
  developmentToolsEnabled = true; render(<ProfileDashboard />);
  expect(screen.getByRole('link', { name: /Preview onboarding/ })).toHaveAttribute('href', '/onboarding/preview');
});

test('edit opens on the same page and cancel discards unsaved changes', async () => {
  render(<ProfileDashboard />);
  fireEvent.click(screen.getByRole('button', { name: /Edit profile/ }));
  const course = await screen.findByRole('textbox', { name: 'What course are you studying?' });
  fireEvent.change(course, { target: { value: 'Unsaved course' } });
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(screen.getByText('Synthetic course')).toBeInTheDocument(); expect(fetch).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: /Edit profile/ }));
  expect(await screen.findByRole('textbox', { name: 'What course are you studying?' })).toHaveValue('Synthetic course');
});

test('failed inline save retains edits; retry saves and refreshes the summary', async () => {
  render(<ProfileDashboard />);
  fireEvent.click(screen.getByRole('button', { name: /Edit profile/ }));
  const course = await screen.findByRole('textbox', { name: 'What course are you studying?' });
  fireEvent.change(course, { target: { value: 'Updated course' } });
  fail = true; fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Synthetic storage outage');
  expect(course).toHaveValue('Updated course'); expect(profile.education.course).toBe('Synthetic course');
  fail = false; fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Profile updated.'));
  expect(screen.getByText('Updated course')).toBeInTheDocument(); expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  expect(profile.education.course).toBe('Updated course');
});

test('confirmed previous work shows company, role and industry as previous employment', () => {
  profile.occupational_status = 'unemployed'; profile.previously_employed = true;
  profile.employment = { employer: 'Synthetic previous company', role: 'Synthetic previous role', industry: 'Synthetic industry' };
  render(<ProfileDashboard />);
  expect(screen.getByRole('heading', { name: 'Previous employment' })).toBeInTheDocument();
  expect(screen.getByText('Synthetic previous company')).toBeInTheDocument();
  expect(screen.getByText('Synthetic previous role')).toBeInTheDocument();
  expect(screen.getByText('Synthetic industry')).toBeInTheDocument();
  expect(screen.queryByText('Current employment')).not.toBeInTheDocument();
});

test('never-employed profile displays graduation and allows editing it', async () => {
  profile.occupational_status = 'unemployed'; profile.previously_employed = false;
  profile.education.graduation_year = 2024;
  render(<ProfileDashboard />);
  expect(screen.getByText('Year of graduation')).toBeInTheDocument();
  expect(screen.getByText('2024')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /Edit profile/ }));
  fireEvent.change(await screen.findByRole('spinbutton', { name: 'Year of graduation' }), { target: { value: '2023' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
  expect(await screen.findByText('2023')).toBeInTheDocument();
  expect(profile.education.graduation_year).toBe(2023);
});
