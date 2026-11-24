import type { LearningItem, ReviewSkill } from '@/lib/api/career';
import type { Requirement } from '@/features/roadmap/types';
import { namesSkill } from './levels';

export type ProfileSkillRef = { name: string; canonicalId?: string | null; level?: number | null };

export function skillParts(skill: ReviewSkill, goalSkills: ReviewSkill[]): LearningItem[] {
 return (skill.learning_items ?? []).filter((item, index, list) => !namesSkill(goalSkills, { name: item.name })
  && list.findIndex(other => namesSkill([other], { name: item.name })) === index);
}

export function linkedProfileSkills(skill: ReviewSkill, outcome: Requirement | undefined, profile: ProfileSkillRef[]): ProfileSkillRef[] {
 const linked = outcome?.profile_skills ?? [], parts = skill.learning_items ?? [];
 return profile.filter(item => namesSkill([skill], item) || namesSkill(linked, item) || namesSkill(parts, { name: item.name }));
}
