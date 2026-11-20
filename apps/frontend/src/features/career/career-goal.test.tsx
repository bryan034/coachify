import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CareerGoal } from './career-goal';
import {CareerSessionProvider} from './career-session';
const push=vi.fn();
vi.mock('next/navigation',()=>({useRouter:()=>({push,replace:vi.fn()})}));
const renderPage=(node:React.ReactNode)=>(render(<CareerSessionProvider>{node}</CareerSessionProvider>));
import { importCareer } from '@/lib/api/career';
import { careerOperation } from '@/lib/api/career-operation';
vi.mock('@/lib/api/career-operation',()=>({careerOperation:vi.fn()}));
vi.mock('@/features/profile/profile-provider',()=>({useProfile:()=>({token:'synthetic-session'})}));
vi.mock('@/lib/api/career',()=>({importCareer:vi.fn(),careerApi:vi.fn(async()=>({goals:[],reviews:[]}))}));
afterEach(()=>{vi.restoreAllMocks();vi.mocked(importCareer).mockClear();});
const preview={kind:'url' as const,text:'Analyst\n• SQL or Python',source_name:'Synthetic Jobs',source_url:'https://example.test/job',notices:['Check for missing content.']};

describe('temporary Career Goal inputs',()=>{
 it('preserves pasted Unicode and whitespace, never submits or stores it, and retains it between tabs',()=>{
  const storage=vi.spyOn(Storage.prototype,'setItem');
  renderPage(<CareerGoal/>);
  const text='  Analyst 🧭\n\n• SQL or Python\n';
  fireEvent.change(screen.getByRole('textbox',{name:'Job description'}),{target:{value:text}});
  expect(screen.getByRole('textbox',{name:'Job description'})).toHaveValue(text);
  fireEvent.click(screen.getByRole('tab',{name:'Job URL'}));
  fireEvent.click(screen.getByRole('tab',{name:'Paste description'}));
  expect(screen.getByRole('textbox',{name:'Job description'})).toHaveValue(text);
  expect(importCareer).not.toHaveBeenCalled();expect(storage).not.toHaveBeenCalled();
  expect(screen.getByRole('button',{name:'Extract career goal'})).toBeEnabled();
 });
 it('counts Unicode characters and retains over-limit input instead of truncating it',()=>{
  renderPage(<CareerGoal/>);
  fireEvent.change(screen.getByRole('textbox',{name:'Job description'}),{target:{value:'🧭'.repeat(8_001)}});
  expect(screen.getByRole('textbox',{name:'Job description'})).toHaveAttribute('aria-invalid','true');
  expect(screen.getByText('8,001 / 8,000 characters')).toBeVisible();
  expect(screen.getByRole('textbox',{name:'Job description'})).toHaveValue('🧭'.repeat(8_001));
 });
 it('imports an editable URL preview and keeps it through a failed replacement',async()=>{
  vi.mocked(importCareer).mockResolvedValueOnce(preview).mockRejectedValueOnce(new Error('This site blocks automated access.'));
  vi.spyOn(window,'confirm').mockReturnValue(true);
  renderPage(<CareerGoal/>);fireEvent.click(screen.getByRole('tab',{name:'Job URL'}));
  fireEvent.change(screen.getByLabelText('Job description URL'),{target:{value:preview.source_url}});
  fireEvent.click(screen.getByRole('button',{name:'Import job page'}));
  await screen.findByRole('textbox',{name:'Review and edit the preview'});
  fireEvent.change(screen.getByRole('textbox',{name:'Review and edit the preview'}),{target:{value:'My edited preview'}});
  fireEvent.click(screen.getByRole('button',{name:'Import job page'}));
  expect(await screen.findByRole('alert')).toHaveTextContent('blocks automated access');
  expect(screen.getByRole('textbox',{name:'Review and edit the preview'})).toHaveValue('My edited preview');
 });
 it('rejects empty or oversized files before an API call',async()=>{
  vi.mocked(importCareer).mockClear();renderPage(<CareerGoal/>);fireEvent.click(screen.getByRole('tab',{name:'Upload document'}));
  fireEvent.change(screen.getByLabelText('Job description document'),{target:{files:[new File([],'empty.txt',{type:'text/plain'})]}});
  expect(await screen.findByRole('alert')).toHaveTextContent('non-empty');
  fireEvent.change(screen.getByLabelText('Job description document'),{target:{files:[new File([new Uint8Array(10*1024*1024+1)],'large.txt',{type:'text/plain'})]}});
  expect(screen.getByRole('alert')).toHaveTextContent('10 MiB');expect(importCareer).not.toHaveBeenCalled();
 });
 it('submits documents as multipart form data and shows the returned preview',async()=>{
  vi.mocked(importCareer).mockResolvedValue({...preview,kind:'document',source_name:'role.txt'});
  renderPage(<CareerGoal/>);fireEvent.click(screen.getByRole('tab',{name:'Upload document'}));
  const file=new File(['Analyst\nSQL'],'role.txt',{type:'text/plain'});
  fireEvent.change(screen.getByLabelText('Job description document'),{target:{files:[file]}});
  await screen.findByRole('textbox',{name:'Review and edit the preview'});
  const args=vi.mocked(importCareer).mock.calls.at(-1)!;expect(args[0]).toBe('document');expect((args[1] as FormData).get('file')).toBe(file);
 });
 it('ignores a late import response after switching methods',async()=>{
  let resolve!:(value:typeof preview)=>void;
  vi.mocked(importCareer).mockImplementation(()=>new Promise(r=>{resolve=r;}));
  renderPage(<CareerGoal/>);fireEvent.click(screen.getByRole('tab',{name:'Job URL'}));
  fireEvent.change(screen.getByLabelText('Job description URL'),{target:{value:preview.source_url}});
  fireEvent.click(screen.getByRole('button',{name:'Import job page'}));
  fireEvent.click(screen.getByRole('tab',{name:'Paste description'}));resolve(preview);
  await waitFor(()=>expect(screen.getByRole('textbox',{name:'Job description'})).toHaveValue(''));
  fireEvent.click(screen.getByRole('tab',{name:'Job URL'}));expect(screen.queryByRole('textbox',{name:'Review and edit the preview'})).not.toBeInTheDocument();
 });
 it('supports keyboard tabs and confirms before clearing or following navigation',()=>{
  vi.spyOn(window,'confirm').mockReturnValue(false);
  renderPage(<><a href="/dashboard">Home</a><CareerGoal/></>);
  fireEvent.keyDown(screen.getByRole('tab',{name:'Paste description'}),{key:'ArrowRight'});
  expect(screen.getByRole('tab',{name:'Job URL'})).toHaveFocus();
  fireEvent.click(screen.getByRole('tab',{name:'Paste description'}));
  fireEvent.change(screen.getByRole('textbox',{name:'Job description'}),{target:{value:'Temporary role'}});
  fireEvent.click(screen.getByRole('button',{name:'Clear input'}));
  expect(screen.getByRole('textbox',{name:'Job description'})).toHaveValue('Temporary role');
  fireEvent.click(screen.getByRole('link',{name:'Home'}));expect(window.confirm).toHaveBeenCalledTimes(2);
 });
});

