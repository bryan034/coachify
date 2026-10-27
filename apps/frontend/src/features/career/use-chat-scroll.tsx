"use client";
import {useCallback,useLayoutEffect,useRef,useState} from 'react';

/** Follow new text until the reader scrolls away; content changes never re-enable it. */
export function useChatScroll(){
 const transcript=useRef<HTMLDivElement|null>(null),following=useRef(true);
 const [showJump,setShowJump]=useState(false);
 const followReply=useCallback(()=>{
  const log=transcript.current;if(!log)return;
  if(following.current)log.scrollTo?.({top:log.scrollHeight,behavior:'instant'});
  else setShowJump(log.scrollHeight-log.scrollTop-log.clientHeight>4);
 },[]);
 const onScroll=useCallback(()=>{
  const log=transcript.current;if(!log)return;
  following.current=log.scrollHeight-log.scrollTop-log.clientHeight<=4;
  setShowJump(!following.current);
 },[]);
 const pause=useCallback(()=>{following.current=false;},[]);
 const jumpToLatest=useCallback(()=>{following.current=true;setShowJump(false);followReply();},[followReply]);
 useLayoutEffect(()=>{followReply();});
 return {transcript,followReply,showJump,jumpToLatest,scrollProps:{
  onScroll,onWheel:(event:React.WheelEvent)=>{if(event.deltaY<0)pause();},
  onKeyDown:(event:React.KeyboardEvent)=>{if(['ArrowUp','PageUp','Home'].includes(event.key))pause();},
  tabIndex:0,
 }};
}
export function ChatScrollControl({visible,onClick}:{visible:boolean;onClick:()=>void}){
 return visible?<div className="agent-scroll-controls"><button type="button" className="btn ghost sm" onClick={onClick}>↓ Jump to latest</button></div>:null;
}
