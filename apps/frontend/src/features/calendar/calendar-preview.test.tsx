import React from 'react';
import { render, screen, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { CalendarPreview } from './calendar-preview';
import { ProfileProvider } from '@/features/profile/profile-provider';

const today = new Date();
const iso = (date: Date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
const target = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 30);
const blackout = { frequency: 'daily', start_date: iso(today), end_date: iso(today), interval: 1, weekdays: [], start_time: null, end_time: null };

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const data = (url: string): any => {
 if (url.endsWith('/auth/session')) return { id: 'synthetic', name: 'Synthetic Person', provider: 'local_test', onboarding_complete: true };
 if (url.endsWith('/auth-config')) return { mode: 'local_test' };
 if (url.endsWith('/school-categories')) return [];
 if (url.endsWith('/career/goals/current')) return { goal: null };
 if (url.endsWith('/jobs/applications')) return { items: [] };
 if (url.includes('/roadmaps/workspace')) return { version: 0, messages: [], operation: null, active: null, draft: null, assessment: null, stale: false, context: { ready: true, issues: [], model_available: true }, planner: { config: { blackouts: [blackout] }, runway: { windows: [], can_generate: true, issues: [], resolved: { today: iso(today), start_date: iso(today), target_date: iso(target) } } } };
 return { version: 1, occupational_status: 'student', school_category: 'university', current_study_year: 3, education_review_required: false, education: { course: 'Synthetic Course' } };
};
afterEach(() => vi.unstubAllGlobals());

test('Calendar explains its colours, shows the target date and hatches a blocked-out day', async () => {
 vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(JSON.stringify(data(url)))));
 const { container } = render(<ProfileProvider><CalendarPreview /></ProfileProvider>);
 expect(await screen.findByText('Study sessions from your roadmap, saved-job deadlines and interviews.')).toBeVisible();
 const key = screen.getByRole('region', { name: 'Key' });
 for (const name of ['Study session', 'Session in a backup block', 'Interview', 'Application deadline', 'Blocked out']) expect(within(key).getByText(name)).toBeVisible();
 expect(within(key).getByRole('link', { name: 'Change study times in Roadmap' })).toHaveAttribute('href', '/roadmap');
 expect(await screen.findByText('30 days away')).toBeVisible();
 expect(container.querySelectorAll('.cal-column.is-blocked')).toHaveLength(1);
});