describe('extracting a career goal',()=>{
 const type=()=>fireEvent.change(screen.getByRole('textbox',{name:'Job description'}),{target:{value:'Backend engineer — build APIs with Python.'}});
 it('shows the processing screen as soon as extraction starts and opens the chat after success',async()=>{
  push.mockClear();vi.mocked(careerOperation).mockResolvedValueOnce({} as never);
  renderPage(<CareerGoal/>);
  expect(screen.getByRole('button',{name:'Extract career goal'})).toBeDisabled();
  type();fireEvent.click(screen.getByRole('button',{name:'Extract career goal'}));
  expect(screen.getByRole('region',{name:'Skills needed'})).toBeInTheDocument();
  expect(screen.queryByRole('textbox',{name:'Job description'})).not.toBeInTheDocument();
  await waitFor(()=>expect(push).toHaveBeenCalledWith('/career-goal/chat?source=jd'));
  expect(importCareer).not.toHaveBeenCalled();
 });
 it('stays on this page on failure, keeps the input and offers a retry',async()=>{
  push.mockClear();vi.mocked(careerOperation).mockRejectedValueOnce(new Error('Extraction failed.')).mockResolvedValueOnce({} as never);
  renderPage(<CareerGoal/>);type();
  fireEvent.click(screen.getByRole('button',{name:'Extract career goal'}));
  await screen.findByText('Extraction failed.');
  expect(push).not.toHaveBeenCalled();
  expect(screen.getByRole('textbox',{name:'Job description'})).toHaveValue('Backend engineer — build APIs with Python.');
  fireEvent.click(screen.getByRole('button',{name:'Retry extraction'}));
  await waitFor(()=>expect(push).toHaveBeenCalledWith('/career-goal/chat?source=jd'));
  const keys=vi.mocked(careerOperation).mock.calls.map(c=>(c[2].headers as Record<string,string>)['Idempotency-Key']);
  expect(keys[0]).toBe(keys[1]);
 });
 it('lets the user leave during extraction and reconnects to the same operation on return',async()=>{
  push.mockClear();sessionStorage.clear();vi.mocked(careerOperation).mockClear();
  const confirm=vi.spyOn(window,'confirm').mockReturnValue(false);
  vi.mocked(careerOperation).mockImplementationOnce(()=>new Promise(()=>{})).mockResolvedValueOnce({} as never);
  const first=renderPage(<><a href="/dashboard">Home</a><CareerGoal/></>);type();
  fireEvent.click(screen.getByRole('button',{name:'Extract career goal'}));
  expect(screen.getByText(/You can leave this page\. elo keeps working/)).toBeVisible();
  fireEvent.click(screen.getByRole('link',{name:'Home'}));
  expect(confirm).not.toHaveBeenCalled();
  first.unmount();
  renderPage(<CareerGoal/>);
  expect(screen.getByRole('region',{name:'Skills needed'})).toBeInTheDocument();
  await waitFor(()=>expect(push).toHaveBeenCalledWith('/career-goal/chat?source=jd'));
  const calls=vi.mocked(careerOperation).mock.calls;
  expect(calls).toHaveLength(2);
  expect((calls[1][2].headers as Record<string,string>)['Idempotency-Key']).toBe((calls[0][2].headers as Record<string,string>)['Idempotency-Key']);
  expect(calls[1][2].body).toBe(calls[0][2].body);
  expect(sessionStorage.getItem('elo-career-extraction')).toBeNull();
 });
});

