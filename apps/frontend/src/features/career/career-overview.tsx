"use client";

import {useEffect,useId,useMemo,useRef,useState} from 'react';
import Link from 'next/link';
import {useRouter,useSearchParams} from 'next/navigation';
import {useProfile} from '@/features/profile/profile-provider';
import {careerApi,refreshWorkspace,type CareerWorkspace,type ReviewSkill} from '@/lib/api/career';
import {useCareerSession} from './career-session';
import {CareerGoal} from './career-goal';
import {OpportunityIntelligence,type RoleCardInput} from './opportunity-intelligence';
import {CvGoalConfirmationCard} from './cv-goal-confirmation';
import {sourceLink} from './source-links';
import {OTHER_SKILLS,groupSkills,type SkillGroupMap} from '@/lib/skill-groups';
import '@/styles/goal.css';
import '@/styles/workspace-pages.css';
import { announceInputsChanged, useComparison } from '@/features/assessment/comparison';
import { EvaluateBanner } from '@/features/assessment/evaluate-banner';
import { LEVEL_COLORS, LEVEL_LABELS, levelStatus, namesSkill, type LevelStatus } from '@/features/assessment/levels';
import { TalkItThrough, type TalkSkill } from '@/features/assessment/talk-it-through';
import { PageFlow } from '@/components/ui/page-flow';
import { loadRoadmap, loadSkills, useSection, type ProfileLevel } from '@/lib/api/workspace-summary';
import { ProcessingCard, SkeletonRows, type ProcessingStep } from '@/components/ui/processing-card';
import type { Requirement } from '@/features/roadmap/types';
import { formatDayMonthYear } from '@/lib/format';
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
 if(!workspace)return <section className="page on ws-page"><h1>Career Goal</h1>{error?<><p role="alert">{error}</p><button className="btn pri" onClick={()=>setAttempt(v=>v+1)}>Retry loading goal</button></>:<PageSkeleton label="Opening your career goal…"/>}</section>;
 if(!workspace.current?.goal)return <CareerGoal/>;
 return <CareerGoalOverview view={view} workspace={workspace} loadError={error} onReload={()=>setAttempt(v=>v+1)}/>;
}
function originLabel(item:{correction?:string;origin?:string}){
 return item.correction==='user'||item.origin==='user_declaration'?'Your refinement':item.origin==='generated_guidance'?'AI planning suggestion':item.origin==='market_research'?'From sampled job listings':'From the job description';
}
// Required and preferred skills are both Essential, so they rank together.
const priorityRank:Record<ReviewSkill['priority'],number>={required:0,preferred:0,unspecified:1,conflicting:2,suggested:3};
function RequirementSources({urls=[]}:{urls?:string[]}){
 const links=urls.map(sourceLink).filter(link=>link!==null);
 return links.length?<p>{links.map((link,i)=><a key={i} href={link.url} target="_blank" rel="noopener noreferrer">{link.domain} ↗ </a>)}</p>:null;
}
const sentence=(value:string)=>value.charAt(0).toUpperCase()+value.slice(1);

/** Importance in the page's words. Unstated importance that elo inferred is marked as inferred. */
type Importance='essential'|'nice'|'unclear';
const importanceLabels:Record<Importance,string>={essential:'Essential',nice:'Nice to have',unclear:'Conflicting requirements'};
const skillImportance=(skill:ReviewSkill):Importance=>skill.priority==='required'||skill.priority==='preferred'?'essential':skill.priority==='conflicting'?'unclear':'nice';
const inferredImportance=(skill:ReviewSkill)=>(skill.priority_origin??skill.origin)==='generated_guidance';
const tidy=(value:number)=>Math.round(value*10)/10;

/** A goal skill's level and the level the role needs, read from the saved evaluation. Nothing is scored here. */
export function goalSkillLevel(skill:ReviewSkill,outcome?:Requirement,profileLevels:ProfileLevel[]=[]):{level:number|null;target:number|null}{
 const target=outcome?.required_score??skill.competence_target?.level??null;
 // Older evaluations hold progress towards the target rather than the level itself.
 const evaluated=outcome?.demonstrated_score??(outcome?.competence_score!=null&&target!=null?tidy(outcome.competence_score*target/10):outcome?.competence_score??null);
 // A skill the evaluation has not rated still shows the level its Skills Profile entry already has.
 const profile=profileLevels.find(item=>namesSkill([item],{name:skill.name,canonicalId:skill.canonical_skill_id}))?.level;
 return {level:evaluated??profile??null,target};
}
type Row={skill:ReviewSkill;outcome?:Requirement;level:number|null;target:number|null;status:LevelStatus;key:string;pending:boolean};

