export const skillNameKey = (name: string) => name.normalize('NFKC').trim().replace(/\s+/g, ' ').toLowerCase();

export const sameSkillName = (a: string, b: string) => skillNameKey(a) === skillNameKey(b);
