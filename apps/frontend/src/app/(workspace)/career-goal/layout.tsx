"use client";
import type {ReactNode} from 'react';
import {useProfile} from '@/features/profile/profile-provider';
import {CareerSessionProvider} from '@/features/career/career-session';
export default function CareerLayout({children}:{children:ReactNode}){
 const {account,token}=useProfile();
 return <CareerSessionProvider key={`${account?.id}:${token}`}>{children}</CareerSessionProvider>;
}
