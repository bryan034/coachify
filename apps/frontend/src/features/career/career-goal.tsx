"use client";

import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { useRouter } from 'next/navigation';
import { useCareerSession } from './career-session';
import { Icon } from '@/components/ui/icon';
import { useProfile } from '@/features/profile/profile-provider';
import { importCareer, type CareerPreview } from '@/lib/api/career';

const methods = [
 { id: 'text', label: 'Paste description', icon: 'doc', hint: 'Bring the opportunity into focus.', detail: 'Copy the complete description from one job listing, including responsibilities and requirements.' },
 { id: 'url', label: 'Job URL', icon: 'link', hint: 'Start with the link.', detail: 'Import a public job page, then check and edit its description. Some websites block automated access.' },
 { id: 'document', label: 'Upload document', icon: 'up', hint: 'Have the description in a file?', detail: 'Choose a PDF, DOCX or UTF-8 TXT file. We’ll prepare an editable preview for you.' },
] as const;
type Method = typeof methods[number]['id'];
type Draft = { text: string; preview?: CareerPreview };
const MAX_TEXT = 8_000, MAX_FILE = 10 * 1024 * 1024;
const empty = (): Record<Method,Draft> => ({text:{text:''},url:{text:''},document:{text:''}});
export function CareerGoal({replacing=false}:{replacing?:boolean}={}) {
 const { token } = useProfile();
 const router=useRouter();const {jd,chooseJD}=useCareerSession();
 useEffect(()=>{if(new URLSearchParams(window.location.search).get('explore')==='1')router.replace('/career-goal/chat');},[router]);
 const [method,setMethod] = useState<Method>('text');
 const [drafts,setDrafts] = useState(()=>{const values=empty();if(jd)values.text={text:jd.text};return values;});
 const [url,setUrl] = useState(''); const [file,setFile] = useState<File>();
 const [error,setError] = useState(''); const [busy,setBusy] = useState(false);
 const controller = useRef<AbortController | null>(null); const request = useRef(0); const input = useRef<HTMLInputElement>(null);
 const active = methods.find(m=>m.id===method)!; const draft=drafts[method];
 const count=Array.from(draft.text).length; const tooLong=count>MAX_TEXT;
 const hasWork=Boolean(url||file||Object.values(drafts).some(d=>d.text));
 const work = useRef(hasWork); work.current=hasWork;
 useEffect(()=>()=>{request.current++;controller.current?.abort();},[]);
 useEffect(()=>{
  const warning='Your Career Goal preview is temporary. Leave this page and discard it?';
  function unload(event:BeforeUnloadEvent){if(work.current){event.preventDefault();event.returnValue='';}}
  function link(event:MouseEvent){
   const anchor=(event.target as Element | null)?.closest?.('a[href]');
   if(!work.current||!anchor||event.defaultPrevented||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
   const target=new URL(anchor.getAttribute('href')!,location.href);
   if(target.origin===location.origin&&target.pathname===location.pathname)return;
   if(!window.confirm(warning)){event.preventDefault();event.stopImmediatePropagation();}
  }
  window.addEventListener('beforeunload',unload);document.addEventListener('click',link,true);
  return()=>{window.removeEventListener('beforeunload',unload);document.removeEventListener('click',link,true);};
 },[]);
 function changeMethod(next:Method){request.current++;controller.current?.abort();setBusy(false);setError('');setMethod(next);}
 function keyboard(event:KeyboardEvent<HTMLButtonElement>,index:number){
  const move=event.key==='ArrowRight'?(index+1)%3:event.key==='ArrowLeft'?(index+2)%3:event.key==='Home'?0:event.key==='End'?2:null;
  if(move===null)return;event.preventDefault();changeMethod(methods[move].id);document.getElementById(`goal-tab-${methods[move].id}`)?.focus();
 }
 function update(text:string){setDrafts(previous=>({...previous,[method]:{...previous[method],text}}));}
 async function startImport(event?:FormEvent,selectedFile?:File){
  event?.preventDefault();if(method==='text'||(busy&&!selectedFile))return;setError('');
  const readingFile=selectedFile||file;
  if(!token){setError('Sign in again to import a description.');return;}
  if(method==='document'&&(!readingFile||!readingFile.size||readingFile.size>MAX_FILE)){setError('Choose a non-empty PDF, DOCX or TXT file up to 10 MiB.');return;}
  if(draft.text&&!window.confirm('Replace this temporary preview? Your edits to this preview will be discarded.'))return;
  const target=method, sequence=++request.current;controller.current?.abort();const abort=new AbortController();controller.current=abort;setBusy(true);
  try{
   let body:string|FormData=JSON.stringify({url});
   if(target==='document'){const form=new FormData();form.set('file',readingFile!);body=form;}
   const preview=await importCareer(target,body,token,abort.signal);
   if(sequence!==request.current)return;
   setDrafts(previous=>({...previous,[target]:{text:preview.text,preview}}));
  }catch(cause){if(sequence===request.current&&!abort.signal.aborted)setError(cause instanceof Error?cause.message:'Could not import this source. Please retry.');}
  finally{if(sequence===request.current)setBusy(false);}
 }
 function clear(){if(hasWork&&!window.confirm('Clear this temporary input and preview?'))return;request.current++;controller.current?.abort();setBusy(false);setError('');setDrafts(p=>({...p,[method]:{text:''}}));if(method==='url')setUrl('');if(method==='document'){setFile(undefined);if(input.current)input.current.value='';}}
 return <section className="page on career-goal">
  <div className="ptitle"><div><p className="small">Your direction, your next step</p><h1>Career Goal</h1></div><span className="chip"><Icon name="brief"/>Find your starting point</span></div>
  {!replacing&&<div className="row"><button className="btn ghost" onClick={()=>router.push('/career-goal/chat')}>Continue career conversation</button></div>}
  {<div className="goal-explore-entry"><span>Still deciding on a role?</span><button type="button" className="btn pri" onClick={()=>{chooseJD(null);router.push('/career-goal/discovery');}}>Explore careers ↗</button></div>}
  <div className="card goal-intro"><div className="tag tone-book"><Icon name="brief"/></div><div><h2>A role to work towards.</h2><p className="small">Bring a job description that interests you. Start with its text, a link or a document. Only career-goal setting is supported.</p></div><span className="pill n">Input preview</span></div>
  <div className="goal-grid"><div className="card goal-editor">
   <div className="goal-tabs" role="tablist" aria-label="Job description input method">{methods.map((item,index)=><button key={item.id} id={`goal-tab-${item.id}`} type="button" role="tab" aria-selected={method===item.id} aria-controls="goal-panel" tabIndex={method===item.id?0:-1} onKeyDown={event=>keyboard(event,index)} onClick={()=>changeMethod(item.id)}><Icon name={item.icon}/>{item.label}</button>)}</div>
   <div id="goal-panel" role="tabpanel" aria-labelledby={`goal-tab-${method}`} className="goal-panel">
    <h2>{active.hint}</h2><p className="small goal-help">{active.detail}</p>
    {method!=='text'&&<form className="goal-import" onSubmit={startImport}>
     {method==='url'?<><label htmlFor="job-url">Job description URL</label><input id="job-url" type="url" maxLength={2048} placeholder="https://company.com/careers/your-next-role" value={url} onChange={event=>setUrl(event.target.value)} disabled={busy} required/><p className="small">Public HTTP/HTTPS pages only. We won’t sign into websites or bypass access restrictions.</p></>:<><label htmlFor="job-document">Job description document</label><input ref={input} id="job-document" type="file" accept=".pdf,.docx,.txt" disabled={busy} onChange={event=>{const next=event.target.files?.[0];setFile(next);setError('');if(next)void startImport(undefined,next);}}/><p className="small">PDF, DOCX or UTF-8 TXT · Up to 10 MiB · Scanned PDFs need a text alternative.</p>{file&&<p className="small goal-filename">Selected: {file.name}</p>}</>}
     {(method==='url'||!!error)&&<button className="btn pri" disabled={busy||(method==='url'?!url:!file)}>{busy?'Preparing preview…':method==='url'?'Import job page':'Retry reading document'}<span aria-hidden="true">↗</span></button>}
    </form>}
    {busy&&<p role="status" className="goal-status">Preparing a temporary preview. You can switch methods to cancel.</p>}
    {error&&<div role="alert" className="goal-error"><p>{error}</p><p className="small">Your current input is still here. Retry, paste the description or choose another source.</p></div>}
    {(method==='text'||draft.text)&&<div className="goal-preview">

     <div className="row between"><label htmlFor="job-description">{method==='text'?'Job description':'Review and edit the preview'}</label><span id="goal-count" className={`small ${tooLong?'error':''}`}>{count.toLocaleString()} / 8,000 characters</span></div>
     <textarea id="job-description" rows={16} placeholder={'Paste one complete job description here…\n\nInclude the responsibilities, skills and qualifications stated in the listing.'} value={draft.text} onChange={event=>update(event.target.value)} aria-describedby="goal-count goal-input-note" aria-invalid={tooLong} spellCheck={false}/>
     <p id="goal-input-note" className="small">{tooLong?'This description exceeds 8,000 characters. Shorten it before using it in a future analysis; your text has not been cut off.':'Keep the original wording, bullet points and line breaks. Review imported content for missing or unrelated sections.'}</p>
     {draft.preview?.notices.map((notice,index)=><p key={index} className="small goal-notice">{notice}</p>)}
    </div>}
    <div className="row between goal-actions"><button type="button" className="btn ghost sm" disabled={!draft.text&&!(method==='url'?url:method==='document'?file:false)} onClick={clear}>Clear input</button><button type="button" className="btn pri" disabled={!draft.text.trim()||tooLong||busy} onClick={()=>{chooseJD({text:draft.text,kind:method,name:draft.preview?.source_name||'Pasted job description',url:draft.preview?.source_url});router.push('/career-goal/chat?source=jd');}}>Extract career goal <span aria-hidden="true">↗</span></button></div>
   </div>
  </div><aside className="goal-guide">
   <div className="card pad"><p className="k">A little guidance</p><h3>One opportunity at a time.</h3><p className="small">Use a complete description for one role. A title or link alone won’t tell the full story.</p><div className="goal-guide-step"><span>01</span><div><strong>Bring the description</strong><p className="small">Choose the input that works for you.</p></div></div><div className="goal-guide-step"><span>02</span><div><strong>Check the details</strong><p className="small">Review the text and remove unrelated content.</p></div></div><div className="goal-guide-step"><span>03</span><div><strong>Understand the role</strong><p className="small">Extract the role’s skills, then review them with your career agent.</p></div></div></div>
   <div className="goal-temporary"><Icon name="doc"/><div><strong>Just a temporary preview</strong><p className="small">Your description stays temporary. Extract career goal sends it to the configured AI provider and saves a structured review. A successfully extracted goal is saved automatically and replaces your current goal. Refreshing discards temporary inputs.</p></div></div>
  </aside></div>
 </section>;
}