it('names the job site and how to paste when its terms forbid automated reading',async()=>{
 vi.mocked(importCareer).mockRejectedValueOnce(new Error('The information could not be extracted from this website. LinkedIn does not allow its job listings to be read automatically. Open the job on LinkedIn, copy the description and paste it here.'));
 renderPage(<CareerGoal/>);
 fireEvent.click(screen.getByRole('tab',{name:'Job URL'}));
 fireEvent.change(screen.getByLabelText('Job description URL'),{target:{value:'https://www.linkedin.com/jobs/view/1'}});
 fireEvent.click(screen.getByRole('button',{name:'Import job page'}));
 const alert=await screen.findByRole('alert');
 expect(alert).toHaveTextContent('The information could not be extracted from this website.');
 expect(alert).toHaveTextContent('LinkedIn does not allow its job listings to be read automatically. Open the job on LinkedIn, copy the description and paste it here.');
 expect(alert).not.toHaveTextContent('copy its description and paste it instead');
 expect(within(alert).getByRole('button',{name:'Paste description'})).toBeInTheDocument();
});

it('tells the user to copy and paste when a website blocks extraction, keeping drafts',async()=>{
 vi.mocked(importCareer).mockRejectedValueOnce(new Error('The information could not be extracted from this website. Copy and paste the job description instead.'));
 renderPage(<CareerGoal/>);
 fireEvent.change(screen.getByRole('textbox',{name:'Job description'}),{target:{value:'My pasted draft'}});
 fireEvent.click(screen.getByRole('tab',{name:'Job URL'}));
 fireEvent.change(screen.getByLabelText('Job description URL'),{target:{value:preview.source_url}});
 fireEvent.click(screen.getByRole('button',{name:'Import job page'}));
 const alert=await screen.findByRole('alert');
 expect(alert).toHaveTextContent('The information could not be extracted from this website.');
 expect(alert).toHaveTextContent('copy its description and paste it instead');
 expect(alert).not.toHaveTextContent('Retry');
 fireEvent.click(within(alert).getByRole('button',{name:'Paste description'}));
 expect(screen.getByRole('tab',{name:'Paste description'})).toHaveAttribute('aria-selected','true');
 expect(screen.getByRole('textbox',{name:'Job description'})).toHaveValue('My pasted draft');
});

it('keeps the specific message and other sources for non-blocking URL failures',async()=>{
 vi.mocked(importCareer).mockRejectedValueOnce(new Error('This job page is no longer available or the link is incorrect.'));
 renderPage(<CareerGoal/>);
 fireEvent.click(screen.getByRole('tab',{name:'Job URL'}));
 fireEvent.change(screen.getByLabelText('Job description URL'),{target:{value:preview.source_url}});
 fireEvent.click(screen.getByRole('button',{name:'Import job page'}));
 const alert=await screen.findByRole('alert');
 expect(alert).toHaveTextContent('no longer available');
 expect(within(alert).getByRole('button',{name:'Upload document'})).toBeVisible();
});
