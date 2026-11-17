import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { SettingsPage, RoadmapSettingsPage } from './settings-page';
import { ThemePreference } from './theme-preference';
import { workspace } from '../../../tests/fixtures/roadmap-workspace';
const api=vi.hoisted(()=>vi.fn());
vi.mock('@/features/profile/profile-provider',()=>({useProfile:()=>({token:'synthetic'})}));
vi.mock('@/lib/api/roadmap',()=>({roadmapApi:api}));
beforeEach(()=>{api.mockReset();localStorage.clear();delete document.documentElement.dataset.theme;});
it('saves roadmap defaults with a workspace version and preserves dates and blocks',async()=>{
 const state=workspace({version:7});api.mockResolvedValue(state);render(<RoadmapSettingsPage/>);
 expect(await screen.findByLabelText('Break minutes per hour')).toHaveValue(10);
 expect(screen.getByLabelText('Week starts on')).toHaveValue('0');
 fireEvent.change(screen.getByLabelText('Plan next week on'),{target:{value:'5'}});
 fireEvent.click(screen.getByRole('button',{name:'Save settings'}));
 await screen.findByRole('status');await waitFor(()=>expect(api.mock.calls[1][2]).toMatchObject({expected_version:7,config:{...state.planner.config,plan_day:5}}));
});
it('keeps unsaved settings when a concurrent save is rejected',async()=>{
 api.mockResolvedValueOnce(workspace()).mockRejectedValueOnce(new Error('Your roadmap changed. Reload settings.'));render(<RoadmapSettingsPage/>);
 fireEvent.change(await screen.findByLabelText('Break minutes per hour'),{target:{value:'15'}});fireEvent.click(screen.getByRole('button',{name:'Save settings'}));
 expect(await screen.findByRole('alert')).toHaveTextContent('Your roadmap changed');expect(screen.getByLabelText('Break minutes per hour')).toHaveValue(15);
});
it('follows system changes only when system mode is selected',()=>{
 let dark=false;let notify=()=>{};vi.stubGlobal('matchMedia',()=>({get matches(){return dark;},addEventListener:(_name:string,fn:()=>void)=>{notify=fn;},removeEventListener:vi.fn()}));
 render(<><ThemePreference/><SettingsPage/></>);expect(document.documentElement.dataset.theme).toBe('light');
 act(()=>{dark=true;notify();});expect(document.documentElement.dataset.theme).toBe('dark');
 fireEvent.change(screen.getByLabelText('Colour mode'),{target:{value:'light'}});expect(localStorage.getItem('elo-appearance')).toBe('light');expect(document.documentElement.dataset.theme).toBe('light');
 act(()=>notify());expect(document.documentElement.dataset.theme).toBe('light');vi.unstubAllGlobals();
});
