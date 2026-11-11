import {fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {beforeEach,expect,it,vi} from 'vitest';
import {InterviewPrepGuideCard} from './interview-prep-guide';
import {careerApi,type InterviewPrepGuide} from '@/lib/api/career';
vi.mock('@/features/profile/profile-provider',()=>({useProfile:()=>({token:'synthetic-token'})}));
vi.mock('@/lib/api/career',()=>({careerApi:vi.fn()}));
const guide:InterviewPrepGuide={goal_id:'goal',goal_version:3,research_id:'r1',generated_at:'2026-11-11T00:00:00Z',interview_date:'2026-11-20',
 role:['SQL','Dashboards'],success:['Accuracy'],
 process:[{round:1,name:'Online assessment',format:['timed'],basis:'confirmed',source_ids:['s1']},{round:2,name:'Case study',format:['case'],basis:'candidate_report',source_ids:[]}],
 resume:[{competency:'Data querying',skill:'SQL',signals:['Reporting'],status:'strength'},{competency:'Stakeholders',skill:null,signals:[],status:'gap'}],
 syllabus:[{name:'SQL joins',priority:'high',depth:'deep',terms:['INNER','LEFT'],basis:'confirmed',source_ids:['s1']}],
 company:{model:[],products:['Analytics'],customers:[],competitors:[],risks:[]},
 questions:[{text:'Why this company?',kind:'behavioural',basis:'prediction',source_ids:[]}],
 schedule:[{when:'Nov 11',focus:['Role and process','Online assessment']}],sources:[{source_id:'s1',url:'https://example.test/careers',title:'Careers'}],not_covered:['recent news']};
beforeEach(()=>{vi.resetAllMocks();});

it('offers to create a guide when none exists, sending the date and goal version',async()=>{
 vi.mocked(careerApi).mockResolvedValueOnce({status:'missing',guide:null}).mockResolvedValueOnce({status:'ready',guide});
 render(<InterviewPrepGuideCard goalId="goal" version={3}/>);
 await screen.findByText(/Keywords only/);
 fireEvent.change(screen.getByLabelText('Interview date'),{target:{value:'2026-11-20'}});
 fireEvent.click(screen.getByRole('button',{name:'Create guide'}));
 await screen.findByRole('button',{name:'Refresh guide'});
 const [path,token,options]=vi.mocked(careerApi).mock.calls[1] as [string,string,RequestInit];
 expect(path).toBe('/goals/goal/interview-prep');expect(token).toBe('synthetic-token');
 expect(JSON.parse(options.body as string)).toEqual({expected_version:3,interview_date:'2026-11-20',refresh:false});
});

it('shows keywords with evidence labels, resume gaps and cited sources, not paragraphs',async()=>{
 vi.mocked(careerApi).mockResolvedValue({status:'ready',guide});
 render(<InterviewPrepGuideCard goalId="goal" version={3}/>);
 const process=within((await screen.findByRole('heading',{name:'Process'})).closest('section')!);
 expect(process.getByText('Online assessment')).toBeVisible();
 expect(process.getByText('Confirmed')).toBeVisible();expect(process.getByText('Reported')).toBeVisible();
 expect(process.getByRole('link',{name:'Source 1: Careers'})).toHaveAttribute('href','https://example.test/careers');
 expect(screen.getByText('INNER')).toBeVisible();expect(screen.getByText('high')).toBeVisible();
 const fit=within(screen.getByRole('heading',{name:'Resume fit'}).closest('section')!);
 expect(fit.getByText('Gap')).toBeVisible();expect(fit.getByText('SQL')).toBeVisible();
 expect(screen.getByText('Predicted')).toBeVisible();
 expect(screen.getByRole('heading',{name:'Plan to interview day'})).toBeVisible();
 expect(screen.getByText('Not covered yet: recent news.')).toBeVisible();
 expect(screen.getByLabelText('Interview date')).toHaveValue('2026-11-20');
 expect(screen.queryByRole('heading',{name:'Customers'})).not.toBeInTheDocument();
});

it('explains a failed generation and keeps the existing guide',async()=>{
 vi.mocked(careerApi).mockResolvedValueOnce({status:'ready',guide}).mockRejectedValueOnce(new Error('down'));
 render(<InterviewPrepGuideCard goalId="goal" version={3}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Refresh guide'}));
 expect(await screen.findByRole('alert')).toHaveTextContent('could not be generated');
 await waitFor(()=>expect(screen.getByText('SQL joins')).toBeVisible());
});
