import {act,fireEvent,render,screen} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {WorkspaceActivity,IDLE_LIMIT} from './workspace-activity';
vi.mock('@/features/profile/profile-provider',()=>({useProfile:()=>({token:'fixture',sessionError:'',signOut:vi.fn()})}));
afterEach(()=>vi.useRealTimers());
it('keeps unsaved input mounted during tab switches and locks at five minutes',()=>{
 vi.useFakeTimers();render(<WorkspaceActivity><input aria-label="Draft" defaultValue="Private unsaved draft"/></WorkspaceActivity>);
 Object.defineProperty(document,'visibilityState',{configurable:true,value:'hidden'});
 fireEvent(document,new Event('visibilitychange'));
 act(()=>vi.advanceTimersByTime(IDLE_LIMIT-1000));
 expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
 Object.defineProperty(document,'visibilityState',{configurable:true,value:'visible'});
 fireEvent(document,new Event('visibilitychange'));
 expect(screen.getByLabelText('Draft')).toHaveValue('Private unsaved draft');
 act(()=>vi.advanceTimersByTime(1000));
 expect(screen.getByRole('alertdialog')).toHaveTextContent('Refresh required');
 expect(screen.getByLabelText('Draft')).toHaveValue('Private unsaved draft');
 fireEvent.keyDown(window,{key:'a'});expect(screen.getByRole('alertdialog')).toBeVisible();
});
it('visible user activity renews the inactivity deadline',()=>{
 vi.useFakeTimers();render(<WorkspaceActivity><input aria-label="Draft"/></WorkspaceActivity>);
 act(()=>vi.advanceTimersByTime(IDLE_LIMIT-1000));fireEvent.keyDown(window,{key:'a'});
 act(()=>vi.advanceTimersByTime(2000));expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
 act(()=>vi.advanceTimersByTime(IDLE_LIMIT));expect(screen.getByRole('alertdialog')).toBeVisible();
});
