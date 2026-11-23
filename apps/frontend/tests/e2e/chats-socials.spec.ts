import { expect, test, type Page } from '@playwright/test';
import type { ChatBooking, ChatSlot, Expert, SocialsWorkspace } from '../../src/lib/api/socials';
import { workspace } from '../fixtures/roadmap-workspace';

const expert: Expert = { id: 'analyst', name: 'Synthetic Analyst', role: 'Data Analyst', field: 'Data', organisation: 'Synthetic Studio', linkedin_url: null, open_slots: 1 };
const slot: ChatSlot = { id: 'd06ecfbd-0405-4445-b6f9-8c6d0dd7b3d4', version: 1, starts_at: '2030-01-08T11:00:00Z', durations: [30, 60] };
const request: ChatBooking = {
 id: '08f07748-08a4-4e0b-8492-17536d96d9e5', version: 2, expert_id: expert.id, expert_name: expert.name,
 starts_at: slot.starts_at, duration_minutes: 30, status: 'requested', question: 'What do you work on each week?',
 meeting_url: null, credits: 1, prep_done: false, notes: '', member_name: 'Synthetic Member',
};

async function signIn(page: Page) {
 await page.addInitScript(() => {
  localStorage.setItem('elo.access-epoch', '1');
  sessionStorage.setItem('elo.session', JSON.stringify({ marker: 'synthetic-token', epoch: '1' }));
 });
 await page.route('**/api/v1/profile/**', route => {
  const path = new URL(route.request().url()).pathname;
  if (path.endsWith('/auth/session')) return route.fulfill({ json: { id: 'synthetic', name: 'Synthetic Member', provider: 'local_test' } });
  return route.fulfill({ json: { mode: 'local_test' } });
 });
 await page.route('**/api/v1/profile', route => route.fulfill({ json: { version: 1, onboarding_complete: true, education: {} } }));
 await page.route('**/api/v1/jobs/applications', route => route.fulfill({ json: { items: [] } }));
}

test('requests a chat once after a lost response and opens its confirmed follow-up in Roadmap', async ({ page }, testInfo) => {
 await signIn(page);
 let booking: ChatBooking | null = null;
 const mutationIds: string[] = [];
 await page.route('**/api/v1/socials/workspace', route => {
  const state: SocialsWorkspace = {
   access: 'enabled', credits: booking ? 0 : 1, experts: [{ ...expert, open_slots: booking ? 0 : 1 }],
   recommendation: { expert_id: expert.id, role: expert.role }, bookings: booking ? [booking] : [], expert_inbox: false,
  };
  return route.fulfill({ json: state });
 });
 await page.route('**/api/v1/socials/experts/analyst/slots', route => route.fulfill({ json: [slot] }));
 await page.route('**/api/v1/socials/bookings', route => {
  const body = route.request().postDataJSON();
  expect(body).toMatchObject({ expert_id: expert.id, slot_id: slot.id, slot_version: 1, duration_minutes: 30, adult_attested: true, question: request.question });
  mutationIds.push(body.mutation_id);
  if (!booking) { booking = request; return route.abort('failed'); }
  return route.fulfill({ json: booking });
 });
 await page.route('**/api/v1/socials/agenda', route => route.fulfill({ json: booking?.status === 'accepted' ? [booking] : [] }));
 await page.route('**/api/v1/roadmaps/workspace*', route => route.fulfill({ json: workspace({}) }));

 await page.goto('/chats-socials');
 await expect(page.getByRole('heading', { name: 'Recommended for you' })).toBeVisible();
 await page.screenshot({ path: testInfo.outputPath('chats-socials.png'), fullPage: true });
 await page.setViewportSize({ width: 390, height: 844 });
 await page.getByRole('button', { name: 'Request a chat', exact: true }).click();
 const drawer = page.getByRole('dialog', { name: `Request a chat with ${expert.name}` });
 await expect(drawer.getByRole('radio', { name: /1 hour/ })).toBeDisabled();
 await drawer.getByRole('radio', { name: /8 Jan/ }).check();
 await expect(drawer.getByRole('button', { name: 'Send request' })).toBeDisabled();
 await drawer.getByRole('checkbox', { name: /18 or over/ }).check();
 await drawer.getByRole('textbox', { name: /What would you like to ask/ }).fill(request.question);
 await page.screenshot({ path: testInfo.outputPath('request-mobile.png') });
 await drawer.getByRole('button', { name: 'Send request' }).click();
 await expect(drawer.getByRole('alert')).toBeVisible();
 await drawer.getByRole('button', { name: 'Send request' }).click();
 await expect(page.getByText('Waiting for reply', { exact: true })).toBeVisible();
 expect(mutationIds).toHaveLength(2);
 expect(mutationIds[0]).toBe(mutationIds[1]);

 booking = { ...request, version: 3, status: 'accepted', meeting_url: 'https://meet.example.test/synthetic' };
 await page.goto('/roadmap');
 const agenda = page.getByRole('region', { name: 'Expert chats' });
 await expect(agenda.getByText('Prep: write three questions · Notes after the chat')).toBeVisible();
 await agenda.getByRole('link', { name: 'Open chat follow-up' }).click();
 await expect(page.getByText('Confirmed', { exact: true })).toBeVisible();
 await expect(page.getByRole('link', { name: 'Open meeting link' })).toHaveAttribute('href', booking.meeting_url!);
});

test('shows an assigned expert inbox while the member directory is locked', async ({ page }) => {
 await signIn(page);
 let booking: ChatBooking = request;
 await page.route('**/api/v1/socials/workspace', route => route.fulfill({ json: {
  access: 'locked', credits: 0, experts: [], recommendation: null, bookings: [], expert_inbox: true,
 } }));
 await page.route('**/api/v1/socials/expert/requests', route => route.fulfill({ json: [booking] }));
 await page.route('**/api/v1/socials/bookings/*/decision', route => {
  expect(route.request().postDataJSON()).toMatchObject({ decision: 'accept', expected_version: booking.version, meeting_url: 'https://meet.example.test/synthetic' });
  booking = { ...booking, version: 3, status: 'accepted', meeting_url: 'https://meet.example.test/synthetic' };
  return route.fulfill({ json: booking });
 });
 await page.goto('/chats-socials');
 await expect(page.getByRole('heading', { name: 'Expert chats are invite-only' })).toBeVisible();
 await expect(page.getByRole('heading', { name: 'Browse experts' })).toHaveCount(0);
 const inbox = page.getByRole('region', { name: 'Expert inbox' });
 await expect(inbox.getByText(request.question)).toBeVisible();
 await inbox.getByRole('textbox', { name: 'Meeting link' }).fill('https://meet.example.test/synthetic');
 await inbox.getByRole('button', { name: 'Accept' }).click();
 await expect(inbox.getByText('Confirmed', { exact: true })).toBeVisible();
 await expect(inbox.getByRole('link', { name: 'Open meeting link' })).toHaveAttribute('href', 'https://meet.example.test/synthetic');
});
