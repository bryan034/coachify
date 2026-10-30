import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { PasswordRecovery } from './password-recovery';
vi.mock('./access-screen', () => ({ AccessFrame: ({ children }: {children: React.ReactNode}) => <main>{children}</main> }));
afterEach(()=>vi.unstubAllGlobals());

test('requests an emailed code, retains inputs on failure, and finishes without signing in', async()=>{
 let fail = true;
 const fetch = vi.fn(async (url: string)=>{
  if (url.endsWith('/forgot-password')) return new Response(JSON.stringify({challenge_id:'synthetic-challenge',message:'If an email/password account exists for this address, we sent a password reset code.'}));
  return fail ? new Response(JSON.stringify({detail:'Reset code incorrect or expired.'}),{status:400}) : new Response(JSON.stringify({ok:true}));
 });
 vi.stubGlobal('fetch', fetch);
 render(<PasswordRecovery/>);
 fireEvent.change(screen.getByLabelText('Email address'),{target:{value:'synthetic@example.test'}});
 fireEvent.click(screen.getByRole('button',{name:'Send reset code'}));
 await screen.findByLabelText('Reset code');
 fireEvent.change(screen.getByLabelText('Reset code'),{target:{value:'123456'}});
 expect(screen.getByLabelText('New password')).toHaveAttribute('minlength','8');
 fireEvent.change(screen.getByLabelText('New password'),{target:{value:'Reset123'}});
 fireEvent.click(screen.getByRole('button',{name:'Reset password'}));
 expect(await screen.findByRole('alert')).toHaveTextContent('Reset code incorrect or expired.');
 expect(screen.getByLabelText('New password')).toHaveValue('Reset123');
 fail = false;
 fireEvent.click(screen.getByRole('button',{name:'Reset password'}));
 await waitFor(()=>expect(screen.getByRole('status')).toHaveTextContent('Your password has been reset.'));
 expect(screen.queryByLabelText('New password')).not.toBeInTheDocument();
 expect(screen.getByRole('link',{name:'Back to sign in'})).toHaveAttribute('href','/login');
 expect(fetch.mock.calls.map(([url])=>url)).toEqual(['/api/v1/profile/auth/forgot-password','/api/v1/profile/auth/reset-password','/api/v1/profile/auth/reset-password']);
});

test('failed delivery allows retry without losing the email', async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({detail:'Email delivery unavailable.'}),{status:503})));
 render(<PasswordRecovery/>);
 fireEvent.change(screen.getByLabelText('Email address'),{target:{value:'synthetic@example.test'}});
 fireEvent.click(screen.getByRole('button',{name:'Send reset code'}));
 expect(await screen.findByRole('alert')).toHaveTextContent('Email delivery unavailable.');
 expect(screen.getByLabelText('Email address')).toHaveValue('synthetic@example.test');
 expect(screen.getByRole('button',{name:'Send reset code'})).toBeEnabled();
});
