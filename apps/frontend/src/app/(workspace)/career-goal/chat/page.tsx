"use client";
import {Suspense} from 'react';
import {CareerChat} from '@/features/career/career-chat';
export default function CareerChatPage(){return <Suspense fallback={<p role="status">Opening your conversation…</p>}><CareerChat/></Suspense>;}
