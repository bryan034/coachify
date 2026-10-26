"use client";
import {useEffect,useRef,useState} from 'react';
import {useRouter} from 'next/navigation';
import {useProfile} from '@/features/profile/profile-provider';
import {careerApi,type CurrentGoal,type ResearchView,type SavedReview} from '@/lib/api/career';

export function CareerTools({current:provided}:{current?:CurrentGoal}={}){
 const {token}=useProfile();const [loaded,setLoaded]=useState<CurrentGoal>();
 useEffect(()=>{if(provided||!token)return;const abort=new AbortController();void careerApi<CurrentGoal>('/goals/current',token,{signal:abort.signal}).then(v=>{if(!abort.signal.aborted)setLoaded(v);}).catch(()=>{});return()=>abort.abort();},[token,provided]);
 const current=provided||loaded;
 if(!token||!current?.goal)return null;
 return <GoalTools key={`${token}:${current.goal._id}:${current.selection_version}`} current={current} token={token}/>;
}
function GoalTools({current,token}:{current:CurrentGoal;token:string}){
 const router=useRouter();const goal=current.goal!;
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[open,setOpen]=useState(()=>typeof window!=='undefined'&&new URLSearchParams(window.location.search).has('research'));
 const controller=useRef<AbortController|null>(null),key=useRef(crypto.randomUUID());
 useEffect(()=>()=>controller.current?.abort(),[]);
 async function generate(){
  const abort=new AbortController();controller.current?.abort();controller.current=abort;setBusy(true);setError('');
  try{const result=await careerApi<SavedReview>(`/goals/${goal._id}/guidance`,token,{method:'POST',signal:abort.signal,
   headers:{'Idempotency-Key':key.current},body:JSON.stringify({expected_version:goal.version,expected_selection_version:current.selection_version})});
   if(!abort.signal.aborted)router.push(`/career-goal/chat?source=jd&review=${result.review_id}`);
  }catch(cause){if(!abort.signal.aborted)setError(cause instanceof Error?cause.message:'Could not generate guidance.');}
  finally{if(!abort.signal.aborted)setBusy(false);}
 }
 return <section className="card pad career-tools" aria-label="Selected career goal tools"><p className="k">Your selected direction</p><h2>{goal.role}</h2>
  <p className="small">{goal.company||'General career direction'} · {goal.field}</p>
  <div className="row">{goal.target_type==='career_exploration'&&<button className="btn pri" disabled={busy} onClick={()=>void generate()}>{busy?'Generating advisory skills…':'Generate role skills'}</button>}
   <button className="btn ghost" onClick={()=>setOpen(v=>!v)} aria-expanded={open}>{open?'Hide interview research':'Interview research'}</button></div>
  {goal.target_type==='career_exploration'&&<p className="small">Generated skills are planning advice. Review and save them before confirming a revised goal.</p>}
  {error&&<p role="alert">{error} Your saved direction is unchanged.</p>}
  {open&&<InterviewResearch current={current} token={token}/>}
 </section>;
}
export function InterviewResearch({current,token}:{current:CurrentGoal;token:string}){
 const goal=current.goal!;const [result,setResult]=useState<ResearchView>(),[error,setError]=useState('');
 const [busy,setBusy]=useState(false),[revision,setRevision]=useState(''),[check,setCheck]=useState(0);
 const controller=useRef<AbortController|null>(null),receipt=useRef<{signature:string;key:string}|null>(null);
 const params=typeof window!=='undefined'?new URLSearchParams(window.location.search):new URLSearchParams();
 const goalId=params.get('goal')||goal._id;const initial=params.get('research')||'';
 const historicalGoal=goalId!==goal._id;
 useEffect(()=>{const abort=new AbortController();controller.current=abort;
  const id=revision||(check===0?initial:'');
  void careerApi<ResearchView>(`/goals/${goalId}/interview-research${id?'?research_id='+encodeURIComponent(id):''}`,token,{signal:abort.signal})
   .then(v=>{if(!abort.signal.aborted)setResult(v);}).catch(c=>{if(!abort.signal.aborted)setError(c instanceof Error?c.message:'Research could not be loaded.');});
  return()=>abort.abort();
 },[token,goalId,revision,initial,check]);
 useEffect(()=>()=>controller.current?.abort(),[]);
 useEffect(()=>{if(result?.status!=='processing')return;const timer=setTimeout(()=>setCheck(v=>v+1),2000);return()=>clearTimeout(timer);},[result,check]);
 async function requestResearch(refresh=false){
  if(busy||historicalGoal)return;const abort=new AbortController();controller.current?.abort();controller.current=abort;setBusy(true);setError('');
  const body=JSON.stringify({expected_version:goal.version,expected_selection_version:current.selection_version,refresh});
  if(receipt.current?.signature!==body)receipt.current={signature:body,key:crypto.randomUUID()};
  try{const value=await careerApi<ResearchView>(`/goals/${goal._id}/interview-research`,token,{method:'POST',signal:abort.signal,headers:{'Idempotency-Key':receipt.current.key},body});
   if(!abort.signal.aborted){setResult(value);setRevision('');receipt.current=null;}
  }catch(cause){if(!abort.signal.aborted){setError(cause instanceof Error?cause.message:'Research is unavailable.');
    try{const saved=await careerApi<ResearchView>(`/goals/${goal._id}/interview-research`,token,{signal:abort.signal});if(!abort.signal.aborted)setResult(saved);}catch{}}
  }finally{if(!abort.signal.aborted)setBusy(false);}
 }
 const research=result?.research;
 return <section className="interview-research" aria-label="Interview research"><h3>Interview preparation evidence</h3>
  <p className="small">{result?.context.company?`${result.context.company} · ${result.context.role}`:`General role-level research · ${result?.context.role||goal.role}`}. Research does not establish personal skill gaps.</p>
  <p role="status">{busy?'Researching permitted public sources…':`Status: ${result?.status||'loading'}`}{result?.reused?' · Reused saved research':''}{result?.stale?' · Stale (older than seven days)':''}{result?.historical?' · Historical version':''}</p>
  {!historicalGoal&&<><p className="small">Research uses connected source APIs. If none are connected, new research is unavailable; saved evidence stays readable.</p>
   <div className="row"><button className="btn pri" disabled={busy||!result||result.status==='processing'} onClick={()=>void requestResearch(false)}>{research?'Reuse or retry research':'Research interviews'}</button>
    {research&&<button className="btn ghost" disabled={busy} onClick={()=>void requestResearch(true)}>Refresh research</button>}
    <button className="btn ghost" disabled={busy} onClick={()=>{setRevision('');setCheck(v=>v+1);}}>Show latest saved version</button></div></>}
  {error&&<p role="alert">{error} Previous successful research is retained.</p>}
  {research&&<><p className="small">Version {research.version} · Last researched: {new Date(research.last_researched_at).toLocaleString()}</p>
   <a href={`/career-goal?goal=${goalId}&research=${research._id}`}>Link to this research version</a>
   {!!result?.history?.length&&<label>Saved research version<select value={revision||research._id} onChange={e=>setRevision(e.target.value)}>{result.history.map(id=><option value={id} key={id}>{id===research._id?`Version ${research.version}`:id.slice(-8)}</option>)}</select></label>}
   {research.research_status==='no_findings'&&<p>No supported interview topics were found in the retrieved sources. This does not mean there are no interview expectations.</p>}
   {research.summaries?.map(summary=><details key={summary.summary_id}><summary>AI interview summary</summary><p className="small">AI synthesis with linked source evidence</p><p style={{whiteSpace:'pre-line'}}>{summary.text}</p>{summary.source_ids.map(id=>{const source=research.sources.find(s=>s.source_id===id);return source?<p key={id}><a href={source.url} target="_blank" rel="noopener noreferrer">{source.title||source.platform}</a></p>:null;})}</details>)}
   {research.skills.map((topic,index)=><article className="requirement-item" key={`${topic.skill_id||topic.name}:${index}`}><h4>{topic.name}</h4>{topic.evidence_origin==='brave_summary'&&<p className="small">AI synthesis · source-linked, not a direct website quotation</p>}<p>{topic.category} · Stage: {topic.interview_stage||'Unknown'} · Assessment: {topic.assessment_type||'Unknown'} · Difficulty: {topic.difficulty||'Unknown'}</p>
    <p className="small">Independent reports: {topic.source_ids.some(id=>!research.sources.find(s=>s.source_id===id)?.report_group)?'Unknown — independence not verified':topic.independent_report_count}. Anecdotal questions are not guaranteed.</p>
    {topic.question_patterns.length>0&&<ul>{topic.question_patterns.map((pattern,i)=><li key={i}>{pattern}</li>)}</ul>}
    {topic.source_ids.map(id=>{const source=research.sources.find(s=>s.source_id===id);return source?<details key={id}><summary>{source.reliability==='official'?'Official employer guidance':source.reliability==='anecdotal'?'Individual/anecdotal report':'Unverified public guidance'} · {source.title||source.platform}</summary>
     <p><a href={source.url} target="_blank" rel="noopener noreferrer">{source.title||source.url}</a> · {source.platform} · {source.source_id}</p>
     <p className="small">Context match: {source.role_match}. {source.role_match!=='exact'?'Location, seniority or role context may differ.':''}</p><blockquote>{source.evidence||'No excerpt available'}</blockquote>
     <p className="small">Published: {source.published_date||'Unknown'} · Reported: {source.reported_date||'Unknown'} · Retrieved: {source.retrieved_at?new Date(source.retrieved_at).toLocaleDateString():'Unknown'}</p>
    </details>:<p key={id}>Source {id} is unavailable.</p>;})}</article>)}
   <p className="small">{result?.note}</p></>}
 </section>;
}
