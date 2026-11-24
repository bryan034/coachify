"use client";
import { useCallback, useEffect, useState } from 'react';
import { skillCardGroups, skillCards } from '@/features/cv-ingestion/skill-cards';
import { deviceTimeZone } from '@/features/profile/planning-preferences';
import type { Workspace } from '@/features/roadmap/types';
import { groupSkills } from '@/lib/skill-groups';
import { careerApi, type CurrentGoal } from './career';
import { skillRatings, ratingKey } from './assessment';
import { cvApi } from './cv';
import { listApplications } from './jobs';
import { roadmapApi } from './roadmap';
import { errorText } from '@/lib/errors';

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

export type ProfileLevel = { name: string; canonicalId?: string | null; level: number };
export type SkillsSummary = { reviewNeeded?: boolean; total: number; experiences: number; levels?: ProfileLevel[]; skills?: { name: string; canonicalId?: string | null; level: number | null }[]; groups: { name: string; count: number; skills: string[] }[] };
export async function loadSkills(token: string, signal: AbortSignal): Promise<SkillsSummary> {
 const [profile, merged, ratings] = await Promise.all([cvApi.skillsProfile(token, signal), cvApi.skills(token, signal),
  skillRatings(token, signal).catch(() => null)]);
 const cv = merged.cv_id ? await cvApi.get(merged.cv_id, token, signal) : null;
 const skills = skillCards(merged);
 const groups = groupSkills(skills, skill => skill.name, skillCardGroups(merged));
 const experiences = (cv ? cv.items.filter(item => !item.removed && item.kind !== 'skill').length : 0) + profile.entries.length;
 const own = new Map((ratings?.ratings ?? []).map(rating => [rating.key, rating.score]));
 const all = skills.map(skill => ({ name: skill.name, canonicalId: skill.canonicalId, level: skill.ownLevel?.level ?? own.get(ratingKey(skill)) ?? null }));
 const levels = all.flatMap((skill): ProfileLevel[] => skill.level == null ? [] : [{ ...skill, level: skill.level }]);
 return { levels, skills: all, reviewNeeded: Boolean(cv && cv.profile_reviewed_effective_version !== cv.effective_version), total: skills.length, experiences, groups: groups.map(group => ({ name: group.name, count: group.items.length, skills: group.items.map(skill => skill.name) })) };
}

export async function loadRoadmap(token: string, signal: AbortSignal) {
 const zone = (() => { try { return `?time_zone=${encodeURIComponent(deviceTimeZone())}`; } catch { return ''; } })();
 const workspace = await roadmapApi<Workspace>(`/workspace${zone}`, token, undefined, signal);
 if (!workspace.planner) throw new Error('Your roadmap could not be read. Retry shortly.');
 return workspace;
}

export const loadApplications = (token: string, signal: AbortSignal) => listApplications(token, signal);
