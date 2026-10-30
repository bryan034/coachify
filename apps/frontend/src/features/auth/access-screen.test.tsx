import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import { ApiError } from '@/lib/api/profile';
import { AccessScreen } from './access-screen';

const access = vi.hoisted(()=>({
 mode: 'email', googleEnabled: false, verification: null, account: null, profile: null,
 loading: false, configError: '', loadError: '', logoutError: '',
 beginAccess: vi.fn(), completeAccess: vi.fn(), cancelAccess: vi.fn(),
 reload: vi.fn(), signOut: vi.fn(), retryLogout: vi.fn(),
}));
const navigation = vi.hoisted(()=>({pathname:'/login'}));
vi.mock('@/features/profile/profile-provider',()=>({useProfile:()=>access}));
vi.mock('next/navigation',()=>({usePathname:()=>navigation.pathname,useRouter:()=>({replace:vi.fn()})}));

beforeEach(()=>{
 vi.clearAllMocks();
 navigation.pathname='/login';
 access.beginAccess.mockResolvedValue({nonce:'synthetic-nonce'});
});

async function signIn() {
 render(<AccessScreen intent="login"/>);
 fireEvent.change(screen.getByLabelText('Email address'),{target:{value:'new@example.test'}});
 fireEvent.change(screen.getByLabelText('Password'),{target:{value:'Test1234'}});
 await waitFor(()=>expect(screen.getByRole('button',{name:/^Sign in/})).toBeEnabled());
 fireEvent.click(screen.getByRole('button',{name:/^Sign in/}));
 return screen.findByRole('alert');
}

test('an unknown email offers a direct create-account link without redirecting away from the message',async()=>{
 access.completeAccess.mockRejectedValue(new ApiError('No account was found for this email address. Create a new account to get started.',404));
 const alert=await signIn();
 expect(alert).toHaveTextContent('No account was found for this email address.');
 const create=within(alert).getByRole('link',{name:'Create new account'});
 expect(create).toHaveAttribute('href','/register');
 expect(screen.getByLabelText('Email address')).toHaveValue('new@example.test');
 create.addEventListener('click',event=>event.preventDefault());
 fireEvent.click(create);
 expect(access.cancelAccess).toHaveBeenCalled();
});

test.each([401,503])('a %s error retains sign-in recovery without a missing-account claim',async(status)=>{
 access.completeAccess.mockRejectedValue(new ApiError(status===401?'Email or password is incorrect.':'Account storage unavailable.',status));
 const alert=await signIn();
 expect(within(alert).queryByRole('link',{name:'Create new account'})).not.toBeInTheDocument();
 expect(within(alert).getByRole('button',{name:'Start again'})).toBeEnabled();
 expect(screen.getByRole('link',{name:'Forgot password?'})).toHaveAttribute('href','/forgot-password');
});

test('registration allows eight characters and blocks seven before submission',async()=>{
 navigation.pathname='/register';
 access.completeAccess.mockResolvedValue(false);
 render(<AccessScreen intent="register"/>);
 fireEvent.change(screen.getByLabelText('Email address'),{target:{value:'synthetic@example.test'}});
 const password=screen.getByLabelText('Password');
 expect(password).toHaveAttribute('minlength','8');
 expect(password).toHaveAttribute('maxlength','128');
 fireEvent.change(password,{target:{value:'Test123'}});
 expect(screen.getByRole('button',{name:/^Create account/})).toBeDisabled();
 fireEvent.change(password,{target:{value:'Test1234'}});
 await waitFor(()=>expect(screen.getByRole('button',{name:/^Create account/})).toBeEnabled());
 fireEvent.click(screen.getByRole('button',{name:/^Create account/}));
 await waitFor(()=>expect(access.completeAccess).toHaveBeenCalledWith({name:'',email:'synthetic@example.test',password:'Test1234'}));
});
