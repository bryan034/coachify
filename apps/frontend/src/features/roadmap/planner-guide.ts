import type { PlannerConfig, Runway } from './types';

export type GuideStep = { section: string; field: string; question: string; hint: string; starters: string[]; optional?: boolean };

const timeline = 'Timeline';
const studyTime = 'Study time';
const blackouts = 'Blackout days and times';
const targetField = 'Target date or Duration';

/** The planner details the helper asks for, in order. Issue codes come from the backend's runway. */
export const requiredDetails: (GuideStep & { code: string; label: string })[] = [
 { code: 'missing_target', label: 'target date or duration', section: timeline, field: targetField, question: 'When would you like to be ready?', hint: 'Give me a date or a length of time, and I’ll fill in your timeline.', starters: ['I want to be ready in 8 weeks.', 'Help me choose a realistic target date.'] },
 { code: 'no_budget', label: 'weekly study budget', section: studyTime, field: 'Weekly budget in hours', question: 'How many hours can you study each week?', hint: 'A rough number is fine. You can change it in the planner at any time.', starters: ['About five hours a week.', 'Help me find a realistic weekly pace.'] },
 { code: 'no_blocks', label: 'recurring study blocks', section: studyTime, field: 'Recurring study blocks', question: 'Which days and times do you usually study?', hint: 'I’ll turn your answer into recurring study blocks.', starters: ['I can study on weekday evenings and Saturday mornings.'] },
];

/** Details the user entered that the backend can't plan with. They use the backend's own message as the question. */
const corrections: Record<string, Pick<GuideStep, 'section' | 'field'>> = {
 target_before_start: { section: timeline, field: 'Start date and Target date' },
 target_elapsed: { section: timeline, field: targetField },
 runway_too_long: { section: timeline, field: targetField },
 start_in_past: { section: timeline, field: 'Start date' },
 blackout_invalid: { section: blackouts, field: 'Blackout rules' },
 no_usable_time: { section: studyTime, field: 'Recurring study blocks' },
};

/** The one thing to fill in next: what blocks generation first, then optional sections still empty. Null when all are done. */
export function nextGuideStep(runway: Runway | null, config: PlannerConfig | null): GuideStep | null {
 const issue = runway?.issues.find(item => item.code in corrections || requiredDetails.some(detail => detail.code === item.code));
 if (issue) return requiredDetails.find(detail => detail.code === issue.code) || { ...corrections[issue.code], question: issue.message, hint: 'Change it in the planner, or tell me what you’d like instead.', starters: [] };
 if (!config) return null;
 if (!config.blackouts.length) return { section: blackouts, field: 'Blackout rules', optional: true, question: 'Are there days or times you can’t study?', hint: 'Skip this if nothing comes to mind, or press Generate roadmap in the planner.', starters: ['I can’t study on Sundays.', 'I’m away next weekend.'] };
 if (!config.learning_focus.length && !config.learning_notes.trim()) return { section: 'Learning focus', field: 'Focus and notes', optional: true, question: 'What would you like to focus on?', hint: 'Skip this if you have no preference, or press Generate roadmap in the planner.', starters: ['Hands-on projects and interview practice.'] };
 return null;
}
