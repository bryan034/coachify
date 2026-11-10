"use client";
import Link from 'next/link';
import {useState} from 'react';
export function GettingStarted(){
 const [step,setStep]=useState<'goal'|'cv'>('goal');
 return <section className="page on"><h1>Make elo yours</h1><p>Your background is saved. These next steps are optional.</p>
 {step==='goal'?<section className="card pad"><h2>Do you have a role in mind?</h2><p>Bring a job description, explore a direction, or decide later.</p><div className="row"><Link className="btn pri" href="/career-goal?new=1">Paste a job description</Link><Link className="btn ghost" href="/career-goal/discovery">Explore careers</Link><button className="btn ghost" onClick={()=>setStep('cv')}>Later</button></div></section>:<section className="card pad"><h2>Add your CV</h2><p>Review your experience to build your Skills Profile. You can also start without a CV.</p><div className="row"><Link className="btn pri" href="/cv?upload=1">Upload CV</Link><Link className="btn ghost" href="/cv?chat=manual">Build through chat</Link><Link className="btn ghost" href="/dashboard">Later</Link></div></section>}
 <p><Link href="/dashboard">Go to Home</Link></p></section>;
}
