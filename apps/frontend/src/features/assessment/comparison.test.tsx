import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { useComparison } from './comparison';
import { assessmentApi } from '@/lib/api/assessment';
vi.mock('@/lib/api/assessment', async original => ({...await original<typeof import('@/lib/api/assessment')>(), assessmentApi: vi.fn()}));
const api = vi.mocked(assessmentApi);
const current = {version: 7, stale: false, result: null, operation: null, ready: true, issues: []};
/** A bare consumer of the hook: what the page components read from it. */
function View({token = 'synthetic'}: {token?: string}) {
 const c = useComparison(token);
 return <section>
  {c.error && <p role="alert">{c.error}</p>}
  {c.current?.stale && c.current.result && <p>Your goal or skills changed.</p>}
  {c.result && <p>Result for {c.result.role}</p>}
  <p data-testid="matches">{JSON.stringify(c.matches)}</p>
  <button disabled={!c.context?.ready || c.busy} onClick={() => void c.compare()}>Compare with my skills</button>
 </section>;
}
beforeEach(() => {vi.resetAllMocks(); api.mockImplementation(async path => path === '/context' ? {ready:true,model_available:true,research_coverage:'unavailable',goal:{role:'Synthetic role'}} : current);});
it('reads without generating and submits one versioned command', async () => {
 render(<View/>);
 const button = await screen.findByRole('button', {name:'Compare with my skills'});
 await waitFor(() => expect(button).toBeEnabled());
 expect(api.mock.calls.every(call => call[2] === undefined)).toBe(true);
 fireEvent.click(button);
 await waitFor(() => expect(api.mock.calls.some(call => call[0] === '')).toBe(true));
 expect(api.mock.calls.find(call => call[0] === '')?.[2]).toMatchObject({expected_version:7,allow_partial:true,mutation_id:expect.any(String)});
});
it('retries an ambiguous submission with the same mutation identity', async () => {
 api.mockImplementation(async (path) => {if (path === '') throw new Error('Connection interrupted.'); return path === '/context' ? {ready:true,model_available:true} : current;});
 render(<View/>);
 const button = await screen.findByRole('button',{name:'Compare with my skills'});
 await waitFor(() => expect(button).toBeEnabled());
 fireEvent.click(button);
 await screen.findByText('Connection interrupted.');
 fireEvent.click(screen.getByRole('button',{name:'Compare with my skills'}));
 await waitFor(() => expect(api.mock.calls.filter(call => call[0] === '')).toHaveLength(2));
 const calls = api.mock.calls.filter(call => call[0] === '');expect(calls[0][2]).toEqual(calls[1][2]);
});
it('hides stale evidence rather than displaying an old match', async () => {
 api.mockImplementation(async path => path === '/context' ? {ready:true,model_available:true} : {...current,stale:true,result:{job_skill_gaps:[{name:'Old Python',ref:'job:old',match_status:'supported'}]}});
 render(<View/>);await screen.findByText(/Your goal or skills changed/);
 expect(screen.getByTestId('matches')).toHaveTextContent('null');
});
it('ignores a late result from the previous account', async () => {
 let resolve!: (value: unknown) => void;
 api.mockImplementation(async (path, token) => token === 'old' ? new Promise(r => {resolve=r;}) : path === '/context' ? {ready:false,model_available:true} : current);
 const view=render(<View token="old"/>);view.rerender(<View token="new"/>);
 await act(async()=>resolve({...current,result:{role:'Private old goal'}}));
 expect(screen.queryByText(/Private old goal/)).not.toBeInTheDocument();
});
it('marks satisfied OR alternatives as covered rather than as gaps', async () => {
 api.mockImplementation(async path => path === '/context' ? {ready:true,model_available:true} : {...current,result:{role:'Role',research_coverage:'available',priorities:[],groups:[{operator:'any',match_status:'supported',requirement_refs:['job:python','job:sql']}],job_skill_gaps:[{ref:'job:python',name:'Python',match_status:'supported'},{ref:'job:sql',name:'SQL',match_status:'confirmed_shortfall'}]}});
 render(<View/>);
 await screen.findByText('Result for Role');
 expect(JSON.parse(screen.getByTestId('matches').textContent!)).toEqual({python:'supported',sql:'covered'});
});
