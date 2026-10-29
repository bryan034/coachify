import {act,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {beforeEach,expect,it,vi} from 'vitest';
import {CvGoalConfirmationCard} from './cv-goal-confirmation';
import {confirmCvGoal,getCvGoalConfirmation,type CvGoalConfirmation} from '@/lib/api/career-cv-confirmation';
import {CareerApiError,type SavedGoal} from '@/lib/api/career';
vi.mock('@/lib/api/career-cv-confirmation',()=>({getCvGoalConfirmation:vi.fn(),confirmCvGoal:vi.fn()}));
const goal:SavedGoal={_id:'111111111111111111111111',version:3,target_type:'specific_job',role:'Data analyst',field:'Analytics',company:null,location:null,seniority_level:null,job_url:null,skills:[],interests:[],preferences:[],readiness:'ready',exploration_draft_id:null,exploration_draft_version:null};
const state=(changes:Partial<CvGoalConfirmation>={}):CvGoalConfirmation=>({goal_id:goal._id,goal_version:3,selection_version:8,confirmed:false,context:null,reason:null,...changes});
const confirmed=()=>state({confirmed:true,context:{id:goal._id,version:3,selection_version:8,confirmed:true}});
const props=()=>({goal,selectionVersion:8,token:'owner-a',onReload:vi.fn()});
beforeEach(()=>{vi.resetAllMocks();vi.mocked(getCvGoalConfirmation).mockResolvedValue(state());vi.mocked(confirmCvGoal).mockResolvedValue(confirmed());});
it('requires an explicit confirmation of the current automatically saved revision',async()=>{
 render(<CvGoalConfirmationCard {...props()}/>);const button=await screen.findByRole('button',{name:'Confirm this goal for CV review'});await waitFor(()=>expect(button).toBeEnabled());
 expect(confirmCvGoal).not.toHaveBeenCalled();expect(screen.getByText(/Your goal is saved automatically/)).toBeVisible();fireEvent.click(button);
 expect(await screen.findByRole('link',{name:'Review CV clarifications'})).toHaveAttribute('href','/cv');
 expect(confirmCvGoal).toHaveBeenCalledWith({expected_goal_id:goal._id,expected_goal_version:3,expected_selection_version:8,mutation_id:expect.any(String)},'owner-a',expect.any(AbortSignal));
});
it('restores confirmed status after returning without submitting again',async()=>{
 vi.mocked(getCvGoalConfirmation).mockResolvedValue(confirmed());render(<CvGoalConfirmationCard {...props()}/>);
 expect(await screen.findByRole('heading',{name:'Confirmed for CV review'})).toBeVisible();expect(confirmCvGoal).not.toHaveBeenCalled();
});
it('keeps incomplete requirements unavailable for confirmation',async()=>{
 vi.mocked(getCvGoalConfirmation).mockResolvedValue(state({reason:'Review the updated requirements first.'}));render(<CvGoalConfirmationCard {...props()}/>);
 await screen.findByText('Review the updated requirements first.');expect(screen.getByRole('button',{name:'Confirm this goal for CV review'})).toBeDisabled();
});
it('retains the exact request identity after an interrupted response and status check',async()=>{
 vi.mocked(confirmCvGoal).mockRejectedValueOnce(new TypeError('Response interrupted.')).mockResolvedValueOnce(confirmed());render(<CvGoalConfirmationCard {...props()}/>);
 const button=await screen.findByRole('button',{name:'Confirm this goal for CV review'});await waitFor(()=>expect(button).toBeEnabled());fireEvent.click(button);await screen.findByRole('alert');
 fireEvent.click(screen.getByRole('button',{name:'Check confirmation status'}));await waitFor(()=>expect(getCvGoalConfirmation).toHaveBeenCalledTimes(2));await waitFor(()=>expect(button).toBeEnabled());fireEvent.click(button);
 await screen.findByRole('link',{name:'Review CV clarifications'});expect(vi.mocked(confirmCvGoal).mock.calls[0][0]).toEqual(vi.mocked(confirmCvGoal).mock.calls[1][0]);
});
it('requires reviewing the newer goal after a stale confirmation response',async()=>{
 vi.mocked(confirmCvGoal).mockRejectedValue(new CareerApiError('Goal changed.',409));const input=props();render(<CvGoalConfirmationCard {...input}/>);
 const button=await screen.findByRole('button',{name:'Confirm this goal for CV review'});await waitFor(()=>expect(button).toBeEnabled());fireEvent.click(button);await screen.findByText('Goal changed.');expect(button).toBeDisabled();fireEvent.click(screen.getByRole('button',{name:'Reload saved goal'}));expect(input.onReload).toHaveBeenCalledOnce();expect(screen.queryByRole('link',{name:'Review CV clarifications'})).not.toBeInTheDocument();
});
it('does not confirm a goal when the current server selection differs from the displayed revision',async()=>{
 vi.mocked(getCvGoalConfirmation).mockResolvedValue(state({goal_version:4,selection_version:9}));render(<CvGoalConfirmationCard {...props()}/>);
 await screen.findByRole('button',{name:'Reload saved goal'});expect(screen.getByRole('button',{name:'Confirm this goal for CV review'})).toBeDisabled();expect(confirmCvGoal).not.toHaveBeenCalled();
});
it('ignores a delayed confirmation after the account or goal changes',async()=>{
 let finish!:(value:CvGoalConfirmation)=>void;vi.mocked(confirmCvGoal).mockImplementation(()=>new Promise(resolve=>finish=resolve));
 const input=props(),view=render(<CvGoalConfirmationCard key="a" {...input}/>);const button=await screen.findByRole('button',{name:'Confirm this goal for CV review'});await waitFor(()=>expect(button).toBeEnabled());fireEvent.click(button);
 vi.mocked(getCvGoalConfirmation).mockResolvedValue(state({goal_version:4}));view.rerender(<CvGoalConfirmationCard key="b" {...input} token="owner-b" goal={{...goal,version:4}}/>);await waitFor(()=>expect(getCvGoalConfirmation).toHaveBeenLastCalledWith('owner-b',expect.any(AbortSignal)));
 await act(async()=>finish(confirmed()));expect(screen.queryByRole('link',{name:'Review CV clarifications'})).not.toBeInTheDocument();expect(screen.getByRole('button',{name:'Confirm this goal for CV review'})).toBeEnabled();expect(vi.mocked(confirmCvGoal).mock.calls[0][2].aborted).toBe(true);
});
