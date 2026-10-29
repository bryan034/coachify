"use client";

import {useEffect,useState} from 'react';
import Link from 'next/link';
import {useRouter,useSearchParams} from 'next/navigation';
import {Icon} from '@/components/ui/icon';
import {useProfile} from '@/features/profile/profile-provider';
import {careerApi,refreshWorkspace,type AssessmentStatus,type CareerWorkspace,type ReviewSkill} from '@/lib/api/career';
import {useCareerSession} from './career-session';
import {CareerGoal} from './career-goal';
import {OpportunityIntelligence} from './opportunity-intelligence';
import {CvGoalConfirmationCard} from './cv-goal-confirmation';
import {sourceLink} from './source-links';

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
function originLabel(item:{correction?:string;origin?:string}){
 return item.correction==='user'||item.origin==='user_declaration'?'Your refinement':item.origin==='generated_guidance'?'AI planning suggestion':item.origin==='market_research'?'From sampled job listings':'From the job description';
}
const priorityLabels:Record<ReviewSkill['priority'],string>={required:'Required by role',preferred:'Preferred by role',unspecified:'Importance not specified',conflicting:'Conflicting requirements',suggested:'Suggested guidance'};
function RequirementSources({urls=[]}:{urls?:string[]}){
 const links=urls.map(sourceLink).filter(link=>link!==null);
 return links.length?<p className="briefing-sources">{links.map((link,i)=><a key={i} href={link.url} target="_blank" rel="noopener noreferrer">{link.domain} ↗</a>)}</p>:null;
}
function SkillFocus({skill,index}:{skill:ReviewSkill;index:number}){
 return <details className="briefing-priority" open={index===0}>
  <summary><span className="briefing-number">{String(index+1).padStart(2,'0')}</span><span><span className="briefing-priority-title">{skill.name}</span><span className="briefing-priority-description">{skill.category}</span><span className="briefing-tags"><span className={skill.priority==='required'?'role':''}>{priorityLabels[skill.priority]}</span><span>Not assessed against this goal</span></span></span><span className="briefing-chevron" aria-hidden="true">+</span></summary>
  <div className="briefing-priority-body">
   {skill.context&&<><p className="briefing-detail-label">Why this matters</p><p>{skill.context}</p></>}
   {(skill.required_proficiency||skill.required_experience_months!=null)&&<><p className="briefing-detail-label">Role expectations</p><p>{[skill.required_proficiency,skill.required_experience_months!=null?`${skill.required_experience_months} months’ experience`:null].filter(Boolean).join(' · ')}</p></>}
   {skill.group_id&&<p className="briefing-group">{skill.group_operator==='any'?'Alternative requirement — one of the linked skills is needed.':'Part of a combined requirement.'}</p>}
   {skill.evidence&&<><p className="briefing-detail-label">Saved supporting detail</p><blockquote>{skill.evidence}</blockquote></>}
   {!skill.context&&!skill.evidence&&!skill.required_proficiency&&skill.required_experience_months==null&&<p>No further detail was saved for this skill. Ask about it in your goal conversation.</p>}
   <p className="briefing-origin">{originLabel(skill)}</p><RequirementSources urls={skill.source_urls}/>
  </div>
 </details>;
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
 return <section className="page on goal-overview career-briefing">
  <div className="briefing-topbar"><p>Career Goal <span>/</span> Your briefing</p><span className="goal-saved">Saved automatically</span></div>
  <header className="briefing-heading"><div><p className="briefing-eyebrow">A direction you can grow into</p><h1>Your goal. Your next steps.</h1><p className="briefing-heading-copy">Understand what this role asks of you, then find your starting point.</p></div><a className="briefing-plain-link" href="#starting-point">Review my starting point ↗</a></header>
  <section className="briefing-target" id="target" aria-label="Your target role"><div><p className="briefing-eyebrow">Working towards</p><h2>{goal.role}</h2><p className="briefing-target-meta">{[goal.company,goal.location,goal.employment_type&&goal.employment_type!=='unknown'?goal.employment_type.replaceAll('_',' '):null,goal.target_type==='career_exploration'?'Career exploration':null].filter(Boolean).join(' · ')}</p></div><span className="briefing-target-icon"><Icon name="brief"/></span></section>
  <nav className="briefing-jump-links" aria-label="Briefing sections"><a href="#priorities">Learning focus</a><a href="#next-step">Next step</a><a href="#opportunity">Role details</a><Link href="/career-goal/chat?refine=1">Refine goal</Link><button onClick={()=>{session.chooseJD(null);router.push('/career-goal?new=1');}}>Set a new goal <span aria-hidden="true">↗</span></button></nav>
  {loadError&&<div className="notice" role="alert">{loadError} <button className="btn ghost sm" onClick={onReload}>Retry loading goal</button></div>}
  {goal.requirements_need_review&&<p className="notice">Your role context changed. Refine your goal to review which requirements still apply.</p>}
  <CvGoalConfirmationCard key={`${token}:${goal._id}:${goal.version}:${workspace.current.selection_version}`} goal={goal} selectionVersion={workspace.current.selection_version} token={token} onReload={onReload}/>
  {working&&<p className="notice" role="status">{workspace.phase==='waiting_quota'?`Research is waiting for the service allowance and will resume automatically${workspace.retry_after?` in about ${workspace.retry_after} seconds`:''}.`:'Researching opportunity information. Your extracted goal is already saved.'}</p>}
  {workspace.phase==='research_failed'&&<div className="notice" role="alert"><p>Opportunity research could not finish. Your saved goal remains available.</p><button className="btn ghost sm" disabled={retrying} onClick={()=>void retryResearch()}>{retrying?'Resuming research…':'Retry research'}</button>{retryError&&<p>{retryError}</p>}</div>}
  <div className="briefing-grid"><div className="briefing-learning">
   <section id="priorities" aria-labelledby="priorities-title"><div className="briefing-section-heading"><div><p className="briefing-eyebrow">What to build towards</p><h2 id="priorities-title">Your learning focus</h2></div><span className="briefing-count">{goal.skills.length} saved {goal.skills.length===1?'skill':'skills'}</span></div><p className="briefing-description">These skills come from your saved goal. Review your starting point to decide which need your attention. Shown in saved order, without a skill-gap ranking.</p>
    <div className="briefing-priorities">{goal.skills.length?goal.skills.map((skill,index)=><SkillFocus key={skill.item_id||index} skill={skill} index={index}/>):<p className="briefing-empty">No skills are listed for this goal yet. Refine your goal to add or clarify them.</p>}</div>
   </section>
   <section className="briefing-next" id="next-step" aria-labelledby="next-title"><div><p className="briefing-eyebrow">One practical next step</p><h3 id="next-title">{assessment?.status==='evaluated'?'Bring your experience into focus.':'Start with what you already know.'}</h3><p>{assessment?.status==='evaluated'?'Review your saved CV skills alongside these requirements. A comparison against this goal is not available yet.':'Review your CV and background before committing to a learning plan.'}</p></div><Link className="btn" href="/cv">Review my CV <span aria-hidden="true">↗</span></Link></section>
   <section className="briefing-support" id="opportunity" aria-labelledby="opportunity-title"><h2 id="opportunity-title">The opportunity, in context</h2><p className="briefing-description">Useful background when you need it. Your learning focus stays above.</p>
    <details><summary>Eligibility &amp; commitment <span>{goal.non_skill_requirements.length} requirements +</span></summary>{goal.non_skill_requirements.length?<ul className="briefing-conditions">{goal.non_skill_requirements.map(item=><li key={item.requirement_id}><p>{item.description}</p><div className="briefing-tags"><span>{item.category.replaceAll('_',' ')}</span><span>{item.priority}</span></div>{item.group_id&&<p>{item.group_operator==='any'?'One of the linked alternatives is needed.':'Part of a combined requirement.'}</p>}{item.evidence&&<blockquote>{item.evidence}</blockquote>}<p className="briefing-origin">{originLabel(item)}</p><RequirementSources urls={item.source_urls}/></li>)}</ul>:<p>No non-skill requirements were identified. Missing information stays unknown.</p>}</details>
    <details><summary>What you would work on <span>{goal.responsibilities.length} responsibilities +</span></summary>{goal.summary&&<p>{goal.summary}</p>}{!!goal.responsibilities.length&&<ul>{goal.responsibilities.map((item,index)=><li key={index}>{item}</li>)}</ul>}{!goal.summary&&!goal.responsibilities.length&&<p>No responsibilities were saved for this goal.</p>}</details>
    <details><summary>Interviews &amp; company research <span>Sources &amp; findings +</span></summary><OpportunityIntelligence key={goal._id} goalId={goal._id} version={goal.version} selectionVersion={workspace.current.selection_version}/></details>
    <details><summary>How this briefing was put together <span>Sources &amp; limits +</span></summary><p>Your role, skills, conditions and responsibilities come from your saved career goal. Each skill keeps its origin and any saved supporting evidence. User refinements and AI suggestions are labelled separately from job requirements.</p><p>{[goal.field,goal.seniority_level].filter(Boolean).join(' · ')}</p>{goal.job_url&&<RequirementSources urls={[goal.job_url]}/>}<p>Company research keeps its sources, verification dates, uncertainty and related-role or conflicting-report labels. The CV check only reports whether extracted skills are saved; it does not assess individual requirements or hiring readiness.</p><p>Personalised learning outcomes, practice ideas and self-check answers are not available yet.</p></details>
   </section>
  </div>
  <aside className="briefing-context" aria-label="Your starting point"><section className="briefing-assessment" id="starting-point" aria-label="Your CV skills"><span className="briefing-mini-icon"><Icon name="bolt"/></span>
   <h2>{!assessment?'Checking your CV…':assessment.status==='evaluated'?'CV skills available':assessment.status==='unavailable'?'CV skills status unavailable':assessment.status==='no_cv'?'Add your CV background':'CV skills are not available yet'}</h2>
   <p>{!assessment?'Checking your saved CV and extracted skills.':assessment.status==='evaluated'?'Your saved CV has extracted or user-clarified skills available to review. These are separate from your goal’s requirements.':assessment.status==='unavailable'?'We couldn’t check your saved CV. Your career goal is safe; retry the check or visit your CV page.':assessment.status==='no_cv'?'No saved CV was found. Upload a CV to review and clarify your background.':'A CV is saved, but no successfully extracted skills were found. Visit your CV page to check processing or review the source.'}</p>
   {assessment?.status==='unavailable'&&<button className="btn ghost sm" onClick={()=>setCheck(v=>v+1)}>Retry CV check</button>}
   {assessment&&<Link className="btn pri" href="/cv">{assessment.status==='evaluated'?'View my CV':assessment.status==='no_cv'?'Upload my CV':assessment.status==='unavailable'?'Open my CV':'Review my CV'} <span aria-hidden="true">↗</span></Link>}
   <p className="briefing-micro">No readiness score. Missing evidence doesn’t mean a missing skill. A comparison against this goal is not available yet.</p>
  </section><div className="briefing-aside-note"><h3>Build evidence as you learn.</h3><p>A small, well-explained project can connect what you know with what the role asks for.</p></div></aside>
  </div>
  <footer className="briefing-footer"><span>COACHIFY · Your career copilot</span><span>Based on your saved goal · Research carries its own sources</span></footer>
 </section>;
}
