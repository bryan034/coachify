"use client";
import {createContext,useContext,useState,type ReactNode} from 'react';
import type {JDReview} from '@/lib/api/career';
export type SelectedJD={text:string;kind:'text'|'url'|'document';name:string;url?:string|null};
type Session={jdReview:JDReview|null;setJDReview:(value:JDReview|null)=>void;jd:SelectedJD|null;jdKey:string|null;chooseJD:(value:SelectedJD|null)=>void;attachment:{draftId:string;text:string;name:string}|null;setAttachment:(value:{draftId:string;text:string;name:string}|null)=>void};
const Context=createContext<Session|null>(null);
export function CareerSessionProvider({children}:{children:ReactNode}){
 const [jdReview,setJDReview]=useState<JDReview|null>(null);
 const [jd,setJD]=useState<SelectedJD|null>(null),[jdKey,setJDKey]=useState<string|null>(null);const [attachment,setAttachment]=useState<Session['attachment']>(null);
 function chooseJD(value:SelectedJD|null){if(value&&(!value.text.trim()||Array.from(value.text).length>8000))throw new Error('Use a job description of up to 8,000 characters.');if(value?.text!==jd?.text||value?.url!==jd?.url||value?.kind!==jd?.kind){setJDReview(null);setJDKey(value?crypto.randomUUID():null);}setJD(value);}
 return <Context.Provider value={{jd,jdKey,jdReview,setJDReview,chooseJD,attachment,setAttachment}}>{children}</Context.Provider>;
}
export function useCareerSession(){const value=useContext(Context);if(!value)throw new Error('Career session provider is required.');return value;}
