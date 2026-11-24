export const OTHER_SKILLS = 'Other skills';
export type SkillGroupMap = Record<string, string>;

export function groupSkills<T>(items: T[], nameOf: (item: T) => string, groups: SkillGroupMap = {}) {
 const grouped = new Map<string, T[]>();
 for (const item of items) {
  const group = groups[nameOf(item)] ?? OTHER_SKILLS;
  grouped.set(group, [...(grouped.get(group) ?? []), item]);
 }
 return [...grouped.entries()].map(([name, members]) => ({name, items: members}))
  .sort((a, b) => Number(a.name === OTHER_SKILLS) - Number(b.name === OTHER_SKILLS) || b.items.length - a.items.length || a.name.localeCompare(b.name));
}
