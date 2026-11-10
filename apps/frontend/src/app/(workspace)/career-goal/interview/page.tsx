"use client";
import {Suspense} from 'react';
import {CareerGoalHome} from '@/features/career/career-overview';
import {useProfile} from '@/features/profile/profile-provider';
import {PageSkeleton} from '@/components/ui/workspace-ui';
export default function CareerGoalInterviewPage(){
 const {account,token}=useProfile();
 return <Suspense fallback={<PageSkeleton label="Opening your career goal…"/>}><CareerGoalHome key={`${account?.id}:${token}`} view="interview"/></Suspense>;
}
