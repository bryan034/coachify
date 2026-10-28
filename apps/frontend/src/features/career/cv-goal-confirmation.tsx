"use client";

import Link from 'next/link';
import {useCallback,useEffect,useRef,useState} from 'react';
import {CareerApiError,type SavedGoal} from '@/lib/api/career';
import {confirmCvGoal,getCvGoalConfirmation,type ConfirmCvGoal,type CvGoalConfirmation} from '@/lib/api/career-cv-confirmation';

export function CvGoalConfirmationCard({goal,selectionVersion,token,onReload}:{goal:SavedGoal;selectionVersion:number;token:string|undefined;onReload:()=>void}){
 const [state,setState]=useState<CvGoalConfirmation>(),[error,setError]=useState(''),[loading,setLoading]=useState(true),[saving,setSaving]=useState(false),[stale,setStale]=useState(false);
 const lifetime=useRef(new AbortController()),attempt=useRef<ConfirmCvGoal|null>(null);
 const matches=useCallback((value:CvGoalConfirmation)=>value.goal_id===goal._id&&value.goal_version===goal.version&&value.selection_version===selectionVersion,[goal._id,goal.version,selectionVersion]);
 const load=useCallback(async()=>{
  if(!token)return;setLoading(true);setError('');
  try{const value=await getCvGoalConfirmation(token,lifetime.current.signal);if(lifetime.current.signal.aborted)return;setState(value);setStale(!matches(value));}
  catch(cause){if(!lifetime.current.signal.aborted)setError(cause instanceof Error?cause.message:'Could not check this goal’s confirmation.');}
  finally{if(!lifetime.current.signal.aborted)setLoading(false);}
 },[token,matches]);
 useEffect(()=>{if(lifetime.current.signal.aborted)lifetime.current=new AbortController();void load();return()=>lifetime.current.abort();},[load]);
 useEffect(()=>{function refresh(){if(!saving&&document.visibilityState!=='hidden')void load();}window.addEventListener('focus',refresh);window.addEventListener('online',refresh);return()=>{window.removeEventListener('focus',refresh);window.removeEventListener('online',refresh);};},[load,saving]);
 async function confirm(){
  if(!token||saving||loading||stale||!state||state.reason||state.confirmed)return;
  attempt.current??={expected_goal_id:goal._id,expected_goal_version:goal.version,expected_selection_version:selectionVersion,mutation_id:crypto.randomUUID()};
  setSaving(true);setError('');
  try{const value=await confirmCvGoal(attempt.current,token,lifetime.current.signal);if(lifetime.current.signal.aborted)return;setState(value);setStale(!matches(value));attempt.current=null;}
  catch(cause){if(!lifetime.current.signal.aborted){setError(cause instanceof Error?cause.message:'Could not confirm the goal. Check its saved status before retrying.');if(cause instanceof CareerApiError&&cause.status===409){setStale(true);attempt.current=null;}}}
  finally{if(!lifetime.current.signal.aborted)setSaving(false);}
 }
 const confirmed=Boolean(state?.confirmed&&!stale),blocked=Boolean(!token||loading||saving||stale||!state||state.reason||goal.requirements_need_review);
 return <section className="card pad" aria-label="Goal confirmation for CV review" aria-busy={loading||saving}>
  <h2>{confirmed?'Confirmed for CV review':'Review this goal before clarifying your CV'}</h2>
  <p className="small">Your goal is saved automatically. Confirm the displayed skills and requirements when you are ready to use them to focus CV questions. Changing this goal requires confirmation again.</p>
  {loading&&<p role="status">Checking your saved confirmation…</p>}
  {stale&&<p role="alert">Your saved goal changed. Reload it to review the current requirements before confirming.</p>}
  {!stale&&state?.reason&&<p className="notice">{state.reason}</p>}
  {error&&<p role="alert">{error}</p>}
  {confirmed?<><p role="status">This version of {goal.role} is confirmed. Your saved CV explanations remain linked to their original sources.</p><Link className="btn pri" href="/cv">Review CV clarifications</Link></>:<div className="row"><button type="button" className="btn pri" disabled={blocked} onClick={()=>void confirm()}>{saving?'Confirming…':'Confirm this goal for CV review'}</button>{stale?<button type="button" className="btn ghost" onClick={onReload}>Reload saved goal</button>:error&&<button type="button" className="btn ghost" disabled={loading||saving} onClick={()=>void load()}>Check confirmation status</button>}</div>}
 </section>;
}
