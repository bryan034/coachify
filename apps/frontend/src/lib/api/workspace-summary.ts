"use client";
import { useCallback, useEffect, useState } from 'react';
import { profileSkillGroups, profileSkillList } from '@/features/cv-ingestion/skill-cards';
import { deviceTimeZone } from '@/features/profile/planning-preferences';
import type { LearningPlan, Workspace } from '@/features/roadmap/types';
import { groupSkills } from '@/lib/skill-groups';
import { careerApi, type CurrentGoal } from './career';
import { cvApi } from './cv';
import { listApplications } from './jobs';
import { roadmapApi } from './roadmap';
import { errorText } from '@/lib/errors';

/** Read-only views of other services for pages that summarise them. Each loads and fails on its own. */
export type Section<T> = { status: 'loading' } | { status: 'ready'; data: T } | { status: 'error'; message: string };

export function useSection<T>(load: (token: string, signal: AbortSignal) => Promise<T>, token: string | undefined) {
 const [state, setState] = useState<Section<T>>({ status: 'loading' });
 const [attempt, setAttempt] = useState(0);
 useEffect(() => {
  if (!token) return;
  const controller = new AbortController();
  setState({ status: 'loading' });
  load(token, controller.signal).then(data => {
   if (!controller.signal.aborted) setState({ status: 'ready', data });
  }).catch((cause: unknown) => {
   if (!controller.signal.aborted) setState({ status: 'error', message: errorText(cause, 'This could not be loaded. Retry shortly.') });
  });
  return () => controller.abort();
 }, [load, token, attempt]);
 const retry = useCallback(() => setAttempt(value => value + 1), []);
 return { state, retry };
}

export const loadGoal = (token: string, signal: AbortSignal) => careerApi<CurrentGoal>('/goals/current', token, { signal });

/**
 * The Skills Profile's own numbers. Every page that mentions the user's skills reads these,
 * so Home, Roadmap and Search Jobs never count differently from Skills Profile.
 */
export type SkillsSummary = { reviewNeeded?: boolean; total: number; experiences: number; groups: { name: string; count: number; skills: string[] }[] };
export async function loadSkills(token: string, signal: AbortSignal): Promise<SkillsSummary> {
 const [profile, declarations, list] = await Promise.all([cvApi.skillsProfile(token, signal), cvApi.declarations(token, signal), cvApi.list(token, signal)]);
 const cv = list.selection.cv_id ? await cvApi.get(list.selection.cv_id, token, signal) : null;
 const skills = profileSkillList(cv, profile, declarations);
 const groups = groupSkills(skills, skill => skill.name, profileSkillGroups(cv, profile, declarations));
 // Same rule as the Skills Profile page: CV items that are not skills, plus profile entries.
 const experiences = (cv ? cv.items.filter(item => !item.removed && item.kind !== 'skill').length : 0) + profile.entries.length;
 return { reviewNeeded: Boolean(cv && cv.profile_reviewed_effective_version !== cv.effective_version), total: skills.length, experiences, groups: groups.map(group => ({ name: group.name, count: group.items.length, skills: group.items.map(skill => skill.name) })) };
}

export async function loadRoadmap(token: string, signal: AbortSignal) {
 const zone = (() => { try { return `?time_zone=${encodeURIComponent(deviceTimeZone())}`; } catch { return ''; } })();
 const workspace = await roadmapApi<Workspace>(`/workspace${zone}`, token, undefined, signal);
 if (!workspace.planner) throw new Error('Your roadmap could not be read. Retry shortly.');
 return workspace;
}

export async function loadLearning(token: string, signal: AbortSignal) {
 const plan = await roadmapApi<LearningPlan>('/learning', token, undefined, signal);
 if (typeof plan?.has_roadmap !== 'boolean' || !Array.isArray(plan.steps)) throw new Error('Your learning steps could not be read. Retry shortly.');
 return plan;
}

export const loadApplications = (token: string, signal: AbortSignal) => listApplications(token, signal);
