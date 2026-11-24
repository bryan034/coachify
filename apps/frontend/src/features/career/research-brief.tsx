"use client";
import {createContext,useCallback,useContext,useEffect,useId,useMemo,useState,type ReactNode} from 'react';
import type {BriefSource,Citations} from '@/lib/api/career';
import {sourceLink} from './source-links';

export const VISIBLE_SOURCES=5;
const FLASH_MS=2000;

type CitationState={prefix:string;titles:Map<number,string>;expanded:boolean;setExpanded:(open:boolean)=>void;flash:number|null;reveal:(n:number)=>void};
const CitationContext=createContext<CitationState|null>(null);
const useCitations=()=>useContext(CitationContext);
const reducedMotion=()=>typeof window!=='undefined'&&!!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
export const sourceAnchor=(prefix:string,n:number)=>`${prefix}-src-${n}`;

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

export function Toggle({expanded,controls,onClick,children}:{expanded:boolean;controls:string;onClick:()=>void;children:ReactNode}){
 return <button type="button" className="brief-toggle" aria-expanded={expanded} aria-controls={controls} onClick={onClick}>{children}</button>;
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

function ExternalIcon(){
 return <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M7 17 17 7M8 7h9v9"/></svg>;
}

export function SourceList({sources}:{sources:BriefSource[]}){
 const state=useCitations(),id=useId();
 const expanded=!!state?.expanded;
 const shown=expanded?sources:sources.slice(0,VISIBLE_SOURCES);
 return <>
  <ol className="brief-sources" id={id}>{shown.map(source=><li key={source.index} id={state?sourceAnchor(state.prefix,source.index):undefined} className={state?.flash===source.index?'is-flash':undefined}>
   <a href={sourceLink(source.url)?.url} target="_blank" rel="noopener noreferrer">
    <span className="brief-cite is-badge" aria-hidden="true">{source.index}</span>
    <span className="brief-source-title">{source.title}<span className="brief-sr"> (opens in a new tab)</span></span>
    <span className="brief-source-site">{source.domain}</span>
    <ExternalIcon/>
   </a>
  </li>)}</ol>
  {sources.length>VISIBLE_SOURCES&&<div className="brief-sources-more"><Toggle expanded={expanded} controls={id} onClick={()=>state?.setExpanded(!expanded)}>{expanded?'Show fewer sources':`Show all ${sources.length} sources`}</Toggle></div>}
 </>;
}
