import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CareerGoal } from './career-goal';
import { importCareer } from '@/lib/api/career';
vi.mock('@/features/profile/profile-provider',()=>({useProfile:()=>({token:'synthetic-session'})}));
vi.mock('@/lib/api/career',()=>({importCareer:vi.fn()}));
vi.mock('@/lib/api/career-targets',()=>({targetApi:{list:vi.fn().mockResolvedValue({targets:[],selected_target:null,next_cursor:null,selection:{career_target_id:null,career_target_version:null,version:0}})}}));
afterEach(()=>vi.restoreAllMocks());
const preview={kind:'url' as const,text:'Analyst\n• SQL or Python',source_name:'Synthetic Jobs',source_url:'https://example.test/job',notices:['Check for missing content.']};

describe('temporary Career Goal inputs',()=>{
 it('preserves pasted Unicode and whitespace, never submits or stores it, and retains it between tabs',()=>{
  const storage=vi.spyOn(Storage.prototype,'setItem');
  render(<CareerGoal/>);
  const text='  Analyst 🧭\n\n• SQL or Python\n';
  fireEvent.change(screen.getByRole('textbox',{name:'Job description'}),{target:{value:text}});
  expect(screen.getByRole('textbox',{name:'Job description'})).toHaveValue(text);
  fireEvent.click(screen.getByRole('tab',{name:'Job URL'}));
  fireEvent.click(screen.getByRole('tab',{name:'Paste description'}));
  expect(screen.getByRole('textbox',{name:'Job description'})).toHaveValue(text);
  expect(importCareer).not.toHaveBeenCalled();expect(storage).not.toHaveBeenCalled();
  expect(screen.getByText('Nothing is saved yet')).toBeVisible();
 });
 it('counts Unicode characters and retains over-limit input instead of truncating it',()=>{
  render(<CareerGoal/>);
  fireEvent.change(screen.getByRole('textbox',{name:'Job description'}),{target:{value:'🧭'.repeat(20_001)}});
  expect(screen.getByRole('textbox',{name:'Job description'})).toHaveAttribute('aria-invalid','true');
  expect(screen.getByText('20,001 / 20,000 characters')).toBeVisible();
  expect(screen.getByRole('textbox',{name:'Job description'})).toHaveValue('🧭'.repeat(20_001));
 });
 it('imports an editable URL preview and keeps it through a failed replacement',async()=>{
  vi.mocked(importCareer).mockResolvedValueOnce(preview).mockRejectedValueOnce(new Error('This site blocks automated access.'));
  vi.spyOn(window,'confirm').mockReturnValue(true);
  render(<CareerGoal/>);fireEvent.click(screen.getByRole('tab',{name:'Job URL'}));
  fireEvent.change(screen.getByLabelText('Job description URL'),{target:{value:preview.source_url}});
  fireEvent.click(screen.getByRole('button',{name:'Import job page'}));
  await screen.findByRole('textbox',{name:'Review and edit the preview'});
  fireEvent.change(screen.getByRole('textbox',{name:'Review and edit the preview'}),{target:{value:'My edited preview'}});
  fireEvent.click(screen.getByRole('button',{name:'Import job page'}));
  expect(await screen.findByRole('alert')).toHaveTextContent('blocks automated access');
  expect(screen.getByRole('textbox',{name:'Review and edit the preview'})).toHaveValue('My edited preview');
 });
 it('rejects empty or oversized files before an API call',async()=>{
  vi.mocked(importCareer).mockClear();render(<CareerGoal/>);fireEvent.click(screen.getByRole('tab',{name:'Upload document'}));
  fireEvent.change(screen.getByLabelText('Job description document'),{target:{files:[new File([],'empty.txt',{type:'text/plain'})]}});
  fireEvent.click(screen.getByRole('button',{name:'Read document'}));
  expect(await screen.findByRole('alert')).toHaveTextContent('non-empty');
  fireEvent.change(screen.getByLabelText('Job description document'),{target:{files:[new File([new Uint8Array(10*1024*1024+1)],'large.txt',{type:'text/plain'})]}});
  fireEvent.click(screen.getByRole('button',{name:'Read document'}));
  expect(screen.getByRole('alert')).toHaveTextContent('10 MiB');expect(importCareer).not.toHaveBeenCalled();
 });
 it('submits documents as multipart form data and shows the returned preview',async()=>{
  vi.mocked(importCareer).mockResolvedValue({...preview,kind:'document',source_name:'role.txt'});
  render(<CareerGoal/>);fireEvent.click(screen.getByRole('tab',{name:'Upload document'}));
  const file=new File(['Analyst\nSQL'],'role.txt',{type:'text/plain'});
  fireEvent.change(screen.getByLabelText('Job description document'),{target:{files:[file]}});
  fireEvent.click(screen.getByRole('button',{name:'Read document'}));
  await screen.findByRole('textbox',{name:'Review and edit the preview'});
  const args=vi.mocked(importCareer).mock.calls.at(-1)!;expect(args[0]).toBe('document');expect((args[1] as FormData).get('file')).toBe(file);
 });
 it('ignores a late import response after switching methods',async()=>{
  let resolve!:(value:typeof preview)=>void;
  vi.mocked(importCareer).mockImplementation(()=>new Promise(r=>{resolve=r;}));
  render(<CareerGoal/>);fireEvent.click(screen.getByRole('tab',{name:'Job URL'}));
  fireEvent.change(screen.getByLabelText('Job description URL'),{target:{value:preview.source_url}});
  fireEvent.click(screen.getByRole('button',{name:'Import job page'}));
  fireEvent.click(screen.getByRole('tab',{name:'Paste description'}));resolve(preview);
  await waitFor(()=>expect(screen.getByRole('textbox',{name:'Job description'})).toHaveValue(''));
  fireEvent.click(screen.getByRole('tab',{name:'Job URL'}));expect(screen.queryByRole('textbox',{name:'Review and edit the preview'})).not.toBeInTheDocument();
 });
 it('supports keyboard tabs and confirms before clearing or following navigation',()=>{
  vi.spyOn(window,'confirm').mockReturnValue(false);
  render(<><a href="/dashboard">Home</a><CareerGoal/></>);
  fireEvent.keyDown(screen.getByRole('tab',{name:'Paste description'}),{key:'ArrowRight'});
  expect(screen.getByRole('tab',{name:'Job URL'})).toHaveFocus();
  fireEvent.click(screen.getByRole('tab',{name:'Paste description'}));
  fireEvent.change(screen.getByRole('textbox',{name:'Job description'}),{target:{value:'Temporary role'}});
  fireEvent.click(screen.getByRole('button',{name:'Clear input'}));
  expect(screen.getByRole('textbox',{name:'Job description'})).toHaveValue('Temporary role');
  fireEvent.click(screen.getByRole('link',{name:'Home'}));expect(window.confirm).toHaveBeenCalledTimes(2);
 });
});
