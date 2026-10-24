import React from 'react';
import { render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import { HomeDashboard } from './home';
import { ProfileProvider } from '@/features/profile/profile-provider';

test.each([
 { status: 'student', currentYear: 6, expected: 'Computing & Design · Year 6' },
 { status: 'employed', currentYear: null, expected: 'Computing & Design' },
])('Home shows independent education fields for $status without inventing a current year', async ({status,currentYear,expected})=>{
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>new Response(JSON.stringify(
  url.endsWith('/auth/session') ? {id:'synthetic',name:'Synthetic',provider:'local_test',onboarding_complete:false} : url.endsWith('/auth-config') ? {mode:'local_test'} : url.endsWith('/school-categories') ? [] : {
   version:1,occupational_status:status,school_category:'university',current_study_year:currentYear,
   education_review_required:false,education:{course:'Computing & Design',study_year:6},
  }
 ))));
 render(<ProfileProvider><HomeDashboard/></ProfileProvider>);
 const detail=await screen.findByText(expected,{exact:true});
 expect(detail).toBeInTheDocument();
 if(!currentYear) expect(screen.queryByText(/Year 6/)).not.toBeInTheDocument();
 expect(screen.queryByText('Ethan')).not.toBeInTheDocument();
});
