/** How a level out of 10 stands against the level a goal needs. Both numbers come from the saved evaluation. */
export type LevelStatus = 'ready' | 'getting' | 'build' | 'unrated';
export const LEVEL_LABELS: Record<LevelStatus, string> = { ready: 'Ready', getting: 'Getting there', build: 'To build', unrated: 'Not rated' };
export const LEVEL_COLORS: Record<LevelStatus, string> = { ready: 'var(--mint)', getting: 'var(--ws-amber-bar)', build: 'var(--ws-build)', unrated: 'transparent' };

/** Without a known target the level is read against the full scale. */
export function levelStatus(level: number | null | undefined, target: number | null | undefined): LevelStatus {
 if (level == null) return 'unrated';
 const need = target ?? 10;
 return level >= need ? 'ready' : level >= need * 0.7 ? 'getting' : 'build';
}

/** "4 / 8" against a target, "4 / 10" without one; an unrated skill still shows the goal's target ("Not rated / 8"). */
export const levelText = (level: number | null | undefined, target: number | null | undefined) => level == null ? (target == null ? 'Not rated' : `Not rated / ${target}`) : `${level} / ${target ?? 10}`;

const fold = (value: string) => value.trim().toLowerCase();
/** Whether a roadmap task names this skill, by registry identity or by name. */
export function namesSkill(skills: { name: string; canonical_skill_id?: string | null }[], skill: { name: string; canonicalId?: string | null }) {
 return skills.some(item => (skill.canonicalId && item.canonical_skill_id === skill.canonicalId) || fold(item.name) === fold(skill.name));
}
