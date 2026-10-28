"use client";
import {Suspense} from 'react';
import {CareerGoalHome} from '@/features/career/career-overview';
import {useProfile} from '@/features/profile/profile-provider';
export default function CareerGoalPage(){
 const {account,token}=useProfile();
 return <Suspense fallback={<p role="status">Opening your career goal…</p>}><CareerGoalHome key={`${account?.id}:${token}`}/></Suspense>;
}
