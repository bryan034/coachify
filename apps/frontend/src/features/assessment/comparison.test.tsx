import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { ComparisonPanel, useComparison } from './comparison';
import { assessmentApi } from '@/lib/api/assessment';
vi.mock('@/lib/api/assessment', async original => ({...await original<typeof import('@/lib/api/assessment')>(), assessmentApi: vi.fn()}));
const api = vi.mocked(assessmentApi);
const current = {version: 7, stale: false, result: null, operation: null, ready: true, issues: []};
function View({token = 'synthetic'}: {token?: string}) { const comparison = useComparison(token); return <ComparisonPanel comparison={comparison}/>; }
beforeEach(() => {vi.resetAllMocks(); api.mockImplementation(async path => path === '/context' ? {ready:true,model_available:true,research_coverage:'unavailable',goal:{role:'Synthetic role'}} : current);});
it('reads without generating, explains partial coverage and submits one versioned command', async () => {
 render(<View/>);
 const button = await screen.findByRole('button', {name:'Compare with my skills'});
 expect(api.mock.calls.every(call => call[2] === undefined)).toBe(true);
 expect(screen.getByText(/results will be labelled partial/)).toBeVisible();
 fireEvent.click(button);
 await waitFor(() => expect(api.mock.calls.some(call => call[0] === '')).toBe(true));
 expect(api.mock.calls.find(call => call[0] === '')?.[2]).toMatchObject({expected_version:7,allow_partial:true,mutation_id:expect.any(String)});
});
it('retries an ambiguous submission with the same mutation identity', async () => {
 api.mockImplementation(async (path) => {if (path === '') throw new Error('Connection interrupted.'); return path === '/context' ? {ready:true,model_available:true} : current;});
 render(<View/>);fireEvent.click(await screen.findByRole('button',{name:'Compare with my skills'}));
 await screen.findByText('Connection interrupted.');
 fireEvent.click(screen.getByRole('button',{name:'Compare with my skills'}));
 await waitFor(() => expect(api.mock.calls.filter(call => call[0] === '')).toHaveLength(2));
 const calls = api.mock.calls.filter(call => call[0] === '');expect(calls[0][2]).toEqual(calls[1][2]);
});
it('hides stale evidence rather than displaying an old match', async () => {
 api.mockImplementation(async path => path === '/context' ? {ready:true,model_available:true} : {...current,stale:true,result:{job_skill_gaps:[{name:'Old Python',ref:'job:old',match_status:'supported'}]}});
 render(<View/>);await screen.findByText(/Your goal or skills changed/);
 expect(screen.queryByText('Old Python')).not.toBeInTheDocument();
 expect(screen.queryByText(/You have evidence/)).not.toBeInTheDocument();
});
it('ignores a late result from the previous account', async () => {
 let resolve!: (value: unknown) => void;
 api.mockImplementation(async (path, token) => token === 'old' ? new Promise(r => {resolve=r;}) : path === '/context' ? {ready:false,model_available:true} : current);
 const view=render(<View token="old"/>);view.rerender(<View token="new"/>);
 await act(async()=>resolve({...current,result:{role:'Private old goal'}}));
 expect(screen.queryByText('Private old goal')).not.toBeInTheDocument();
});

it('keeps satisfied OR alternatives out of confirmed gaps', async () => {
 api.mockImplementation(async path => path === '/context' ? {ready:true,model_available:true} : {...current,result:{role:'Role',research_coverage:'available',priorities:[],groups:[{operator:'any',match_status:'supported',requirement_refs:['job:python','job:sql']}],job_skill_gaps:[{ref:'job:python',name:'Python',match_status:'supported',components:[]},{ref:'job:sql',name:'SQL',match_status:'confirmed_shortfall',components:[{status:'confirmed_shortfall',evidence_refs:[]}]}]}});
 render(<View/>);
 await screen.findByText('You have evidence for 1 of 2 skills.');
 expect(screen.getByText('No confirmed skill gaps in this comparison.')).toBeVisible();
});
