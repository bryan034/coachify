const slug = (name: string) => name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
export const categoryAnchor = (prefix: string, name: string) => `${prefix}-${slug(name)}`;

/** Jump links to each skill category, with how many skills it holds. */
export function SkillCategoryNav({ groups, prefix, label }: { groups: { name: string; items: unknown[] }[]; prefix: string; label: string }) {
 if (groups.length < 2) return null;
 return <nav className="skill-category-nav" aria-label={label}>{groups.map(group => <a key={group.name} href={`#${categoryAnchor(prefix, group.name)}`}>{group.name}<span>{group.items.length}</span></a>)}</nav>;
}
