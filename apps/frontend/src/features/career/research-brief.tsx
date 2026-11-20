"use client";
import {createContext,useCallback,useContext,useEffect,useId,useMemo,useState,type ReactNode} from 'react';
import type {BriefReport,BriefSource,Citations,InterviewBrief,RoleBrief,Tone} from '@/lib/api/career';

export const VISIBLE_SOURCES=5;
const FLASH_MS=2000;

type CitationState={prefix:string;titles:Map<number,string>;expanded:boolean;setExpanded:(open:boolean)=>void;flash:number|null;reveal:(n:number)=>void};
const CitationContext=createContext<CitationState|null>(null);
const useCitations=()=>useContext(CitationContext);
const reducedMotion=()=>typeof window!=='undefined'&&!!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
export const sourceAnchor=(prefix:string,n:number)=>`${prefix}-src-${n}`;

/** Shares the source list between citation chips and the Sources panel: a chip expands the list, scrolls to its source and flashes it. */
export function CitationProvider({prefix,sources,children}:{prefix:string;sources:BriefSource[];children:ReactNode}){
 const [expanded,setExpanded]=useState(false),[flash,setFlash]=useState<number|null>(null),[target,setTarget]=useState<{n:number}|null>(null);
 const titles=useMemo(()=>new Map(sources.map(source=>[source.index,source.title])),[sources]);
 const reveal=useCallback((n:number)=>{if(n>VISIBLE_SOURCES)setExpanded(true);setTarget({n});},[]);
 useEffect(()=>{
  if(!target)return;
  const row=document.getElementById(sourceAnchor(prefix,target.n));
  if(!row)return;
  row.scrollIntoView({behavior:reducedMotion()?'auto':'smooth',block:'center'});
  row.querySelector('a')?.focus({preventScroll:true});
  setFlash(target.n);
  const timer=setTimeout(()=>setFlash(null),FLASH_MS);
  return()=>clearTimeout(timer);
 },[target,prefix]);
 const value=useMemo(()=>({prefix,titles,expanded,setExpanded,flash,reveal}),[prefix,titles,expanded,flash,reveal]);
 return <CitationContext.Provider value={value}>{children}</CitationContext.Provider>;
}

export function CitationChip({n}:{n:number}){
 const state=useCitations();
 const title=state?.titles.get(n);
 if(!state||!title)return null;
 return <a className="brief-cite" href={`#${sourceAnchor(state.prefix,n)}`} aria-label={`Source ${n}: ${title}`} title={title}
  onClick={event=>{event.preventDefault();state.reveal(n);}}>{n}</a>;
}

export const CitationChips=({citations}:{citations:Citations})=><>{citations.map(n=><CitationChip key={n} n={n}/>)}</>;

export const EstimatedTag=()=><span className="brief-tag is-estimated" title="An AI estimate, not from a source">Estimated</span>;
export const ConflictTag=()=><span className="brief-tag is-conflict">Conflicting reports</span>;

const toneLabels:Record<Tone,string>={positive:'Positive',mixed:'Mixed',negative:'Negative'};
export const SentimentPill=({tone}:{tone:Tone})=><span className={`brief-pill is-${tone}`}>{toneLabels[tone]}</span>;

export function Toggle({expanded,controls,onClick,children}:{expanded:boolean;controls:string;onClick:()=>void;children:ReactNode}){
 return <button type="button" className="brief-toggle" aria-expanded={expanded} aria-controls={controls} onClick={onClick}>{children}</button>;
}

export const SummaryLead=({children}:{children:ReactNode})=><p className="brief-lead">{children}</p>;

export function FactStrip({facts}:{facts:RoleBrief['facts']}){
 return <dl className="brief-strip" aria-label="Key facts">{facts.map(fact=><div key={fact.label} className="brief-cell">
  <dt>{fact.label}</dt>
  <dd className="brief-cell-value">{fact.value}</dd>
  <dd className="brief-cell-note">{fact.note}{fact.citations.length?<CitationChips citations={fact.citations}/>:<EstimatedTag/>}</dd>
 </div>)}</dl>;
}

export function ProcessStepper({steps}:{steps:InterviewBrief['process']}){
 return <ol className="brief-strip" aria-label="Interview process">{steps.map((step,index)=><li key={step.step} className="brief-cell">
  <span className="brief-step-when"><span className={`brief-step-dot${index===steps.length-1?' is-last':''}`} aria-hidden="true">{step.step}</span>
   <span className="brief-sr">Step {step.step}: </span>{step.when}</span>
  <span className="brief-cell-value">{step.title}</span>
  <span className="brief-cell-note">{step.detail}{step.citations.length?<CitationChips citations={step.citations}/>:<EstimatedTag/>}</span>
 </li>)}</ol>;
}