/** Everything the evaluation and the goal hold about one skill; opened by "See evidence". */
function Evidence({row,evidence}:{row:Row;evidence?:Record<string,{name?:string;text:string}>}){
 const {skill,outcome}=row,importance=skillImportance(skill),inferred=inferredImportance(skill);
 const refs=[...new Set((outcome?.components??[]).flatMap(component=>component.evidence_refs))].map(ref=>evidence?.[ref]).filter((item):item is {name?:string;text:string}=>!!item).slice(0,4);
 const linked=outcome?.profile_skills??[];
 return <div className="ws-evidence">
  <div>
   <h4>Your evidence</h4>
   {outcome?.score_explanation?<p>{outcome.score_explanation}</p>:<p>{outcome?'elo found no evidence for this skill in your CV and review.':'Evaluate your skills to see the evidence elo used.'}</p>}
   {refs.map((item,index)=><blockquote key={index}>{item.name?<><b>{item.name}.</b> </>:null}{item.text}</blockquote>)}
   {outcome&&<><h4>From your Skills Profile</h4>{linked.length?<ul>{linked.map(item=><li key={item.canonical_skill_id||item.name}><Link href="/cv">{item.name}</Link>{item.competence_score!=null?` · ${item.competence_score} / 10`:''}</li>)}</ul>:<p>No skill in your Skills Profile covers this yet.</p>}</>}
  </div>
  <div>
   <h4>What the role expects</h4>
   {skill.context&&<p>{skill.context}</p>}
   <p>{importanceLabels[importance]}. {inferred?'The job description doesn’t say, so elo inferred this from the description and research.':skill.origin==='market_research'?'From sampled job listings.':skill.origin==='user_declaration'||skill.correction==='user'?'Set in your refinement.':'Stated in the job description.'}</p>
   {(skill.required_proficiency||skill.required_experience_months!=null)&&<p>{[skill.required_proficiency?`${sentence(skill.required_proficiency)} level expected`:null,skill.required_experience_months!=null?`${skill.required_experience_months} months’ experience`:null].filter(Boolean).join(' · ')}</p>}
   {skill.competence_target&&<><p>Target {skill.competence_target.level} / 10. {skill.competence_target.explanation}</p><RequirementSources urls={skill.competence_target.source_urls}/></>}
   {skill.group_id&&<p>{skill.group_operator==='any'?'Alternative requirement: one of the linked skills is needed.':'Part of a combined requirement.'}</p>}
   {skill.evidence&&skill.origin!=='employer'&&<blockquote>{skill.evidence}</blockquote>}
   <p>{originLabel(skill)}</p><RequirementSources urls={skill.source_urls}/>
   {!!skill.learning_items?.length&&<><h4>What to learn</h4><ul>{skill.learning_items.map(item=><li key={item.item_id}><b>{item.name}.</b> {item.reason}</li>)}</ul></>}
  </div>
 </div>;
}
function SkillRow({row,evidence,talk}:{row:Row;evidence?:Record<string,{name?:string;text:string}>;talk:(row:Row,mode:'talk'|'build')=>void}){
 const [open,setOpen]=useState(false),[showEvidence,setShowEvidence]=useState(false),id=useId();
 const {skill,level,target,status}=row,importance=importanceLabels[skillImportance(skill)];
 const short=level!=null&&target!=null?tidy(target-level):null;
 return <li className={`ws-skill${open?' open':''}${status==='unrated'?' unrated':''}`}>
  <button className="ws-sk-row" type="button" aria-expanded={open} aria-controls={id} onClick={()=>setOpen(value=>!value)}>
   <span className="ws-sk-name"><b>{skill.name}{row.pending&&<span className="ws-pending">In roadmap</span>}</b><span>{importance}{inferredImportance(skill)?' · inferred by elo':''}</span></span>
   {status==='unrated'
    ?<span className="ws-lvlbar" aria-hidden="true">{target!=null&&<span className="target" style={{left:`${target*10}%`}}/>}</span>
    :<span className="ws-lvlbar" role="img" aria-label={`${level} out of 10${target!=null?`, target ${target}`:''}`}><span className="fill" style={{width:`${level!*10}%`,background:LEVEL_COLORS[status]}}/>{target!=null&&<span className="target" style={{left:`${target*10}%`}}/>}</span>}
   <span className="ws-score">{status==='unrated'?'Not rated':<>{level} <small>/ {target??10}</small></>}</span>
   <svg className="ws-chev" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>
  </button>
  <div className="ws-sk-more" id={id} hidden={!open}>
   {status==='unrated'
    ?<p>{row.outcome?'elo didn’t find enough in your CV to rate this yet. Tell elo where you’ve used it and it will be rated.':'This skill hasn’t been compared with your Skills Profile yet.'}</p>
    :<p><b>{LEVEL_LABELS[status]}.</b> {status==='ready'?'You’ve met the target for this role.':short!=null?`${short} more to reach the target of ${target} for this ${importance.toLowerCase()} skill.`:'The role’s target for this skill isn’t set yet.'}</p>}
   <button className="ws-mini solid" type="button" onClick={()=>talk(row,'talk')}>{status==='unrated'?'Rate this skill':'Talk it through'}</button>
   <button className="ws-mini" type="button" aria-expanded={showEvidence} onClick={()=>setShowEvidence(value=>!value)}>{showEvidence?'Hide evidence':'See evidence'}</button>
   {status!=='ready'&&!row.pending&&<button className="ws-mini" type="button" onClick={()=>talk(row,'build')}>Add to roadmap</button>}
   {showEvidence&&<Evidence row={row} evidence={evidence}/>}
  </div>
 </li>;
}
const filters:{key:'all'|LevelStatus;label:string}[]=[{key:'all',label:'All'},{key:'ready',label:'Ready'},{key:'getting',label:'Getting there'},{key:'build',label:'To build'},{key:'unrated',label:'Not rated'}];
/** Every skill the goal needs, grouped by category, with the person's level against the role's target. */
export function SkillsNeeded({skills,categories,outcomes,profileLevels,evidence,pending=()=>false,talk=()=>{}}:{skills:ReviewSkill[];categories?:SkillGroupMap;outcomes?:Record<string,Requirement>|null;profileLevels?:ProfileLevel[];evidence?:Record<string,{name?:string;text:string}>;pending?:(skill:ReviewSkill)=>boolean;talk?:(row:Row,mode:'talk'|'build')=>void}){
 const [filter,setFilter]=useState<'all'|LevelStatus>('all');
 const rows=new Map<ReviewSkill,Row>(skills.map(skill=>{const outcome=skill.item_id?outcomes?.[skill.item_id]:undefined,{level,target}=goalSkillLevel(skill,outcome,profileLevels);return [skill,{skill,outcome,level,target,status:levelStatus(level,target),key:skill.item_id||skill.name,pending:pending(skill)}];}));
 const count=(key:'all'|LevelStatus)=>key==='all'?skills.length:[...rows.values()].filter(row=>row.status===key).length;
 const ordered=[...skills].sort((a,b)=>priorityRank[a.priority]-priorityRank[b.priority]).filter(skill=>filter==='all'||rows.get(skill)!.status===filter);
 const best=(items:ReviewSkill[])=>Math.min(...items.map(skill=>priorityRank[skill.priority]));
 const groups=groupSkills(ordered,skill=>skill.name,categories).sort((a,b)=>Number(a.name===OTHER_SKILLS)-Number(b.name===OTHER_SKILLS)||best(a.items)-best(b.items));
 return <section id="priorities" className="ws-panel" aria-labelledby="priorities-title">
  <h2 id="priorities-title">Skills needed</h2>
  <p className="ws-lead">Where you stand on each skill for this role. The tick marks the level the role needs. Open a skill and choose <b>Talk it through</b> to update your level or get a task that raises it.</p>
  {skills.length>0&&<>
   <div className="ws-filters" role="group" aria-label="Filter skills">{filters.map(item=><button key={item.key} className="ws-f" type="button" aria-pressed={filter===item.key} onClick={()=>setFilter(item.key)}>{item.key!=='all'&&<i style={{background:LEVEL_COLORS[item.key],border:item.key==='unrated'?'1.5px dashed var(--ws-muted)':undefined}} aria-hidden="true"/>}<b>{count(item.key)}</b> {item.label}</button>)}</div>
   <div className="ws-key" aria-hidden="true">
    <span><i className="ws-tick"/>Target for this role</span>
    {(['ready','getting','build'] as LevelStatus[]).map(status=><span key={status}><i style={{width:18,height:8,borderRadius:4,background:LEVEL_COLORS[status]}}/>{LEVEL_LABELS[status]}</span>)}
   </div>
   {groups.map(group=><section key={group.name} aria-label={group.name}><h3 className="ws-cat">{group.name}</h3><ul>{group.items.map(skill=><SkillRow key={rows.get(skill)!.key} row={rows.get(skill)!} evidence={evidence} talk={talk}/>)}</ul></section>)}
   {!groups.length&&<p className="ws-empty">No skills here yet. Keep working through your roadmap.</p>}
  </>}
  {!skills.length&&<p className="ws-empty">No skills are listed for this goal yet. Refine your goal to add or clarify them.</p>}
 </section>;
}
/** Part-to-whole of the goal's own priorities. Every slice is named and counted beside the ring. */
function PriorityRing({skills}:{skills:ReviewSkill[]}){
 const essential=skills.filter(skill=>skill.priority==='required'||skill.priority==='preferred').length;
 const slices=[{label:'Essential',count:essential,color:'#34D399'},{label:'Nice to have or not stated',count:skills.length-essential,color:'#64748B'}].filter(slice=>slice.count>0);
 if(!skills.length)return null;
 let start=0;
 return <div className="ws-ring-box">
  <svg width="132" height="132" viewBox="0 0 132 132" role="img" aria-label={`${skills.length} ${skills.length===1?'skill':'skills'}: ${slices.map(slice=>`${slice.count} ${slice.label.toLowerCase()}`).join(', ')}`}>
   <circle cx="66" cy="66" r="54" fill="none" stroke="rgba(255,255,255,.12)" strokeWidth="12"/>
   {slices.map(slice=>{const length=slice.count/skills.length*100,offset=start;start+=length;const shown=slices.length>1?Math.max(length-1.2,.5):100;return <circle key={slice.label} cx="66" cy="66" r="54" fill="none" stroke={slice.color} strokeWidth="12" pathLength={100} strokeDasharray={`${shown} ${100-shown}`} strokeDashoffset={-offset} transform="rotate(-90 66 66)"/>;})}
   <text x="66" y="66" textAnchor="middle" fontSize="34" fontWeight="700" fill="#fff">{skills.length}</text>
   <text x="66" y="88" textAnchor="middle" fontSize="13" fill="#CBD5E1">{skills.length===1?'skill':'skills'}</text>
  </svg>
  <div className="ws-ring-legend">{slices.map(slice=><span key={slice.label}><i style={{background:slice.color}} aria-hidden="true"/><b>{slice.count}</b>{slice.label}</span>)}</div>
 </div>;
}
const dateKinds:Record<string,string>={application_deadline:'Apply by',interview:'Interview',job_start:'Starts'};
const tabs:{view:GoalView;href:string;label:string}[]=[{view:'skills',href:'/career-goal',label:'Skills needed'},{view:'interview',href:'/career-goal/interview',label:'Interview preparation'},{view:'role',href:'/career-goal/role',label:'About the role'}];
export function CareerGoalOverview({workspace,loadError='',onReload,view='skills'}:{workspace:CareerWorkspace;loadError?:string;onReload:()=>void;view?:GoalView}){
 const {token}=useProfile(),router=useRouter(),session=useCareerSession();
 const [retrying,setRetrying]=useState(false),[retryError,setRetryError]=useState('');
 const [talking,setTalking]=useState<{key:string;mode:'talk'|'build'}|null>(null);
 const saved=workspace.current.goal!;
 const comparison=useComparison(token, `${saved._id}:${saved.version}`);
 const roadmap=useSection(loadRoadmap,token),profile=useSection(loadSkills,token);
 // A new or edited goal (such as a changed job description) makes earlier evaluations and roadmaps out of date.
 const savedRevision=useRef(`${saved._id}:${saved.version}`);
 useEffect(()=>{const revision=`${saved._id}:${saved.version}`;if(savedRevision.current!==revision){savedRevision.current=revision;announceInputsChanged();}},[saved._id,saved.version]);
 const current=!(comparison.result?.inputs && (comparison.result.inputs.goal_id!==saved._id || comparison.result.inputs.goal_version!==saved.version));
 const outcomes=current?comparison.outcomes:null;
 const goal={...saved,summary:saved.summary||null,responsibilities:saved.responsibilities||[],non_skill_requirements:saved.non_skill_requirements||[]};
 const confirmationKey=`${token}:${goal._id}:${goal.version}:${workspace.current.selection_version}`;
 const working=processing.includes(workspace.phase);
 const waitingText=workspace.phase==='waiting_quota'?`Research is waiting for the service allowance and will resume automatically${workspace.retry_after?` in about ${workspace.retry_after} seconds`:''}.`:'Researching opportunity information. Your extracted goal is already saved.';
 const processingSteps:ProcessingStep[]=[
  {label:'Read the job description',state:'done'},
  {label:'Listing the skills',state:goal.skills.length?'done':'now'},
  {label:'Researching the role',state:goal.skills.length?'now':'next',note:workspace.phase==='waiting_quota'?'Waiting to resume':'Checking interviews and similar roles'},
  {label:'Rating your competence',state:'next'},
 ];
 async function retryResearch(){if(!token||retrying)return;setRetrying(true);setRetryError('');try{await careerApi('/workspace/retry',token,{method:'POST'});onReload();}catch{setRetryError('Research could not be resumed. Please retry.');}finally{setRetrying(false);}}
 const facts=[
  goal.company,
  goal.employment_type&&goal.employment_type!=='unknown'?sentence(goal.employment_type.replaceAll('_',' ')):null,
  goal.location,
  goal.target_type==='career_exploration'?'Career exploration':null,
  ...(goal.job_dates??[]).filter(item=>item.date||item.text).map(item=>`${dateKinds[item.kind]??sentence(item.kind.replaceAll('_',' '))} ${item.date?formatDayMonthYear(item.date):item.text}`),
 ].filter((fact):fact is string=>Boolean(fact));
 // A roadmap that runs past the job's start date can't prepare the person in time.
 const planner=roadmap.state.status==='ready'?roadmap.state.data.planner:null;
 const jobStart=goal.job_dates?.find(item=>item.kind==='job_start'&&item.date)?.date,roadmapEnd=planner?.config.target_date;
 const lateRoadmap=jobStart&&roadmapEnd&&roadmapEnd>jobStart?roadmapEnd:null;
 const scheduled=useMemo(()=>(planner?.active_sessions??[]).filter(item=>item.status==='scheduled'),[planner]);
 const pending=(skill:ReviewSkill)=>scheduled.some(item=>item.origin==='user'&&namesSkill(item.skills,{name:skill.name,canonicalId:skill.canonical_skill_id}));
 const goalLabel=[goal.role,goal.company].filter(Boolean).join(' at ');
 const profileLevels=profile.state.status==='ready'?profile.state.data.levels:undefined;
 const talkSkill=useMemo(():TalkSkill|null=>{
  const skill=talking&&goal.skills.find(item=>(item.item_id||item.name)===talking.key);
  if(!skill)return null;
  const {level,target}=goalSkillLevel(skill,skill.item_id?outcomes?.[skill.item_id]:undefined,profileLevels);
  return {key:`${talking!.key}:${talking!.mode}`,name:skill.name,canonicalId:skill.canonical_skill_id,level,target,meaning:skill.competence_target?.explanation,tasks:(skill.learning_items??[]).map(item=>({name:item.name,reason:item.reason}))};
 },[talking,goal.skills,outcomes,profileLevels]);
 const roleCards:RoleCardInput[]=[
  {card_id:'eligibility',title:'Eligibility and commitment',icon:'check',items:goal.non_skill_requirements.map(item=>({ref:`req:${item.requirement_id}`,text:item.description,note:originLabel(item),urls:item.source_urls}))},
  {card_id:'work',title:'What you would work on',icon:'code',items:[...(goal.summary?[{ref:'summary',text:goal.summary}]:[]),...goal.responsibilities.map((text,index)=>({ref:`resp:${index}`,text}))].map((item,index)=>index===0&&goal.job_url?{...item,urls:[goal.job_url]}:item)},
 ];
 const research=(section:'interview'|'role')=><OpportunityIntelligence key={`${goal._id}:${section}`} section={section} goalId={goal._id} version={goal.version} selectionVersion={workspace.current.selection_version} roleCards={section==='role'?roleCards:undefined}/>;
 return <section className={`page on ws-page goal-overview career-briefing${view==='role'?' is-wide':''}`}>
  <section className="ws-hero ws-goal" id="target" aria-label="Your target role">
   <div>
    <div className="ws-eyebrow">Working towards</div>
    <h1>{goal.role}</h1>
    {(facts.length>0||lateRoadmap)&&<ul className="ws-meta">{facts.map(fact=><li key={fact} className="ws-chip">{fact}</li>)}{lateRoadmap&&<li><Link className="ws-chip warn" href="/roadmap">Your roadmap ends {formatDayMonthYear(lateRoadmap)}. Match the dates</Link></li>}</ul>}
    <div className="ws-actions"><Link className="ws-btn ghost" href="/career-goal/chat?refine=1">Refine goal</Link><button type="button" className="ws-btn ghost" onClick={()=>{session.chooseJD(null);router.push('/career-goal?new=1');}}>Set a new goal</button></div>
   </div>
   {view==='skills'&&<PriorityRing skills={goal.skills}/>}
  </section>
  <PageFlow current="/career-goal">Your goal decides which skills matter and what level to aim for. Change it, and your Skills Profile targets and Roadmap update to match.</PageFlow>
  <div className="ws-row"><nav className="ws-tabs" aria-label="Career goal pages">{tabs.map(tab=><Link key={tab.view} href={tab.href} className={tab.view===view?'on':undefined} aria-current={tab.view===view?'page':undefined}>{tab.label}</Link>)}</nav><span className="ws-saved">Saved automatically</span></div>
  {loadError&&<div className="notice" role="alert">{loadError} <button className="btn ghost sm" onClick={onReload}>Retry loading goal</button></div>}
  {goal.requirements_need_review&&<p className="notice">Your role context changed. Refine your goal to review which requirements still apply.</p>}
  {working&&view!=='skills'&&<p className="notice" role="status">{waitingText}</p>}
  {view==='skills'&&working&&<ProcessingCard title="Skills needed" intro="elo is working out what this role needs and how your skills compare." progressLabel="Working out the skills needed" steps={processingSteps}
   footer={<p>{workspace.phase==='waiting_quota'?waitingText:'You can leave this page. elo keeps working, and your skills will be here when it’s done.'}</p>}>{!goal.skills.length&&<SkeletonRows rows={4}/>}</ProcessingCard>}
  {workspace.phase==='research_failed'&&<div className="notice" role="alert"><p>Opportunity research could not finish. Your saved goal remains available.</p><button className="btn ghost sm" disabled={retrying} onClick={()=>void retryResearch()}>{retrying?'Resuming research…':'Retry research'}</button>{retryError&&<p>{retryError}</p>}</div>}
  {view==='skills'&&<>
   {!working&&<EvaluateBanner comparison={comparison} here="/career-goal"/>}
   <CvGoalConfirmationCard pill key={confirmationKey} goal={goal} selectionVersion={workspace.current.selection_version} token={token} onReload={onReload}/>
   <SkillsNeeded key={`${goal._id}:${goal.version}`} skills={goal.skills} categories={workspace.current.skill_groups} outcomes={outcomes} profileLevels={profileLevels} evidence={current?comparison.result?.evidence:undefined} pending={pending} talk={(row,mode)=>setTalking({key:row.key,mode})}/>
   <TalkItThrough skill={talkSkill} mode={talking?.mode} onClose={()=>setTalking(null)} token={token} goalLabel={goalLabel} comparison={comparison} onRoadmapChanged={roadmap.retry}/>
  </>}
  {view!=='skills'&&research(view)}
 </section>;
}
