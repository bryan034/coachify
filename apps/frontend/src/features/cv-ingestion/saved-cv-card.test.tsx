import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {beforeEach,expect,it,vi} from 'vitest';
import {SavedCvCard} from './saved-cv-card';
import {cvApi,CvApiError} from '@/lib/api/cv';
import {savedCv} from '../../../tests/fixtures/cv';
vi.mock('@/lib/api/cv',()=>({cvApi:{rename:vi.fn()},CvApiError:class extends Error{constructor(message:string,public status:number){super(message);}}}));
beforeEach(()=>vi.clearAllMocks());
function setup(){const props={cv:savedCv('one'),active:true,busy:false,token:'synthetic',review:vi.fn(),select:vi.fn(),remove:vi.fn(),saved:vi.fn(),refresh:vi.fn().mockResolvedValue(undefined)};render(<SavedCvCard {...props}/>);return props;}
it('saves a title independently of baseline selection or review',async()=>{
 const props=setup();vi.mocked(cvApi.rename).mockResolvedValue({...props.cv,display_name:'Engineering CV'});
 fireEvent.click(screen.getByRole('button',{name:'Rename'}));fireEvent.change(screen.getByRole('textbox',{name:'CV title'}),{target:{value:' Engineering CV '}});fireEvent.click(screen.getByRole('button',{name:'Save title'}));
 await waitFor(()=>expect(props.saved).toHaveBeenCalledWith(expect.objectContaining({display_name:'Engineering CV'})));
 expect(cvApi.rename).toHaveBeenCalledWith('one',expect.objectContaining({display_name:'Engineering CV',expected_version:props.cv.version}),'synthetic',expect.any(AbortSignal));expect(props.select).not.toHaveBeenCalled();expect(props.review).not.toHaveBeenCalled();
});
it('retains the draft and exact request identity after a lost response',async()=>{
 setup();vi.mocked(cvApi.rename).mockRejectedValue(new Error('Connection interrupted'));
 fireEvent.click(screen.getByRole('button',{name:'Rename'}));fireEvent.change(screen.getByRole('textbox',{name:'CV title'}),{target:{value:'Draft title'}});fireEvent.click(screen.getByRole('button',{name:'Save title'}));await screen.findByRole('alert');
 expect(screen.getByRole('textbox',{name:'CV title'})).toHaveValue('Draft title');fireEvent.click(screen.getByRole('button',{name:'Save title'}));await waitFor(()=>expect(cvApi.rename).toHaveBeenCalledTimes(2));expect(vi.mocked(cvApi.rename).mock.calls[0][1]).toEqual(vi.mocked(cvApi.rename).mock.calls[1][1]);
});
it('refreshes on a conflict while retaining the typed title',async()=>{
 const props=setup();vi.mocked(cvApi.rename).mockRejectedValue(new CvApiError('CV changed',409));fireEvent.click(screen.getByRole('button',{name:'Rename'}));fireEvent.change(screen.getByRole('textbox',{name:'CV title'}),{target:{value:'My draft'}});fireEvent.click(screen.getByRole('button',{name:'Save title'}));await waitFor(()=>expect(props.refresh).toHaveBeenCalled());expect(screen.getByRole('textbox',{name:'CV title'})).toHaveValue('My draft');
});
