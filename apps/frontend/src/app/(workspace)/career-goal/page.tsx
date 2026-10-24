"use client";
import { CareerGoal } from '@/features/career/career-goal';
import { useProfile } from '@/features/profile/profile-provider';
export default function CareerGoalPage() {
 const { account, token } = useProfile();
 return <CareerGoal key={`${account?.id}:${token}`} />;
}
