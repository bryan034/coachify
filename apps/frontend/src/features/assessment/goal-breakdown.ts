import type { LearningItem, ReviewSkill } from '@/lib/api/career';
import type { Requirement } from '@/features/roadmap/types';
import { namesSkill } from './levels';

/** One of the person's Skills Profile entries, with its level when one is known. */
export type ProfileSkillRef = { name: string; canonicalId?: string | null; level?: number | null };

/** The smaller skills a goal skill breaks down into, from the goal's own learning items. Items that repeat a goal skill are left out. */
export function skillParts(skill: ReviewSkill, goalSkills: ReviewSkill[]): LearningItem[] {
 return (skill.learning_items ?? []).filter((item, index, list) => !namesSkill(goalSkills, { name: item.name })
  && list.findIndex(other => namesSkill([other], { name: item.name })) === index);
}

/**
 * The person's skills that count towards one goal skill: the same skill (by registry id or name), one of its smaller parts,
 * or a skill the saved evaluation linked to it. Both the Career Goal and the Skills Profile use this, so they agree.
 */
export function linkedProfileSkills(skill: ReviewSkill, outcome: Requirement | undefined, profile: ProfileSkillRef[]): ProfileSkillRef[] {
 const linked = outcome?.profile_skills ?? [], parts = skill.learning_items ?? [];
 return profile.filter(item => namesSkill([skill], item) || namesSkill(linked, item) || namesSkill(parts, { name: item.name }));
}
