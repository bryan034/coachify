export type PremiumFeature = 'career' | 'cv' | 'roadmap';
export const PREMIUM_REQUIRED_EVENT = 'elo:premium-required';
export const PREMIUM_REQUIRED = 'premium_required';

export function openPremium(feature: PremiumFeature) {
 window.dispatchEvent(new CustomEvent(PREMIUM_REQUIRED_EVENT, { detail: { feature } }));
}

export function isPremiumRequired(cause: unknown): boolean {
 return !!cause && typeof cause === 'object' && 'status' in cause && cause.status === 402 && 'code' in cause && cause.code === PREMIUM_REQUIRED;
}
