import {fireEvent,render,screen} from '@testing-library/react';
import {afterEach,describe,expect,it,vi} from 'vitest';
import {SearchJobs} from './search-jobs';

afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();});
describe('Search Jobs',()=>{
 it('requires explicit search terms before offering job-board links',()=>{
  render(<SearchJobs/>);
  expect(screen.getByRole('heading',{level:1,name:'Search Jobs'})).toBeVisible();
  expect(screen.getByRole('textbox',{name:'Location'})).toHaveValue('Singapore');
  expect(screen.getByRole('button',{name:'Find jobs'})).toBeDisabled();
  expect(screen.queryByRole('link',{name:/LinkedIn/})).toBeNull();
  fireEvent.change(screen.getByRole('textbox',{name:'Job title or keywords'}),{target:{value:'   '}});
  expect(screen.getByRole('button',{name:'Find jobs'})).toBeDisabled();
 });
 it('builds encoded searches without fetching, storing or sending private CV data',()=>{
  const fetch=vi.fn();vi.stubGlobal('fetch',fetch);
  const storage=vi.spyOn(Storage.prototype,'setItem');
  render(<SearchJobs/>);
  fireEvent.change(screen.getByRole('textbox',{name:'Job title or keywords'}),{target:{value:'  C++ & SQL #1  '}});
  fireEvent.change(screen.getByRole('textbox',{name:'Location'}),{target:{value:'Singapore & remote'}});
  fireEvent.click(screen.getByRole('button',{name:'Find jobs'}));
  const linkedin=screen.getByRole('link',{name:/LinkedIn/}),indeed=screen.getByRole('link',{name:/Indeed/});
  const first=new URL(linkedin.getAttribute('href')!),second=new URL(indeed.getAttribute('href')!);
  expect(first.origin+first.pathname).toBe('https://www.linkedin.com/jobs/search/');
  expect(first.searchParams.get('keywords')).toBe('C++ & SQL #1');
  expect(first.searchParams.get('location')).toBe('Singapore & remote');
  expect(second.origin+second.pathname).toBe('https://sg.indeed.com/jobs');
  expect(second.searchParams.get('q')).toBe('C++ & SQL #1');
  expect(second.searchParams.get('l')).toBe('Singapore & remote');
  for(const link of [linkedin,indeed]){
   expect(link).toHaveAttribute('target','_blank');expect(link).toHaveAttribute('rel','noopener noreferrer');
  }
  expect(fetch).not.toHaveBeenCalled();expect(storage).not.toHaveBeenCalled();
  expect(screen.getByRole('link',{name:/Use its job description/})).toHaveAttribute('href','/career-goal?new=1');
 });
 it('clears stale search links when either field is changed',()=>{
  render(<SearchJobs/>);
  const keywords=screen.getByRole('textbox',{name:'Job title or keywords'}),location=screen.getByRole('textbox',{name:'Location'});
  fireEvent.change(keywords,{target:{value:'Analyst'}});fireEvent.click(screen.getByRole('button',{name:'Find jobs'}));
  expect(screen.getByRole('region',{name:'View matching jobs'})).toBeVisible();
  fireEvent.change(location,{target:{value:'London'}});
  expect(screen.queryByRole('region',{name:'View matching jobs'})).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'Find jobs'}));
  expect(new URL(screen.getByRole('link',{name:/LinkedIn/}).getAttribute('href')!).searchParams.get('location')).toBe('London');
  fireEvent.change(keywords,{target:{value:'Engineer'}});
  expect(screen.queryByRole('link',{name:/LinkedIn/})).toBeNull();
 });
});
