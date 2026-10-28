// Shared synthetic API fixtures project one goal and separate progress/evidence reads.
type Json=Record<string,any>;
const reports=new Map<string,Json>();
let latest:Json|undefined;
function publicReport(goalId:string,record:Json={},researchId='000000000000000000000091'){
 const category=()=>({status:'completed',findings:[],missing_fields:[],warnings:[],error_code:null,researched_at:'2026-10-28T00:00:00Z'});
 const findings:Json[]=[];
 if(record.process?.round_count!=null)findings.push({field:'recruitment_stages',value:`Reported interview rounds: ${record.process.round_count}.`,source_ids:record.process.round_count_evidence?.source_ids||[]});
 for(const stage of record.process?.stages||[])findings.push({field:'recruitment_stages',value:[stage.name,stage.assessment_type].filter(Boolean).join(' · '),source_ids:stage.evidence?.source_ids||['s1']});
 for(const skill of record.skills||[])findings.push({field:'preparation_topics',value:[skill.name,skill.interview_stage,skill.assessment_type].filter(Boolean).join(' · '),source_ids:skill.source_ids||[]});
 const categories=record.intelligence?.categories||Object.fromEntries(['interview_intelligence','internship_insights','career_progression','conversion_outcomes','company_intelligence'].map(key=>[key,{...category(),findings:key==='interview_intelligence'?findings.map((f,i)=>({...f,finding_id:'f'+String(i+1).padStart(16,'0'),confidence:'medium',evidence_type:'candidate_reported',scope:'exact',conflict_group:null,last_verified_at:'2026-10-28T00:00:00Z',quotes:[record.sources?.[0]?.evidence||f.value]})):[]} ]));
 return {available:true,job_id:'synthetic-job',career_target_id:goalId,research_id:researchId,status:'completed',finished:true,categories,sources:record.sources||[],summary:record.intelligence?.summary||{},error_code:null,updated_at:'2026-10-28T00:00:00Z'};
}
function goalResponse(review:Json){return {current:{goal:{...review.extraction,_id:review.review_id,version:review.version,target_type:review.target_type||'specific_job',requirements_need_review:review.requirements_need_review||false}}};}
function canonical(value:Json):Json{
 if(value.review?.extraction){
  const goal=goalResponse(value.review).current.goal;
  const report=publicReport(goal._id,value.research||{},value.research?._id);
  if(['researching','research_pending','waiting_quota'].includes(value.phase)){report.status='pending';report.finished=false;for(const category of Object.values(report.categories) as Json[])category.status='pending';}
  report.updated_at=value.phase+':'+value.revision;
  reports.set(goal._id,report);
  const {review,research,...rest}=value;
  const workspace={...rest,current:{...value.current,goal},research_id:value.phase==='ready'?report.research_id:null,research_version:value.phase==='ready'?1:null};
  latest=workspace;return workspace;
 }
 if(value.current?.goal&&value.phase){latest=value;return value;}
 if(value.current?.goal)return value;
 if(value.review_id&&value.extraction)return goalResponse(value);
 if(value.phase==='empty'){const {review,research,...rest}=value;return {...rest,current:{goal:null,selection_version:0}};}
 if(value.session)return {...value,session:{...value.session,review:value.session.review?goalResponse(value.session.review):null}};
 if(value.workspace)return {...value,workspace:canonical(value.workspace)};
 if(value.result)return {...value,result:canonical(value.result)};
 return value;
}
export function careerFixture(url:string,input:Json):Json{
 const parsed=new URL(url),path=parsed.pathname;
 if(!path.includes('/career/'))return input;
 const value=canonical(input),goalId=path.match(/\/goals\/([^/]+)/)?.[1]||latest?.current?.goal?._id;
 if(path.endsWith('/goals/current/cv-confirmation')){
  const current=value.current?.goal?value.current:latest?.current,goal=current?.goal;
  return {goal_id:goal?._id||null,goal_version:goal?.version||null,selection_version:current?.selection_version||0,confirmed:false,context:null,reason:goal?null:'Save a career goal before confirming it for CV review.'};
 }
 if(path.endsWith('/workspace/summary')){
  const goal=(value.current?.goal?value:latest)?.current?.goal;
  if(!goal)throw new Error('Summary fixture requires a saved goal');
  const report=reports.get(goal._id)||publicReport(goal._id);
  const labels:Record<string,string>={interview_intelligence:'Interview findings',internship_insights:'Internship experience',career_progression:'Career progression and conversion salary',conversion_outcomes:'Historical full-time conversion rates',company_intelligence:'Company and team culture'};
  return {reply:[
   '## Your career goal',`Let’s look at ${goal.role}${goal.company?' at '+goal.company:''}.`,
   goal.location?`**Location:** ${goal.location}`:'',
   '### Role overview',goal.summary||'',...(goal.responsibilities||[]).map((v:string)=>'- '+v),
   '### Skills for this role',...(goal.skills||[]).map((v:Json)=>`- **${v.name}** — ${v.priority}`),
   ...(goal.non_skill_requirements?.length?['### Qualifications and conditions',...goal.non_skill_requirements.map((v:Json)=>'- '+v.description)]:[]),
   ...Object.entries(report.categories as Record<string,Json>).flatMap(([key,category])=>[
    '### '+labels[key],...(category.findings||[]).map((finding:Json)=>'- '+finding.value+' '+(report.sources||[]).filter((s:Json)=>finding.source_ids.includes(s.source_id)).map((s:Json)=>`[Source](${s.url})`).join(' ')),
   ]),
   'What would you like clarified or researched next?',
  ].filter(Boolean).join('\n\n')};
 }
 if(path.includes('/opportunity-research')){
  let report:Json=value.categories?value:reports.get(goalId)||publicReport(goalId);
  if(value.categories)reports.set(goalId,report);
  if(path.includes('/evidence')){
   const findingId=path.match(/\/findings\/([^/]+)/)?.[1];
   const finding=Object.values(report.categories as Record<string,Json>).flatMap(c=>c.findings||[]).find(f=>f.finding_id===findingId);
   return {finding_id:findingId,quotes:finding?.quotes||[],sources:report.sources||[]};
  }
  if(path.endsWith('/progress'))return {status:report.status,finished:report.finished??true,result_version:report.updated_at||'fixture-v1',categories:Object.fromEntries(Object.entries(report.categories).map(([k,v])=>[k,{status:(v as Json).status,error_code:(v as Json).error_code}]))};
  report={...report,research_id:parsed.searchParams.get('research_id')||report.research_id,career_target_id:goalId};
  const {research,...rest}=report;
  return {...rest,sources:(report.sources||[]).map(({evidence,...s}:Json)=>s),categories:Object.fromEntries(Object.entries(report.categories).map(([k,v])=>[k,{...(v as Json),findings:((v as Json).findings||[]).map(({quotes,...f}:Json)=>f)}]))};
 }
 if(path.endsWith('/workspace/progress')){
  const state=value.phase?value:latest;
  return {session_id:state?.session_id,revision:state?.revision,goal_id:state?.current?.goal?._id,selection_version:state?.current?.selection_version,phase:state?.phase,activities:state?.activities||[],research_id:state?.research_id,error:state?.error,error_code:state?.error_code,retry_after:state?.retry_after};
 }
 return value;
}
