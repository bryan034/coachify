"use client";

import {useEffect,useState,type ReactNode} from 'react';
import Link from 'next/link';
import {useRouter,useSearchParams} from 'next/navigation';
import {Icon} from '@/components/ui/icon';
import {useProfile} from '@/features/profile/profile-provider';
import {careerApi,refreshWorkspace,type AssessmentStatus,type CareerWorkspace,type ReviewSkill} from '@/lib/api/career';
import {useCareerSession} from './career-session';
import {CareerGoal} from './career-goal';
import {OpportunityIntelligence} from './opportunity-intelligence';

const processing=['research_pending','researching','waiting_quota'];
export function CareerGoalHome(){
 const {token}=useProfile(),params=useSearchParams();
 const [workspace,setWorkspace]=useState<CareerWorkspace>(),[error,setError]=useState(''),[attempt,setAttempt]=useState(0);
 const creating=params.get('new')==='1';
 useEffect(()=>{
  if(!token||creating)return;
  const abort=new AbortController();let timer:ReturnType<typeof setTimeout>;
  let previous:CareerWorkspace|undefined;
  async function load(){try{
   const value=previous?await refreshWorkspace(previous,token!,abort.signal):await careerApi<CareerWorkspace>('/workspace',token!,{signal:abort.signal});
   if(abort.signal.aborted)return;previous=value;setWorkspace(value);setError('');
   if(processing.includes(value.phase))timer=setTimeout(()=>void load(),2000);
  }catch{if(!abort.signal.aborted)setError('Your saved goal could not be loaded. Please retry.');}}
  void load();return()=>{abort.abort();clearTimeout(timer);};
 },[token,creating,attempt]);
 if(creating)return <><div className="goal-return"><Link href="/career-goal">← Back to saved goal</Link><p className="small">Your current goal stays saved until the new description is successfully extracted.</p></div><CareerGoal replacing/></>;
 if(!workspace)return <section className="page on"><h1>Career Goal</h1>{error?<><p role="alert">{error}</p><button className="btn pri" onClick={()=>setAttempt(v=>v+1)}>Retry loading goal</button></>:<p role="status">Opening your career goal…</p>}</section>;
 if(!workspace.current?.goal)return <CareerGoal/>;
 return <CareerGoalOverview workspace={workspace} loadError={error} onReload={()=>setAttempt(v=>v+1)}/>;
}
function grouped<T extends {category:string}>(items:T[]){
 const result=new Map<string,T[]>();for(const item of items){const category=item.category||'Other';result.set(category,[...(result.get(category)||[]),item]);}return [...result];
}
function CategoryCard({title,count,children}:{title:string;count?:number;children:ReactNode}){
 return <article className="card goal-category"><header><h3>{title}</h3>{count!=null&&<span className="goal-item-count">{count} {count===1?'item':'items'}</span>}</header>{children}</article>;
}
function SkillItem({skill}:{skill:ReviewSkill}){
 return <li><div className="goal-item-title"><strong>{skill.name}</strong><span className="goal-priority">{skill.priority}</span></div>
  {skill.context&&<p className="small">{skill.context}</p>}
  {(skill.required_proficiency||skill.required_experience_months!=null)&&<p className="small">{[skill.required_proficiency,skill.required_experience_months!=null?`${skill.required_experience_months} months’ experience`:null].filter(Boolean).join(' · ')}</p>}
  {skill.group_id&&<p className="small">{skill.group_operator==='any'?'Alternative requirement — one of the linked skills is needed.':'Part of a combined requirement.'}</p>}
  <p className="goal-origin">{skill.correction==='user'||skill.origin==='user_declaration'?'Your refinement':skill.origin==='generated_guidance'?'AI planning suggestion':skill.origin==='market_research'?'From sampled job listings':'From the job description'}</p>
  {skill.evidence&&<details><summary>Supporting detail</summary><blockquote>{skill.evidence}</blockquote></details>}
 </li>;
}
export function CareerGoalOverview({workspace,loadError='',onReload}:{workspace:CareerWorkspace;loadError?:string;onReload:()=>void}){
 const {token}=useProfile(),router=useRouter(),session=useCareerSession();
 const [assessment,setAssessment]=useState<AssessmentStatus>(),[check,setCheck]=useState(0),[retrying,setRetrying]=useState(false),[retryError,setRetryError]=useState('');
 useEffect(()=>{if(!token)return;const abort=new AbortController();setAssessment(undefined);
  void careerApi<AssessmentStatus>('/context/assessment',token,{signal:abort.signal}).then(v=>{if(!abort.signal.aborted)setAssessment(v);}).catch(()=>{if(!abort.signal.aborted)setAssessment({status:'unavailable',cv_uploaded:null,skills_evaluated:null});});
  return()=>abort.abort();
 },[token,check]);
 const saved=workspace.current.goal!;
 const goal={...saved,summary:saved.summary||null,responsibilities:saved.responsibilities||[],non_skill_requirements:saved.non_skill_requirements||[]};
 const working=processing.includes(workspace.phase);
 async function retryResearch(){if(!token||retrying)return;setRetrying(true);setRetryError('');try{await careerApi('/workspace/retry',token,{method:'POST'});onReload();}catch{setRetryError('Research could not be resumed. Please retry.');}finally{setRetrying(false);}}
 return <section className="page on goal-overview">
  <header className="ptitle"><div><p className="small">Your direction, clearly defined</p><h1>Career Goal</h1></div><span className="goal-saved">Saved automatically</span></header>
  <section className="goal-target" aria-label="Your target role">
   <p className="goal-target-label">Your target role</p><div className="goal-target-heading"><span className="goal-target-icon"><Icon name="brief"/></span><div><h2>{goal.role}</h2><p>{[goal.field,goal.seniority_level].filter(Boolean).join(' · ')}</p></div></div>
   {goal.summary&&<p className="goal-target-summary">{goal.summary}</p>}
   <div className="goal-target-tags">{[goal.employment_type&&goal.employment_type!=='unknown'?goal.employment_type.replaceAll('_',' '):null,goal.company,goal.location,workspace.current.goal?.target_type==='career_exploration'?'Career exploration':null].filter(Boolean).map((tag,i)=><span key={i}>{tag}</span>)}</div>
   <div className="goal-target-actions"><Link className="btn" href="/career-goal/chat?refine=1"><Icon name="chat"/>Refine goal</Link><button className="btn" onClick={()=>{session.chooseJD(null);router.push('/career-goal?new=1');}}>Set a new goal <span aria-hidden="true">↗</span></button></div>
  </section>
  {loadError&&<div className="notice" role="alert">{loadError} <button className="btn ghost sm" onClick={onReload}>Retry loading goal</button></div>}
  {workspace.current.goal?.requirements_need_review&&<p className="notice">Your role context changed. Refine your goal to review which requirements still apply.</p>}
  <section className="card goal-assessment" aria-label="Your skill assessment"><span className="goal-assessment-icon"><Icon name="doc"/></span><div>
   <h2>{!assessment?'Checking your skills…':assessment.status==='evaluated'?'Your assessed skills are saved':assessment.status==='unavailable'?'Skill assessment status unavailable':assessment.status==='no_cv'?'Bring your skills into the picture':'Your skills still need assessment'}</h2>
   <p className="small">{!assessment?'Checking your saved CV and extracted skills.':assessment.status==='evaluated'?'Your saved CV contains assessed skills. These are separate from your goal’s requirements.':assessment.status==='unavailable'?'We couldn’t check your saved CV. Your career goal is safe; retry the check or visit your CV page.':assessment.status==='no_cv'?'No saved CV was found. Visit CV upload to add your background and assess your skills.':'A CV is saved, but no successfully extracted skills were found. Visit your CV page to continue.'}</p>
   {assessment?.status==='unavailable'&&<button className="btn ghost sm" onClick={()=>setCheck(v=>v+1)}>Retry skill check</button>}
  </div>{assessment&&<Link className="btn pri" href="/cv">{assessment.status==='evaluated'?'View my CV':assessment.status==='unavailable'?'Go to CV upload':'Assess my skills'} <span aria-hidden="true">↗</span></Link>}</section>
  {working&&<p className="notice" role="status">{workspace.phase==='waiting_quota'?`Research is waiting for the service allowance and will resume automatically${workspace.retry_after?` in about ${workspace.retry_after} seconds`:''}.`:'Researching opportunity information. Your extracted goal is already saved.'}</p>}
  <section className="goal-section" aria-labelledby="goal-skills-heading"><div className="goal-section-heading"><h2 id="goal-skills-heading">Skills</h2><p className="small">What this role calls for</p></div>
   {goal.skills.length?<div className="goal-category-grid">{grouped(goal.skills).map(([category,skills])=><CategoryCard key={category} title={`${category} skills`} count={skills.length}><ul className="goal-item-list">{skills.map((skill,i)=><SkillItem key={skill.item_id||i} skill={skill}/>)}</ul></CategoryCard>)}</div>:<div className="card goal-category"><p className="small">No skills are listed for this goal yet. Refine your goal to add or clarify them.</p></div>}
  </section>
  <section className="goal-section" aria-labelledby="goal-conditions-heading"><div className="goal-section-heading"><h2 id="goal-conditions-heading">Non-skill requirements</h2><p className="small">Qualifications, experience and other conditions</p></div>
   {goal.non_skill_requirements.length?<div className="goal-category-grid">{grouped(goal.non_skill_requirements).map(([category,items])=><CategoryCard key={category} title={category.replaceAll('_',' ')} count={items.length}><ul className="goal-item-list">{items.map(item=><li key={item.requirement_id}><p>{item.description}</p><span className="goal-priority">{item.priority}</span>{item.group_id&&<p className="small">{item.group_operator==='any'?'One of the linked alternatives is needed.':'Part of a combined requirement.'}</p>}<p className="goal-origin">{item.correction==='user'||item.origin==='user_declaration'?'Your refinement':item.origin==='generated_guidance'?'AI planning suggestion':'From the job description'}</p></li>)}</ul></CategoryCard>)}</div>:<div className="card goal-category"><p className="small">No non-skill requirements were identified. Missing information stays unknown.</p></div>}
  </section>
  {!!goal.responsibilities.length&&<section className="goal-section"><h2>Responsibilities</h2><CategoryCard title="What you’ll do" count={goal.responsibilities.length}><ul className="goal-item-list">{goal.responsibilities.map((item,i)=><li key={i}>{item}</li>)}</ul></CategoryCard></section>}
  {workspace.current.goal&&<OpportunityIntelligence key={workspace.current.goal._id} goalId={workspace.current.goal._id} version={workspace.current.goal.version} selectionVersion={workspace.current.selection_version}/>}

 </section>;
}
