import {act,fireEvent,render,screen} from '@testing-library/react';
import {afterEach,describe,expect,it,vi} from 'vitest';
import {AgentProgress,AgentMarkdown,AgentReply,AgentRecovery} from './agent-message';

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
  expect(screen.getByRole('link',{name:'example.test'})).toHaveAttribute('rel','noopener noreferrer');
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

it('explains disabled AI without displaying private configuration diagnostics',()=>{
 render(<AgentRecovery message="PRIVATE server configuration diagnostic" code="not_configured" onRetry={()=>{}}/>);
 expect(screen.getByRole('alert')).toHaveTextContent('AI is disabled.');
 expect(screen.queryByText(/PRIVATE/)).toBeNull();
 expect(screen.getByRole('button',{name:'Retry'})).toBeEnabled();
});


it('shows only fixed public progress labels and deduplicates observed steps',()=>{
 render(<AgentProgress steps={['searching_interviews','PRIVATE Brave tool output','searching_interviews']}/>);
 expect(screen.getByRole('status',{name:'Career goal progress'})).toHaveTextContent('Searching for relevant interview experiences');
 expect(screen.getAllByRole('listitem')).toHaveLength(1);
 expect(screen.queryByText(/PRIVATE|Brave/)).toBeNull();
});

it('explains career-only scope without exposing provider diagnostics',()=>{
 render(<AgentRecovery message="PRIVATE model response" code="career_scope" onRetry={()=>{}}/>);
 expect(screen.getByRole('alert')).toHaveTextContent('Please provide a job description');
 expect(screen.queryByText(/PRIVATE/)).toBeNull();
});

it('renders each summary citation beside its own point, preserving saved URL parentheses',()=>{
 const {container}=render(<AgentMarkdown>{'## Your career goal\n\n- An Analyst internship. [Source](<https://example.test/jobs_(internship)>)\n\n- SQL \\[required\\]. [Source](<https://skills.test/SQL_(required)>)\n\n- An interview is reported. [Source](<https://interviews.test/report>)\n\nAsk me anything about this goal set!'}</AgentMarkdown>);
 const intro=screen.getByText(/An Analyst internship/).closest('li')!;
 expect(intro.querySelector('a')).toHaveAttribute('href','https://example.test/jobs_(internship)');
 const points=screen.getAllByRole('listitem');
 expect(points).toHaveLength(3);
 expect(points[1]).toHaveTextContent('SQL [required].');
 expect(points[1].querySelector('a')).toHaveAttribute('href','https://skills.test/SQL_(required)');
 expect(points[2]).toHaveTextContent('An interview is reported.');
 expect(points[2].querySelector('a')).toHaveAttribute('href','https://interviews.test/report');
 expect(container.querySelectorAll('a')).toHaveLength(3);
 expect(screen.getByText('Ask me anything about this goal set!')).toBeVisible();
});

it('does not turn escaped model prose into a citation or HTML link',()=>{
 render(<AgentMarkdown>{'A \\[made-up link\\]\\(https://unapproved.test\\) and \\<https://unapproved.test\\>. [Source](<https://approved.test/report>)'}</AgentMarkdown>);
 expect(screen.getAllByRole('link')).toHaveLength(1);
 expect(screen.getByRole('link')).toHaveAttribute('href','https://approved.test/report');
});

it('shows source links inside the interview stage instead of internal fact markers',()=>{
 const reply='1. **Online test**: 50 questions. [Source](<https://reports.test/interview_(online)>)\n2. **Supervisor interview**: a short interview. [Source](<https://candidates.test/report>)';
 const {container}=render(<AgentMarkdown>{reply}</AgentMarkdown>);
 const stages=screen.getAllByRole('listitem');
 expect(stages).toHaveLength(2);
 expect(stages[0]).toHaveTextContent('Online test: 50 questions.');
 expect(stages[0].querySelector('a')).toHaveAttribute('href','https://reports.test/interview_(online)');
 expect(stages[1].querySelector('a')).toHaveAttribute('href','https://candidates.test/report');
 expect(container).not.toHaveTextContent(/\[f\d/);
 expect(container).not.toHaveTextContent('Sources:');
});
