import type {IntelligenceFinding,IntelligenceResult,ResearchSource} from '../../src/lib/api/career';

export const interviewResearchSources:ResearchSource[]=Array.from({length:7},(_,i)=>({
 source_id:`interview-source-${i+1}`,platform:'other',url:`https://example.test/interview-${i+1}`,title:`Interview report ${i+1}`,
 published_date:null,reported_date:null,role_match:'exact',reliability:'anecdotal',report_group:null,
}));

function finding(field:string,value:string,source:number,extra:Partial<IntelligenceFinding>={}):IntelligenceFinding{
 return {finding_id:`f${String(source).padStart(16,'0')}`,field,value,source_ids:[`interview-source-${source}`],
  confidence:'medium',evidence_type:'candidate_reported',scope:'exact',conflict_group:null,last_verified_at:'2026-11-21T08:00:00Z',...extra};
}

export const interviewResearch:IntelligenceResult={
 status:'completed',error_code:null,missing_fields:[],warnings:[],researched_at:'2026-11-21T08:00:00Z',expires_at:null,
 searches:7,model_calls:2,latency_ms:100,estimated_cost_usd:null,
 findings:[
  finding('recruitment_stages','An **HR call** followed by a **technical interview**.',1),
  finding('application_timeline','Replies arrived within **two weeks**.',2),
  finding('round_format','An online call with the hiring manager.',3,{round_number:2,round_name:'Technical interview'}),
  finding('difficulty','**Moderate** difficulty, with practical questions about past projects.',4),
  finding('interview_questions','How did you organise your previous project, handle conflicting requirements, and explain the final technical decisions to other teams?',5,{round_number:2,round_name:'Technical interview'}),
  finding('preparation_topics','Explain the core concepts of **SQL joins** and practise discussing your project decisions.',6,{round_number:2,round_name:'Technical interview'}),
  finding('candidate_experience','The interviewer asked follow-up questions about project trade-offs and gave the candidate time to explain the reasoning behind each decision in detail.',7),
  finding('round_format','A short HR call about motivation and availability.',1,{finding_id:'f0000000000000008',round_number:1,round_name:'HR call'}),
  finding('preparation_topics','Review your motivation for the role and confirm your availability.',2,{finding_id:'f0000000000000009',round_number:1,round_name:'HR call'}),
  finding('round_format','A final discussion with the department lead.',7,{finding_id:'f0000000000000010',round_number:3,round_name:'Final interview'}),
 ],
};
