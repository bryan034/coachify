import {act,fireEvent,render,screen} from '@testing-library/react';
import {expect,it,vi} from 'vitest';
import {ChatScrollControl,useChatScroll} from './use-chat-scroll';

it('preserves the reading position during new content and follows again only after returning to latest',()=>{
 let height=1000;
 const scroll=vi.fn();
 function Chat({text}:{text:string}){
  const {transcript,scrollProps,showJump,jumpToLatest}=useChatScroll();
  return <><div role="log" ref={transcript} {...scrollProps}>{text}</div><ChatScrollControl visible={showJump} onClick={jumpToLatest}/></>;
 }
 const view=render(<Chat text="Initial reply"/>),log=screen.getByRole('log');
 Object.defineProperties(log,{scrollHeight:{get:()=>height},clientHeight:{value:300},scrollTop:{value:700,writable:true},scrollTo:{value:scroll}});
 view.rerender(<Chat text="More words"/>);
 expect(scroll).toHaveBeenLastCalledWith({top:1000,behavior:'instant'});
 fireEvent.wheel(log,{deltaY:-100});log.scrollTop=400;fireEvent.scroll(log);scroll.mockClear();
 height=1200;view.rerender(<Chat text="New words and research status"/>);
 expect(scroll).not.toHaveBeenCalled();expect(log.scrollTop).toBe(400);
 fireEvent.click(screen.getByRole('button',{name:/Jump to latest/}));
 expect(scroll).toHaveBeenLastCalledWith({top:1200,behavior:'instant'});
 expect(screen.queryByRole('button',{name:/Jump to latest/})).toBeNull();
 height=1400;view.rerender(<Chat text="Another word"/>);
 expect(scroll).toHaveBeenLastCalledWith({top:1400,behavior:'instant'});
 // Native touch/scrollbar movement also pauses following.
 log.scrollTop=300;fireEvent.scroll(log);scroll.mockClear();
 act(()=>{height=1600;});view.rerender(<Chat text="Next reply"/>);
 expect(scroll).not.toHaveBeenCalled();
 log.scrollTop=1300;fireEvent.scroll(log);height=1700;view.rerender(<Chat text="Latest"/>);
 expect(scroll).toHaveBeenLastCalledWith({top:1700,behavior:'instant'});
});