export function SectionPanel({id,title,description,tag,dashed=false,children}:{id:string;title:string;description?:ReactNode;tag?:ReactNode;dashed?:boolean;children:ReactNode}){
 return <section className={`brief-panel${dashed?' is-dashed':''}`} aria-labelledby={id}>
  <div className="brief-panel-head">
   <h3 id={id}>{title}</h3>
   {tag}
   {description&&<p>{description}</p>}
  </div>
  <div className="brief-panel-body">{children}</div>
 </section>;
}

export function EvidenceList({id,items}:{id?:string;items:BriefReport[]}){
 return <ul className="brief-evidence" id={id}>{items.map((item,index)=><li key={index}>{item.text}<CitationChips citations={item.citations}/></li>)}</ul>;
}

export function TopicCard({topic}:{topic:RoleBrief['topics'][number]}){
 const [open,setOpen]=useState(false),id=useId();
 const count=topic.reports.length;
 return <article className="brief-card brief-topic">
  <div className="brief-topic-head">
   <div>
    <h4>{topic.title}</h4>
    <p>{topic.takeaway}</p>
    {(topic.estimated||topic.conflicting)&&<p className="brief-tags">{topic.conflicting&&<ConflictTag/>}{topic.estimated&&<EstimatedTag/>}</p>}
   </div>
   <SentimentPill tone={topic.tone}/>
  </div>
  {count>0&&<Toggle expanded={open} controls={id} onClick={()=>setOpen(value=>!value)}>{open?'Hide reports':`Show ${count} report${count===1?'':'s'}`}</Toggle>}
  {count>0&&<div id={id} hidden={!open}><EvidenceList items={topic.reports}/></div>}
 </article>;
}

function PlusIcon(){
 return <svg className="brief-plus" aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 5v14M5 12h14"/></svg>;
}

/** Questions to practise; each opens to how to prepare. The first is open by default. */
export function QuestionAccordion({questions,markEach}:{questions:InterviewBrief['questions'];markEach:boolean}){
 const [open,setOpen]=useState<number|null>(0),id=useId();
 return <ul className="brief-cards">{questions.map((item,index)=>{const expanded=open===index,panel=`${id}-${index}`;
  return <li key={item.question} className={`brief-card brief-question${expanded?' is-open':''}`}>
   <h4><button type="button" aria-expanded={expanded} aria-controls={panel} onClick={()=>setOpen(expanded?null:index)}>
    <span>{item.question}{markEach&&item.estimated&&<EstimatedTag/>}</span><PlusIcon/>
   </button></h4>
   <div id={panel} className="brief-prep" hidden={!expanded}>
    <span>How to prepare</span>
    <p>{item.prep}</p>
   </div>
  </li>;})}</ul>;
}

const levels=['easy','average','difficult'] as const;
const levelLabels={easy:'Easy',average:'Average',difficult:'Difficult'};
export function DifficultyBar({difficulty}:{difficulty:NonNullable<InterviewBrief['difficulty']>}){
 return <section className="brief-difficulty" aria-label="Difficulty">
  <span className="brief-difficulty-label" aria-hidden="true">Difficulty</span>
  <span className="brief-segments" role="img" aria-label={`Difficulty: ${levelLabels[difficulty.level]}${difficulty.estimated?', estimated':''}`}>
   {levels.map(level=><span key={level} className={level===difficulty.level?'is-on':undefined}>{levelLabels[level]}</span>)}
  </span>
  {difficulty.estimated&&<EstimatedTag/>}
  <span className="brief-difficulty-reason">{difficulty.reason}</span>
 </section>;
}

function ExternalIcon(){
 return <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M7 17 17 7M8 7h9v9"/></svg>;
}

/** Sources numbered to match the citation chips, already sorted 1..N by the backend. */
export function SourceList({sources}:{sources:BriefSource[]}){
 const state=useCitations(),id=useId();
 const expanded=!!state?.expanded;
 const shown=expanded?sources:sources.slice(0,VISIBLE_SOURCES);
 return <>
  <ol className="brief-sources" id={id}>{shown.map(source=><li key={source.index} id={state?sourceAnchor(state.prefix,source.index):undefined} className={state?.flash===source.index?'is-flash':undefined}>
   <a href={source.url} target="_blank" rel="noopener noreferrer">
    <span className="brief-cite is-badge" aria-hidden="true">{source.index}</span>
    <span className="brief-source-title">{source.title}<span className="brief-sr"> (opens in a new tab)</span></span>
    <span className="brief-source-site">{source.domain}</span>
    <ExternalIcon/>
   </a>
  </li>)}</ol>
  {sources.length>VISIBLE_SOURCES&&<div className="brief-sources-more"><Toggle expanded={expanded} controls={id} onClick={()=>state?.setExpanded(!expanded)}>{expanded?'Show fewer sources':`Show all ${sources.length} sources`}</Toggle></div>}
 </>;
}
