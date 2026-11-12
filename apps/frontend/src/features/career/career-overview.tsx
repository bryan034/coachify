"use client";

import {useCallback,useEffect,useId,useState} from 'react';
import Link from 'next/link';
import {useRouter,useSearchParams} from 'next/navigation';
import {Icon} from '@/components/ui/icon';
import {useProfile} from '@/features/profile/profile-provider';
import {careerApi,refreshWorkspace,type CareerWorkspace,type ReviewSkill} from '@/lib/api/career';
import {useCareerSession} from './career-session';
import {CareerGoal} from './career-goal';
import {OpportunityIntelligence,type RoleCardInput} from './opportunity-intelligence';
import {CvGoalConfirmationCard} from './cv-goal-confirmation';
import {sourceLink} from './source-links';
import {OTHER_SKILLS,groupSkills,type SkillGroupMap} from '@/lib/skill-groups';
import {type SkillMatch} from '@/lib/api/assessment';
import '@/styles/goal.css';
import { useComparison } from '@/features/assessment/comparison';
import { EvaluateBanner } from '@/features/assessment/evaluate-banner';
import { ProcessingCard, SkeletonRows, type ProcessingStep } from '@/components/ui/processing-card';
import type { Requirement } from '@/features/roadmap/types';
import { formatDate } from '@/lib/format';
import { PageSkeleton } from '@/components/ui/workspace-ui';

const processing=['research_pending','researching','waiting_quota'];
export type GoalView='skills'|'interview'|'role';
export function CareerGoalHome({view='skills'}:{view?:GoalView}={}){
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
 if(!workspace)return <section className="page on"><h1>Career Goal</h1>{error?<><p role="alert">{error}</p><button className="btn pri" onClick={()=>setAttempt(v=>v+1)}>Retry loading goal</button></>:<PageSkeleton label="Opening your career goal…"/>}</section>;
 if(!workspace.current?.goal)return <CareerGoal/>;
 return <CareerGoalOverview view={view} workspace={workspace} loadError={error} onReload={()=>setAttempt(v=>v+1)}/>;
}
function originLabel(item:{correction?:string;origin?:string}){
 return item.correction==='user'||item.origin==='user_declaration'?'Your refinement':item.origin==='generated_guidance'?'AI planning suggestion':item.origin==='market_research'?'From sampled job listings':'From the job description';
}
const priorityLabels:Record<ReviewSkill['priority'],string>={required:'Required',preferred:'Preferred',unspecified:'Importance not specified',conflicting:'Conflicting requirements',suggested:'Suggested guidance'};
function RequirementSources({urls=[]}:{urls?:string[]}){
 const links=urls.map(sourceLink).filter(link=>link!==null);
 return links.length?<p className="briefing-sources">{links.map((link,i)=><a key={i} href={link.url} target="_blank" rel="noopener noreferrer">{link.domain} ↗</a>)}</p>:null;
}
const priorityOrder=Object.keys(priorityLabels) as ReviewSkill['priority'][];
const sentence=(value:string)=>value.charAt(0).toUpperCase()+value.slice(1);
// Missing proof is never called a gap: only a confirmed shortfall is.
const matchLabels:Record<SkillMatch,string>={supported:'Have',covered:'Covered by an alternative',partial:'Partial',uncertain:'Unknown',confirmed_shortfall:'Gap'};

/** Importance shown by colour. Unstated importance that elo inferred is marked as inferred. */
type Importance='essential'|'important'|'nice'|'unclear';
const importanceLabels:Record<Importance,string>={essential:'Essential',important:'Important',nice:'Nice to have',unclear:'Conflicting requirements'};
const skillImportance=(skill:ReviewSkill):Importance=>skill.priority==='required'?'essential':skill.priority==='preferred'?'important':skill.priority==='conflicting'?'unclear':'nice';
const itemImportance=(value:'high'|'medium'|'low'):Importance=>value==='high'?'essential':value==='medium'?'important':'nice';
const inferredImportance=(skill:ReviewSkill)=>(skill.priority_origin??skill.origin)==='generated_guidance';
function InferredMark(){return <span className="inferred-mark" title="Importance inferred by elo" aria-label="importance inferred by elo">◆</span>;}

