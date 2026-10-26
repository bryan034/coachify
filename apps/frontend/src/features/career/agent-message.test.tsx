import {act,fireEvent,render,screen} from '@testing-library/react';
import {afterEach,describe,expect,it,vi} from 'vitest';
import {AgentMarkdown,AgentReply,AgentRecovery} from './agent-message';

describe('assistant Markdown',()=>{
 it('renders emphasis, headings, lists and code instead of literal markers',()=>{
  const {container}=render(<AgentMarkdown>{'## Preparation\n\nLearn **SQL** and *Python*.\n\n- Practise joins\n- Build an API\n\nUse `SELECT`.'}</AgentMarkdown>);
  expect(screen.getByRole('heading',{name:'Preparation'})).toBeInTheDocument();
  expect(container.querySelector('strong')).toHaveTextContent('SQL');
  expect(container.querySelector('em')).toHaveTextContent('Python');
  expect(screen.getAllByRole('listitem')).toHaveLength(2);
  expect(container.querySelector('code')).toHaveTextContent('SELECT');
  expect(container).not.toHaveTextContent('**');
 });
 it('never executes HTML, fetches model images or creates unsafe links',()=>{
  const {container}=render(<AgentMarkdown>{'<script>alert(1)</script>\n\n<img src="https://tracker.test/pixel">\n\n![tracking](https://tracker.test/pixel)\n\n[bad](javascript:alert%281%29)\n\n[bad protocol](//tracker.test)\n\n[Source](https://example.test/report)'}</AgentMarkdown>);
  expect(container.querySelector('script,img')).toBeNull();
  expect(screen.queryByRole('link',{name:'bad'})).toBeNull();
  expect(screen.queryByRole('link',{name:'bad protocol'})).toBeNull();
  expect(screen.getByRole('link',{name:'Source'})).toHaveAttribute('rel','noopener noreferrer');
 });
});


afterEach(()=>{vi.useRealTimers();vi.unstubAllGlobals();});
function motion(reduced:boolean){vi.stubGlobal('matchMedia',()=>({matches:reduced,addEventListener(){},removeEventListener(){}}));}

it('reveals a new reply word by word and ends with proper Markdown',()=>{
 motion(false);vi.useFakeTimers();
 const {container}=render(<AgentReply>{'Learn **SQL**.\n\n- Practise joins'}</AgentReply>);
 expect(container).toHaveTextContent('Learn');
 expect(container).not.toHaveTextContent('Practise');
 act(()=>vi.advanceTimersByTime(20));
 expect(container.querySelector('strong')).toHaveTextContent('SQL');
 act(()=>vi.advanceTimersByTime(200));
 expect(screen.getByRole('listitem')).toHaveTextContent('Practise joins');
 expect(screen.queryByRole('button',{name:'Show full response'})).toBeNull();
});

it('can reveal the whole answer immediately and does not restart on the same content',()=>{
 motion(false);vi.useFakeTimers();
 const view=render(<AgentReply>{'First second third fourth'}</AgentReply>);
 fireEvent.click(screen.getByRole('button',{name:'Show full response'}));
 expect(view.container).toHaveTextContent('First second third fourth');
 view.rerender(<AgentReply>{'First second third fourth'}</AgentReply>);
 expect(screen.queryByRole('button',{name:'Show full response'})).toBeNull();
 view.rerender(<AgentReply>{'New response here'}</AgentReply>);
 expect(view.container).not.toHaveTextContent('First second');
 expect(view.container).not.toHaveTextContent('response here');
});

it('respects reduced motion and shows older replies without animation',()=>{
 motion(true);const view=render(<AgentReply>{'Immediate complete response'}</AgentReply>);
 expect(view.container).toHaveTextContent('Immediate complete response');
 expect(screen.queryByRole('button',{name:'Show full response'})).toBeNull();
 motion(false);view.rerender(<AgentReply animate={false}>{'Older complete response'}</AgentReply>);
 expect(view.container).toHaveTextContent('Older complete response');
});

it('hides technical errors but keeps recovery available',()=>{
 render(<AgentRecovery message="PRIVATE provider_json diagnostic" code="invalid_output" onRetry={()=>{}}/>);
 expect(screen.queryByRole('alert')).toBeNull();
 expect(screen.queryByText(/PRIVATE/)).toBeNull();
 expect(screen.getByRole('button',{name:'Retry'})).toBeEnabled();
});

it('keeps token errors and the countdown visible',()=>{
 render(<AgentRecovery message="Your token limit was reached." code="rate_limited" seconds={5} onRetry={()=>{}}/>);
 expect(screen.getByRole('alert')).toHaveTextContent('Your token limit was reached.');
 expect(screen.getByRole('status')).toHaveTextContent('Try again in 5 seconds.');
});
