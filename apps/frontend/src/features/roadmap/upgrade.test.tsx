import { act, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ProfileProvider } from '@/features/profile/profile-provider';
import { PremiumDialog } from '@/components/ui/premium-dialog';
import { openPremium } from '@/lib/api/premium';
import { RoadmapPlanner } from './roadmap-planner';
import type { Outline } from './types';
import { planner, review, roadmap, workspace } from '../../../tests/fixtures/roadmap-workspace';
const api = vi.hoisted(() => vi.fn());
vi.mock('@/lib/api/roadmap', () => ({roadmapApi:api, RoadmapError:class extends Error {status=409;}}));
vi.mock('@/lib/api/assessment', async original => ({...await original<typeof import('@/lib/api/assessment')>(),assessmentApi:vi.fn(async path => path === '/context' ? {ready:true,model_available:true} : {version:0,stale:false,ready:true,result:null,operation:null,evaluation:{freshness:'current',processing:'idle',reasons:[]}})}));
vi.mock('@/lib/api/workspace-summary', async original => ({...await original<typeof import('@/lib/api/workspace-summary')>(),loadSkills:vi.fn(async () => ({total:0,experiences:0,groups:[]}))}));
let plan: 'free' | 'premium' = 'free'; let sessions = 0;
function outline(): Outline {const p=roadmap();const week=(week_start:string,objective:string)=>({week_start,start_date:week_start,end_date:week_start,objective,expected_outcome:'Done',estimated_minutes:60,milestone_key:'m1',gap_ids:['python']});
 return {id:'outline',revision:1,summary:p.summary,gaps:p.gaps,milestones:p.milestones,routine_rules:[],deadline_outcome:p.deadline_outcome,beyond_deadline:[],exclusions:[],config:p.config,weeks:[week('2030-01-07','Build an endpoint'),week('2030-01-14','Test edge cases'),week('2030-01-21','Ship the service')]};}
beforeEach(() => {
 plan = 'free'; sessions = 0; sessionStorage.clear(); localStorage.clear();
 localStorage.setItem('elo.access-epoch', '1'); sessionStorage.setItem('elo.session', JSON.stringify({ marker: 'synthetic-marker', epoch: '1' }));
 Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true });
 vi.stubGlobal('fetch', vi.fn(async (url: string) => {
  if (url.endsWith('/auth/session')) sessions++;
  const value = url.endsWith('/auth-config') ? { mode: 'local_test' } : url.endsWith('/school-categories') ? []
   : url.endsWith('/auth/session') ? { id: 'owner', name: 'Synthetic', provider: 'local_test', email_verified: true, account_type: plan }
   : { version: 1, onboarding_complete: true, education: { course: 'Synthetic course' } };
  return new Response(JSON.stringify(value));
 }));
 const p = roadmap(); const state = workspace({ planner: planner({ active: p, active_review: review(p), outline_active: outline(), week_planning: { action: 'plan_next', week_start: '2030-01-21', available: true, plan_day: '2030-01-20', week_done: false, unfinished_count: 0 } }) });
 api.mockReset(); api.mockImplementation(async (path: string) => path === '/planner/runway' ? state.planner.runway : state);
 window.history.replaceState({}, '', '/roadmap');
});
afterEach(() => { vi.unstubAllGlobals(); });
it('unlocks a later week when session re-validation shows the account upgraded', async () => {
 render(<ProfileProvider><RoadmapPlanner/></ProfileProvider>);
 expect(await screen.findByRole('group', { name: /Task breakdown for the week of/ })).toHaveTextContent('Week goal: Ship the service');
 plan = 'premium';
 act(() => { document.dispatchEvent(new Event('visibilitychange')); });
 expect(await screen.findByRole('button', { name: 'Plan next week' })).toBeEnabled();
 expect(screen.queryByRole('group', { name: /Task breakdown for the week of/ })).toBeNull();
});
it('re-checks the session when a premium limit is reached and closes the dialog after an upgrade', async () => {
 render(<ProfileProvider><RoadmapPlanner/><PremiumDialog/></ProfileProvider>);
 await screen.findByRole('group', { name: /Task breakdown for the week of/ });
 const before = sessions; plan = 'premium';
 act(() => openPremium('roadmap'));
 expect(screen.getByRole('dialog', { name: 'Task breakdowns after your first two weeks' })).toBeVisible();
 await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
 expect(sessions).toBe(before + 1);
 expect(screen.getByRole('button', { name: 'Plan next week' })).toBeEnabled();
});
it('keeps the dialog open when the re-check still shows a free account', async () => {
 render(<ProfileProvider><RoadmapPlanner/><PremiumDialog/></ProfileProvider>);
 await screen.findByRole('group', { name: /Task breakdown for the week of/ });
 const before = sessions;
 act(() => openPremium('roadmap'));
 await waitFor(() => expect(sessions).toBe(before + 1));
 expect(screen.getByRole('dialog', { name: 'Task breakdowns after your first two weeks' })).toBeVisible();
});
