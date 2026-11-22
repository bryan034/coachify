import type {IntelligenceCategory,IntelligenceFinding,IntelligenceResult,ResearchSource} from '../../src/lib/api/career';

export const roleGoal={
 requirements:['Currently enrolled in a degree programme, graduating in December 2026 or May 2027, with experience coordinating projects.'],
 duties:['Coordinate project timelines and stand-ups across delivery teams, track dependencies, and communicate changes to project stakeholders.',
  'Work with internal teams, partners and vendors','Run events and workshops on AI solutions','Write status reports on progress and metrics',
  'Join innovation discussions on health technology','Draft internal updates and social posts'],
};
export const roleResearchSources:ResearchSource[]=Array.from({length:7},(_,i)=>({
 source_id:`role-source-${i+1}`,platform:'other',url:`https://example.test/role-${i+1}`,title:`Role report ${i+1}`,
 published_date:null,reported_date:null,role_match:'exact',reliability:'anecdotal',report_group:null,
}));

let nextId=0;
function finding(field:string,value:string,source:number,extra:Partial<IntelligenceFinding>={}):IntelligenceFinding{
 return {finding_id:`f${String(++nextId).padStart(16,'0')}`,field,value,source_ids:[`role-source-${source}`],
  confidence:'medium',evidence_type:'candidate_reported',scope:'exact',conflict_group:null,last_verified_at:'2026-11-21T08:00:00Z',...extra};
}
function category(findings:IntelligenceFinding[]):IntelligenceResult{
 return {status:'completed',error_code:null,missing_fields:[],warnings:[],researched_at:'2026-11-21T08:00:00Z',expires_at:null,
  searches:4,model_calls:2,latency_ms:100,estimated_cost_usd:null,findings};
}
export const roleResearch:Partial<Record<IntelligenceCategory,IntelligenceResult>>={
 internship_insights:category([
  finding('projects','An intern helped coordinate a cross-team delivery project.',1),
  finding('benefits','Interns reported **paid leave** during the programme.',2),
  finding('mentorship','A data analyst intern said busy full-time staff had limited time to mentor and provided little feedback during the first month of their placement.',3,{conflict_group:'mentorship'}),
  finding('mentorship','Another intern praised the supervisors for mentorship and career advice.',4,{conflict_group:'mentorship'}),
  finding('work_life_balance','Interns reported flexible workdays with two office days each week.',4),
  finding('compensation','Reported intern pay was **S$1,799/mo** for a related analyst role in 2024.',6,{scope:'related_role',confidence:'low'}),
 ]),
 company_intelligence:category([
  finding('company_culture','Employees described a collaborative company culture.',5),
  finding('team_culture','The project team worked closely with other departments.',5,{evidence_type:'inferred'}),
  finding('management','A July 2025 intern review cited weak delegation and unclear processes.',6),
  finding('work_life_balance','Employees reported longer hours near major project deadlines.',7),
 ]),
 career_progression:category([
  finding('full_time_role','Interns reported a full-time graduate programme after the placement.',6),
  finding('career_path','A former intern progressed into a business analyst role.',7),
  finding('conversion_salary','Related graduate roles reportedly paid S$5,000/mo in 2025.',7,{scope:'related_role'}),
 ]),
 conversion_outcomes:category([
  finding('conversion_rate','A reported 2025 cohort conversion rate was 50%.',7),
  finding('historical_cohort','The reported 2025 cohort had twenty interns.',7),
  finding('offer_acceptance','Some interns declined their return offers to pursue further study.',7),
 ]),
};