/** Planning-estimate bands. 10 means your evidence meets the level this goal states (rubric v1). */
const band=(score:number)=>score>=8.5?'ready':score>=6?'growing':'build';
function ScoreChip({outcome,match,id}:{outcome?:Requirement;match?:SkillMatch;id:string}){
 const score=outcome?.competence_score;
 if(score!=null)return <span id={id} className={`score-chip score-${band(score)}`}>{score}<small> / 10</small></span>;
 if(match)return <span id={id} className={`skill-match match-${match}`}>{matchLabels[match]}</span>;
 return <span id={id} className="score-chip score-none">Not compared</span>;
}
function CompetenceBar({outcome}:{outcome?:Requirement}){
 const score=outcome?.competence_score;
 if(score==null)return <p className="small">{outcome?.score_status==='insufficient_evidence'?'Level unknown from your CV review.':outcome?'Competence not recorded yet. Your CV review hasn’t covered this level.':'Evaluate your skills to see where you stand.'}</p>;
 return <><div className="competence-bar" role="img" aria-label={`Your competence ${score} out of 10 against the level this role needs`}><span className={`competence-fill score-${band(score)}`} style={{width:`${score*10}%`}}/><span className="competence-target"/></div>
  {outcome?.demonstrated_score!=null&&outcome.required_score!=null&&<p className="small goal-skill-levels">You: about {outcome.demonstrated_score} / 10 · role needs about {outcome.required_score} / 10</p>}
  <p className="small">Planning estimate: {score} / 10. 10 means your evidence meets the level this role states.{outcome?.score_explanation?` ${outcome.score_explanation}`:''}</p></>;
}
/** Skills Profile skills the comparison linked to this goal skill, with their own level. */
function ProfileLinks({outcome}:{outcome?:Requirement}){
 if(!outcome)return null;
 const linked=outcome.profile_skills??[];
 return <><p className="briefing-detail-label">From your Skills Profile</p>
  {linked.length?<ul className="goal-skill-profile-links">{linked.map(skill=><li key={skill.canonical_skill_id||skill.name}><Link href="/cv">{skill.name}</Link>{skill.competence_score!=null&&<span className="small"> · about {skill.competence_score} / 10</span>}</li>)}</ul>
  :<p className="small">No skill in your Skills Profile covers this yet.</p>}</>;
}
function SkillRow({skill,match,outcome}:{skill:ReviewSkill;match?:SkillMatch;outcome?:Requirement}){
 const [expanded,setExpanded]=useState(false),id=useId();
 const importance=skillImportance(skill),inferred=inferredImportance(skill);
 return <li className="skill-row goal-skill-row">
  <button type="button" className="skill-row-toggle" aria-labelledby={`${id}-title`} aria-describedby={`${id}-status`} aria-expanded={expanded} aria-controls={id} onClick={()=>setExpanded(value=>!value)}>
   <span className={`importance-square importance-${importance}`} aria-hidden="true"/>
   <span className="goal-skill-name"><span id={`${id}-title`}>{skill.name}</span>{inferred&&<InferredMark/>}</span>
   <span className="goal-skill-importance">{importanceLabels[importance]}</span>
   <ScoreChip id={`${id}-status`} outcome={outcome} match={match}/>
   <span className="skill-rank-chevron" aria-hidden="true"/>
  </button>
  <div className="goal-skill-details" id={id} hidden={!expanded}>
   <div>
    {skill.context&&<><p className="briefing-detail-label">Why this matters</p><p>{skill.context}</p></>}
    <p className="briefing-detail-label">Importance</p><p>{importanceLabels[importance]}. {inferred?'The job description doesn’t say, so elo inferred this from the description and research.':skill.origin==='market_research'?'From sampled job listings.':skill.origin==='user_declaration'||skill.correction==='user'?'Set in your refinement.':'Stated in the job description.'}</p>
    {(skill.required_proficiency||skill.required_experience_months!=null)&&<><p className="briefing-detail-label">Role expectations</p><p>{[skill.required_proficiency?`${sentence(skill.required_proficiency)} level expected`:null,skill.required_experience_months!=null?`${skill.required_experience_months} months’ experience`:null].filter(Boolean).join(' · ')}</p></>}
    {skill.group_id&&<p className="briefing-group">{skill.group_operator==='any'?'Alternative requirement — one of the linked skills is needed.':'Part of a combined requirement.'}</p>}
    {skill.evidence&&skill.origin!=='employer'&&<><p className="briefing-detail-label">Saved supporting detail</p><blockquote>{skill.evidence}</blockquote></>}
    <p className="briefing-detail-label">Your competence</p><CompetenceBar outcome={outcome}/>
    <ProfileLinks outcome={outcome}/>
    <p className="briefing-origin">{originLabel(skill)}</p><RequirementSources urls={skill.source_urls}/>
   </div>
   <div>
    <p className="briefing-detail-label">What you need</p>
    {skill.learning_items?.length?<ul className="learning-items">{skill.learning_items.map(item=><li key={item.item_id} className="learning-item"><span className={`importance-square importance-${itemImportance(item.importance)}`} aria-label={importanceLabels[itemImportance(item.importance)]}/><span><strong>{item.name}</strong>{item.importance_origin==='inferred'&&<InferredMark/>}<span className="small">{item.reason}</span><RequirementSources urls={item.source_urls}/></span></li>)}</ul>:<p className="small">No specific items saved yet. Refine your goal to break this skill down.</p>}
    <Link className="goal-skill-roadmap" href="/roadmap">{outcome?.competence_score===10?'Already at the level this role needs':'See where this is in your roadmap'}</Link>
   </div>
  </div>
 </li>;
}
const SHOWN=10;
/** Grouped by category, most important first. Long lists start short; every skill stays reachable. */
export function LearningFocus({skills,categories,matches,outcomes}:{skills:ReviewSkill[];categories?:SkillGroupMap;matches?:Record<string,SkillMatch>|null;outcomes?:Record<string,Requirement>|null}){
 const [all,setAll]=useState(false);
 const ordered=[...skills].sort((a,b)=>priorityOrder.indexOf(a.priority)-priorityOrder.indexOf(b.priority));
 const best=(items:ReviewSkill[])=>Math.min(...items.map(skill=>priorityOrder.indexOf(skill.priority)));
 const groups=groupSkills(ordered,skill=>skill.name,categories).sort((a,b)=>Number(a.name===OTHER_SKILLS)-Number(b.name===OTHER_SKILLS)||best(a.items)-best(b.items));
 let budget=all?Infinity:SHOWN;
 const visible=groups.map(group=>{const items=group.items.slice(0,Math.max(0,budget));budget-=items.length;return {...group,items};}).filter(group=>group.items.length);
 const hiddenSkills=skills.length-visible.reduce((n,group)=>n+group.items.length,0),hiddenGroups=groups.length-visible.filter(group=>group.items.length===groups.find(g=>g.name===group.name)!.items.length).length;
 const scored=skills.map(skill=>skill.item_id?outcomes?.[skill.item_id]?.competence_score:null).filter((score):score is number=>score!=null);
 const counts=matches?(['supported','partial','confirmed_shortfall','uncertain'] as SkillMatch[]).map(status=>[status,skills.filter(skill=>skill.item_id&&(matches[skill.item_id]===status||(status==='supported'&&matches[skill.item_id]==='covered'))).length] as const):[];
 const kinds=new Set(skills.map(skillImportance));
 return <section id="priorities" className="card goal-skills" aria-labelledby="priorities-title">
  <div className="goal-skills-head">
   <div><h2 id="priorities-title">Skills needed</h2><p className="small">{outcomes?'Your competence out of 10, against the level this role needs. Click a skill for details.':'Click a skill for details. Evaluate your skills to see your competence in each one.'}</p></div>
   {skills.length>0&&<p className="goal-skills-summary">{scored.length>0?<><strong className="band-ready">{scored.filter(v=>band(v)==='ready').length} ready</strong> · <strong className="band-growing">{scored.filter(v=>band(v)==='growing').length} getting there</strong> · <strong className="band-build">{scored.filter(v=>band(v)==='build').length} to build</strong> · {skills.length-scored.length} not rated</>:counts.length?<>You have <strong>{counts[0][1]}</strong> of {skills.length}{counts.slice(1).filter(([,n])=>n).map(([status,n])=><span key={status}> · {n} {matchLabels[status].toLowerCase()}</span>)}</>:<>{skills.length} saved {skills.length===1?'skill':'skills'}</>}</p>}
  </div>
  {skills.length>0&&<div className="goal-skills-legend"><span>Importance:</span>{(['essential','important','nice','unclear'] as Importance[]).filter(kind=>kinds.has(kind)).map(kind=><span key={kind}><i className={`importance-square importance-${kind}`} aria-hidden="true"/>{importanceLabels[kind]}</span>)}{skills.some(inferredImportance)&&<span><InferredMark/>Inferred by elo</span>}{scored.length>0&&<><span className="legend-divider" aria-hidden="true"/><span>Competence:</span><span><i className="score-dot score-ready" aria-hidden="true"/>8.5+</span><span><i className="score-dot score-growing" aria-hidden="true"/>6 – 8.4</span><span><i className="score-dot score-build" aria-hidden="true"/>Below 6</span></>}</div>}
  {visible.map(group=><section key={group.name} className="goal-skill-category" aria-label={group.name}><h3>{group.name}</h3><ul className="goal-skill-list">{group.items.map(skill=><SkillRow key={skill.item_id||skill.name} skill={skill} match={skill.item_id?matches?.[skill.item_id]:undefined} outcome={skill.item_id?outcomes?.[skill.item_id]:undefined}/>)}</ul></section>)}
  {hiddenSkills>0&&<button type="button" className="btn ghost goal-skills-more" onClick={()=>setAll(true)}>Show {hiddenSkills} more {hiddenSkills===1?'skill':'skills'}{hiddenGroups>0?` in ${hiddenGroups} ${hiddenGroups===1?'category':'categories'}`:''}</button>}
  {all&&skills.length>SHOWN&&<button type="button" className="btn ghost goal-skills-more" onClick={()=>setAll(false)}>Show fewer skills</button>}
  {!skills.length&&<p className="briefing-empty">No skills are listed for this goal yet. Refine your goal to add or clarify them.</p>}
 </section>;
}
/** Part-to-whole of the backend's own priorities. Every slice is named and counted beside the ring. */
function PriorityRing({skills}:{skills:ReviewSkill[]}){
 const required=skills.filter(skill=>skill.priority==='required').length,preferred=skills.filter(skill=>skill.priority==='preferred').length;
 const slices=[{key:'required',label:'Required',count:required},{key:'preferred',label:'Preferred',count:preferred},{key:'other',label:'Suggested or not stated',count:skills.length-required-preferred}].filter(slice=>slice.count>0);
 // A ring with one slice says nothing the count beside it doesn't.
 if(!skills.length||slices.length<2)return null;
 let start=0;const gap=1.6;
 return <figure className="goal-ring" aria-label={`Priority of the ${skills.length} skills this role needs`}>
  <div className="goal-ring-chart"><svg viewBox="0 0 100 100" aria-hidden="true">{slices.map(slice=>{const length=slice.count/skills.length*100,offset=start;start+=length;return <circle key={slice.key} className={`slice-${slice.key}`} cx="50" cy="50" r="40" pathLength={100} strokeDasharray={`${Math.max(length-gap,.5)} ${100-Math.max(length-gap,.5)}`} strokeDashoffset={25-offset}/>;})}</svg><span><strong>{skills.length}</strong>{skills.length===1?'skill':'skills'}</span></div>
  <figcaption><p>Priority</p><ul>{slices.map(slice=><li key={slice.key}><i className={`slice-${slice.key}`} aria-hidden="true"/><b>{slice.count}</b> {slice.label}</li>)}</ul></figcaption>
 </figure>;
}
const dateKinds:Record<string,string>={application_deadline:'Apply by',interview:'Interview',job_start:'Starts'};
const tabs:{view:GoalView;href:string;label:string}[]=[{view:'skills',href:'/career-goal',label:'Skills needed'},{view:'interview',href:'/career-goal/interview',label:'Interview preparation'},{view:'role',href:'/career-goal/role',label:'About the role'}];
export function CareerGoalOverview({workspace,loadError='',onReload,view='skills'}:{workspace:CareerWorkspace;loadError?:string;onReload:()=>void;view?:GoalView}){
 const {token}=useProfile(),router=useRouter(),session=useCareerSession();
 const [retrying,setRetrying]=useState(false),[retryError,setRetryError]=useState('');
 const saved=workspace.current.goal!;
 const comparison=useComparison(token, `${saved._id}:${saved.version}`);
 const current=!(comparison.result?.inputs && (comparison.result.inputs.goal_id!==saved._id || comparison.result.inputs.goal_version!==saved.version));
 const matches=current?comparison.matches:null,outcomes=current?comparison.outcomes:null;
 const goal={...saved,summary:saved.summary||null,responsibilities:saved.responsibilities||[],non_skill_requirements:saved.non_skill_requirements||[]};
 const confirmationKey=`${token}:${goal._id}:${goal.version}:${workspace.current.selection_version}`;
 const working=processing.includes(workspace.phase);
 const comparing=!!comparison.current?.operation&&['pending','running'].includes(comparison.current.operation.status);
 const waitingText=workspace.phase==='waiting_quota'?`Research is waiting for the service allowance and will resume automatically${workspace.retry_after?` in about ${workspace.retry_after} seconds`:''}.`:'Researching opportunity information. Your extracted goal is already saved.';
 const processingSteps:ProcessingStep[]=[
  {label:'Read the job description',state:'done'},
  {label:'Listing the skills',state:goal.skills.length?'done':'now'},
  {label:'Researching the role',state:working&&goal.skills.length?'now':working?'next':'done',note:working?(workspace.phase==='waiting_quota'?'Waiting to resume':'Checking interviews and similar roles'):undefined},
  {label:'Rating your competence',state:matches?'done':comparing&&!working?'now':'next'},
 ];
 async function retryResearch(){if(!token||retrying)return;setRetrying(true);setRetryError('');try{await careerApi('/workspace/retry',token,{method:'POST'});onReload();}catch{setRetryError('Research could not be resumed. Please retry.');}finally{setRetrying(false);}}
 const facts:{icon:string;text:string}[]=[
  goal.company?{icon:'building',text:goal.company}:null,
  goal.employment_type&&goal.employment_type!=='unknown'?{icon:'brief',text:sentence(goal.employment_type.replaceAll('_',' '))}:null,
  goal.location?{icon:'pin',text:goal.location}:null,
  goal.target_type==='career_exploration'?{icon:'search',text:'Career exploration'}:null,
  ...(goal.job_dates??[]).filter(item=>item.date||item.text).map(item=>({icon:item.kind==='application_deadline'?'cal':'flag',text:`${dateKinds[item.kind]??sentence(item.kind.replaceAll('_',' '))} ${item.date?formatDate(item.date):item.text}`})),
 ].filter((fact):fact is {icon:string;text:string}=>Boolean(fact));
 const roleCards:RoleCardInput[]=[
  {card_id:'eligibility',title:'Eligibility and commitment',icon:'check',items:goal.non_skill_requirements.map(item=>({ref:`req:${item.requirement_id}`,text:item.description,note:originLabel(item),urls:item.source_urls}))},
  {card_id:'work',title:'What you would work on',icon:'code',items:[...(goal.summary?[{ref:'summary',text:goal.summary}]:[]),...goal.responsibilities.map((text,index)=>({ref:`resp:${index}`,text}))].map((item,index)=>index===0&&goal.job_url?{...item,urls:[goal.job_url]}:item)},
 ];
 const research=(section:'interview'|'role')=><OpportunityIntelligence key={`${goal._id}:${section}`} section={section} goalId={goal._id} version={goal.version} selectionVersion={workspace.current.selection_version} roleCards={section==='role'?roleCards:undefined}/>;
 return <section className={`page on goal-overview career-briefing${view==='role'?' is-wide':''}`}>
  <section className="briefing-target goal-header" id="target" aria-label="Your target role">
   <div className="briefing-target-copy"><p className="briefing-eyebrow">Working towards</p><h1>{goal.role}</h1>{facts.length>0&&<ul className="briefing-target-meta">{facts.map(fact=><li key={fact.text}><Icon name={fact.icon}/>{fact.text}</li>)}</ul>}</div>
   <div className="briefing-target-actions"><Link className="btn goal-header-btn" href="/career-goal/chat?refine=1">Refine goal</Link><button type="button" className="btn goal-header-btn" onClick={()=>{session.chooseJD(null);router.push('/career-goal?new=1');}}>Set a new goal</button></div>
   {view==='skills'&&<PriorityRing skills={goal.skills}/>}
  </section>
  <nav className="goal-tabs" aria-label="Career goal pages"><div className="goal-tab-group">{tabs.map(tab=><Link key={tab.view} href={tab.href} className={tab.view===view?'on':''} aria-current={tab.view===view?'page':undefined}>{tab.label}</Link>)}</div><span className="goal-saved">Saved automatically</span></nav>
  {loadError&&<div className="notice" role="alert">{loadError} <button className="btn ghost sm" onClick={onReload}>Retry loading goal</button></div>}
  {goal.requirements_need_review&&<p className="notice">Your role context changed. Refine your goal to review which requirements still apply.</p>}
  {working&&view!=='skills'&&<p className="notice" role="status">{waitingText}</p>}
  {view==='skills'&&(working||comparing)&&<ProcessingCard title="Skills needed" intro="elo is working out what this role needs and how your skills compare." progressLabel={working?'Working out the skills needed':'Rating your competence'} steps={processingSteps}
   footer={<p>{working&&workspace.phase==='waiting_quota'?waitingText:'You can leave this page. elo keeps working, and your skills will be here when it’s done.'}</p>}>{!goal.skills.length&&<SkeletonRows rows={4}/>}</ProcessingCard>}
  {workspace.phase==='research_failed'&&<div className="notice" role="alert"><p>Opportunity research could not finish. Your saved goal remains available.</p><button className="btn ghost sm" disabled={retrying} onClick={()=>void retryResearch()}>{retrying?'Resuming research…':'Retry research'}</button>{retryError&&<p>{retryError}</p>}</div>}
  {view==='skills'&&<>
   {!working&&!comparing&&<EvaluateBanner comparison={comparison} here="/career-goal"/>}
   <CvGoalConfirmationCard key={confirmationKey} goal={goal} selectionVersion={workspace.current.selection_version} token={token} onReload={onReload}/>
   <div className="briefing-grid briefing-grid-confirmed">
    <div className="briefing-learning"><LearningFocus key={`${goal._id}:${goal.version}`} skills={goal.skills} categories={workspace.current.skill_groups} matches={matches} outcomes={outcomes}/></div>
   </div>
  </>}
  {view!=='skills'&&research(view)}
 </section>;
}
