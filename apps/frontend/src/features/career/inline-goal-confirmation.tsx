"use client";
import { useCallback, useRef } from 'react';
import { loadGoal, useSection } from '@/lib/api/workspace-summary';
import { CvGoalConfirmationCard } from './cv-goal-confirmation';
export function InlineGoalConfirmation({ token, onConfirmed }: { token: string; onConfirmed?: () => void }) {
 const callback = useRef(onConfirmed); callback.current = onConfirmed;
 const confirmed = useCallback((value: boolean) => { if (value) callback.current?.(); }, []);
 const goal = useSection(loadGoal, token);
 if (goal.state.status === 'loading') return <p role="status">Checking your career goal…</p>;
 if (goal.state.status === 'error') return <button className="btn ghost" onClick={goal.retry}>Retry goal check</button>;
 const value = goal.state.data;
 if (!value.goal) return <p>Add a Career Goal to focus your CV questions.</p>;
 return <CvGoalConfirmationCard key={`${token}:${value.goal._id}:${value.goal.version}:${value.selection_version}`} goal={value.goal} selectionVersion={value.selection_version} token={token} onReload={goal.retry} onConfirmationChange={confirmed}/>;
}
