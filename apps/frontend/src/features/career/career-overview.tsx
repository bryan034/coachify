"use client";

import {useCallback,useEffect,useId,useState} from 'react';
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
  if(creating)return;
  const refresh=()=>{if(document.visibilityState==='visible')setAttempt(value=>value+1);};
  window.addEventListener('focus',refresh);document.addEventListener('visibilitychange',refresh);
  return()=>{window.removeEventListener('focus',refresh);document.removeEventListener('visibilitychange',refresh);};
 },[creating]);
 useEffect(()=>{
  if(!token||creating)return;
  const abort=new AbortController();let timer:ReturnType<typeof setTimeout>;
  let previous:CareerWorkspace|undefined;
  async function load(){
   if(document.visibilityState==='hidden'){timer=setTimeout(()=>void load(),5000);return;}
   try{
   const value=previous?await refreshWorkspace(previous,token!,abort.signal):await careerApi<CareerWorkspace>('/workspace',token!,{signal:abort.signal});
   if(abort.signal.aborted)return;previous=value;setWorkspace(value);setError('');
   timer=setTimeout(()=>void load(),processing.includes(value.phase)?2000:5000);
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
const priorityLabels:Record<ReviewSkill['priority'],string>={required:'Required',preferred:'Preferred',unspecified:'Importance not specified',conflicting:'Conflicting requirements',suggested:'Suggested guidance'};
function RequirementSources({urls=[]}:{urls?:string[]}){
 const links=urls.map(sourceLink).filter(link=>link!==null);
 return links.length?<p className="briefing-sources">{links.map((link,i)=><a key={i} href={link.url} target="_blank" rel="noopener noreferrer">{link.domain} ↗</a>)}</p>:null;
}
const categoryColors:Record<string,string>={'product management':'#116149',ai:'#7053a1',technical:'#345f91',transferable:'#886021',general:'#475569'};
type SkillPresentation={status?:'evidence'|'no-evidence';cvReviewHint?:string};
function SkillFocus({skill,presentation={}}:{skill:ReviewSkill;presentation?:SkillPresentation}){
 const [expanded,setExpanded]=useState(false),id=useId();
 return <article className={`briefing-priority importance-${skill.priority}`}>
  <button type="button" className="briefing-skill-toggle" aria-labelledby={`${id}-title`} aria-expanded={expanded} aria-controls={id} onClick={()=>setExpanded(value=>!value)}>
   <span className="briefing-skill-heading"><span className="briefing-priority-title" id={`${id}-title`}>{skill.name}</span><span className="briefing-category"><span aria-hidden="true" style={{backgroundColor:categoryColors[skill.category.toLowerCase()]||categoryColors.general}}/>{skill.category}</span>{presentation.status&&<span className="briefing-skill-status">{presentation.status==='evidence'?'Evidence in CV':'No evidence yet'}</span>}</span>
   <svg className="briefing-chevron" aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m6 9 6 6 6-6"/></svg>
  </button>
  <div className="briefing-priority-body" id={id} hidden={!expanded}>
   {skill.context&&<><p className="briefing-detail-label">Why this matters</p><p>{skill.context}</p></>}
   {(skill.required_proficiency||skill.required_experience_months!=null)&&<><p className="briefing-detail-label">Role expectations</p><p>{[skill.required_proficiency,skill.required_experience_months!=null?`${skill.required_experience_months} months’ experience`:null].filter(Boolean).join(' · ')}</p></>}
   {skill.group_id&&<p className="briefing-group">{skill.group_operator==='any'?'Alternative requirement — one of the linked skills is needed.':'Part of a combined requirement.'}</p>}
   {skill.evidence&&<><p className="briefing-detail-label">{skill.origin==='employer'?'Source from the job description':'Saved supporting detail'}</p><blockquote>{skill.evidence}</blockquote></>}
   {!skill.context&&!skill.evidence&&!skill.required_proficiency&&skill.required_experience_months==null&&<p>No further detail was saved for this skill. Ask about it in your goal conversation.</p>}
   <p className="briefing-origin">{originLabel(skill)}</p><RequirementSources urls={skill.source_urls}/>
   {presentation.cvReviewHint&&<><p className="briefing-detail-label">What to review in your CV</p><p>{presentation.cvReviewHint}</p></>}
  </div>
 </article>;
}
export function LearningFocus({skills}:{skills:ReviewSkill[]}){
 const [category,setCategory]=useState<string|null>(null),id=useId();
 const categories=[...new Set(skills.map(skill=>skill.category))];
 const filtering=skills.length>12;
 const activeCategory=filtering&&category&&categories.includes(category)?category:null;
 const visible=skills.filter(skill=>!activeCategory||skill.category===activeCategory);
 return <section id="priorities" aria-labelledby="priorities-title">
  <div className="briefing-section-heading"><h2 id="priorities-title">Your learning focus</h2><span className="briefing-count">{skills.length} saved {skills.length===1?'skill':'skills'}</span></div>
  <p className="briefing-description">Not yet compared with your CV. <Link href="/cv">Review my CV</Link></p>
  {filtering&&<div className="briefing-filters" role="group" aria-label="Filter skills by category">{[null,...categories].map(value=><button type="button" key={value??'all'} aria-pressed={activeCategory===value} onClick={()=>setCategory(value)}>{value??'All categories'}</button>)}</div>}
  <div className="briefing-priorities">
   {Object.entries(priorityLabels).map(([priority,label])=>{
    const items=visible.filter(skill=>skill.priority===priority);
    return items.length?<section className="briefing-skill-group" key={priority} aria-labelledby={`${id}-${priority}`}><h3 id={`${id}-${priority}`}>{label} · {items.length}</h3><div className="briefing-skill-grid">{items.map((skill,index)=><SkillFocus key={skill.item_id||`${skill.name}-${index}`} skill={skill}/>)}</div></section>:null;
   })}
   {!skills.length&&<p className="briefing-empty">No skills are listed for this goal yet. Refine your goal to add or clarify them.</p>}
  </div>
 </section>;
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
 const confirmationKey=`${token}:${goal._id}:${goal.version}:${workspace.current.selection_version}`;
 const [confirmedKey,setConfirmedKey]=useState<string|null>(null);
 const onConfirmationChange=useCallback((confirmed:boolean)=>setConfirmedKey(confirmed?confirmationKey:null),[confirmationKey]);
 const confirmed=confirmedKey===confirmationKey;
 const working=processing.includes(workspace.phase);
 async function retryResearch(){if(!token||retrying)return;setRetrying(true);setRetryError('');try{await careerApi('/workspace/retry',token,{method:'POST'});onReload();}catch{setRetryError('Research could not be resumed. Please retry.');}finally{setRetrying(false);}}
 const startingPoint=<aside className={`briefing-context${confirmed?' briefing-context-banner':''}`} aria-label="Your starting point"><section className="briefing-assessment" id="starting-point" aria-label="Your CV skills"><span className="briefing-mini-icon"><Icon name="bolt"/></span>
   <h2>{!assessment?'Checking your CV…':assessment.status==='evaluated'?'CV skills available':assessment.status==='unavailable'?'CV skills status unavailable':assessment.status==='no_cv'?'Add your CV background':'CV skills are not available yet'}</h2>
   <p>{!assessment?'Checking your saved CV and extracted skills.':assessment.status==='evaluated'?'Your saved CV has extracted or user-clarified skills available to review. These are separate from your goal’s requirements.':assessment.status==='unavailable'?'We couldn’t check your saved CV. Your career goal is safe; retry the check or visit your CV page.':assessment.status==='no_cv'?'No saved CV was found. Upload a CV to review and clarify your background.':'A CV is saved, but no successfully extracted skills were found. Visit your CV page to check processing or review the source.'}</p>
   {assessment?.status==='unavailable'&&<button className="btn ghost sm" onClick={()=>setCheck(v=>v+1)}>Retry CV check</button>}
   {assessment&&<Link className="btn pri" href="/cv">{assessment.status==='evaluated'?'View my CV':assessment.status==='no_cv'?'Upload my CV':assessment.status==='unavailable'?'Open my CV':'Review my CV'} <span aria-hidden="true">↗</span></Link>}
   <p className="briefing-micro">No readiness score. Missing evidence doesn’t mean a missing skill. A comparison against this goal is not available yet.</p>
  </section><div className="briefing-aside-note"><h3>Build evidence as you learn.</h3><p>A small, well-explained project can connect what you know with what the role asks for.</p></div></aside>;
 return <section className="page on goal-overview career-briefing">
  <div className="briefing-topbar"><p>Career Goal <span>/</span> Your briefing</p><span className="goal-saved">Saved automatically</span></div>
  <header className="briefing-heading"><div><p className="briefing-eyebrow">A direction you can grow into</p><h1>Your goal. Your next steps.</h1><p className="briefing-heading-copy">Understand what this role asks of you, then find your starting point.</p></div><a className="briefing-plain-link" href="#starting-point">Review my starting point ↗</a></header>
  <section className="briefing-target" id="target" aria-label="Your target role"><div><p className="briefing-eyebrow">Working towards</p><h2>{goal.role}</h2><p className="briefing-target-meta">{[goal.company,goal.location,goal.employment_type&&goal.employment_type!=='unknown'?goal.employment_type.replaceAll('_',' '):null,goal.target_type==='career_exploration'?'Career exploration':null].filter(Boolean).join(' · ')}</p></div><span className="briefing-target-icon"><Icon name="brief"/></span></section>
  <nav className="briefing-jump-links" aria-label="Briefing sections"><a href="#priorities">Learning focus</a><a href="#next-step">Next step</a><a href="#opportunity">Role details</a><Link href="/career-goal/chat?refine=1">Refine goal</Link><button onClick={()=>{session.chooseJD(null);router.push('/career-goal?new=1');}}>Set a new goal <span aria-hidden="true">↗</span></button></nav>
  {loadError&&<div className="notice" role="alert">{loadError} <button className="btn ghost sm" onClick={onReload}>Retry loading goal</button></div>}
  {goal.requirements_need_review&&<p className="notice">Your role context changed. Refine your goal to review which requirements still apply.</p>}
  <CvGoalConfirmationCard key={`${token}:${goal._id}:${goal.version}:${workspace.current.selection_version}`} goal={goal} selectionVersion={workspace.current.selection_version} token={token} onReload={onReload} onConfirmationChange={onConfirmationChange}/>
  {working&&<p className="notice" role="status">{workspace.phase==='waiting_quota'?`Research is waiting for the service allowance and will resume automatically${workspace.retry_after?` in about ${workspace.retry_after} seconds`:''}.`:'Researching opportunity information. Your extracted goal is already saved.'}</p>}
  {workspace.phase==='research_failed'&&<div className="notice" role="alert"><p>Opportunity research could not finish. Your saved goal remains available.</p><button className="btn ghost sm" disabled={retrying} onClick={()=>void retryResearch()}>{retrying?'Resuming research…':'Retry research'}</button>{retryError&&<p>{retryError}</p>}</div>}
  {confirmed&&startingPoint}
  <div className={`briefing-grid${confirmed?' briefing-grid-confirmed':''}`}><div className="briefing-learning">
   <LearningFocus key={`${goal._id}:${goal.version}`} skills={goal.skills}/>
   <section className="briefing-next" id="next-step" aria-labelledby="next-title"><div><p className="briefing-eyebrow">One practical next step</p><h3 id="next-title">{assessment?.status==='evaluated'?'Bring your experience into focus.':'Start with what you already know.'}</h3><p>{assessment?.status==='evaluated'?'Review your saved CV skills alongside these requirements. A comparison against this goal is not available yet.':'Review your CV and background before committing to a learning plan.'}</p></div><Link className="btn" href="/cv">Review my CV <span aria-hidden="true">↗</span></Link></section>
   <section className="briefing-support" id="opportunity" aria-labelledby="opportunity-title"><h2 id="opportunity-title">The opportunity, in context</h2><p className="briefing-description">Useful background when you need it. Your learning focus stays above.</p>
    <details><summary>Eligibility &amp; commitment <span>{goal.non_skill_requirements.length} requirements +</span></summary>{goal.non_skill_requirements.length?<ul className="briefing-conditions">{goal.non_skill_requirements.map(item=><li key={item.requirement_id}><p>{item.description}</p><div className="briefing-tags"><span>{item.category.replaceAll('_',' ')}</span><span>{item.priority}</span></div>{item.group_id&&<p>{item.group_operator==='any'?'One of the linked alternatives is needed.':'Part of a combined requirement.'}</p>}{item.evidence&&<blockquote>{item.evidence}</blockquote>}<p className="briefing-origin">{originLabel(item)}</p><RequirementSources urls={item.source_urls}/></li>)}</ul>:<p>No non-skill requirements were identified. Missing information stays unknown.</p>}</details>
    <details><summary>What you would work on <span>{goal.responsibilities.length} responsibilities +</span></summary>{goal.summary&&<p>{goal.summary}</p>}{!!goal.responsibilities.length&&<ul>{goal.responsibilities.map((item,index)=><li key={index}>{item}</li>)}</ul>}{!goal.summary&&!goal.responsibilities.length&&<p>No responsibilities were saved for this goal.</p>}</details>
    <details><summary>Interviews &amp; company research <span>Sources &amp; findings +</span></summary><OpportunityIntelligence key={goal._id} goalId={goal._id} version={goal.version} selectionVersion={workspace.current.selection_version}/></details>
    <details><summary>How this briefing was put together <span>Sources &amp; limits +</span></summary><p>Your role, skills, conditions and responsibilities come from your saved career goal. Each skill keeps its origin and any saved supporting evidence. User refinements and AI suggestions are labelled separately from job requirements.</p><p>{[goal.field,goal.seniority_level].filter(Boolean).join(' · ')}</p>{goal.job_url&&<RequirementSources urls={[goal.job_url]}/>}<p>Company research keeps its sources, verification dates, uncertainty and related-role or conflicting-report labels. The CV check only reports whether extracted skills are saved; it does not assess individual requirements or hiring readiness.</p><p>Personalised learning outcomes, practice ideas and self-check answers are not available yet.</p></details>
   </section>
  </div>
  {!confirmed&&startingPoint}
  </div>
  <footer className="briefing-footer"><span>elo · Your career copilot</span><span>Based on your saved goal · Research carries its own sources</span></footer>
 </section>;
}
