import type {InterviewBrief,RoleBrief} from '../../src/lib/api/career';

const site=(n:number,title:string,domain:string)=>({index:n,title,domain,url:`https://example.test/source-${n}`});

export const roleBrief:RoleBrief={
 researchedAt:'2026-11-21T08:00:00Z',sourceCount:7,
 summary:'A hybrid GenAI delivery internship. Mentorship reviews are mixed, management reviews are weak, and a return offer is possible.',
 facts:[
  {label:'Who can apply',value:'Graduating 2026 or 2027',note:'From the job description',citations:[1]},
  {label:'Work setup',value:'Hybrid',note:'About 2 office days a week',citations:[2]},
  {label:'Reviews',value:'Mixed',note:'Strong teams, weak management',citations:[3,4]},
  {label:'After the internship',value:'Return offer possible',note:'Subject to business need',citations:[]},
 ],
 duties:['Coordinate GenAI project timelines and stand-ups','Work with internal teams, partners and vendors','Run events and workshops on AI solutions','Write status reports on progress and metrics','Join innovation discussions on health technology','Draft internal updates and social posts'],
 topics:[
  {id:'mentorship',title:'Mentorship',tone:'mixed',takeaway:'Good when your team has time, thin when it is busy.',estimated:false,conflicting:true,reports:[
   {text:'A data analyst intern said busy full-time staff had limited time to mentor.',citations:[2]},
   {text:'An intern praised supervisors for mentorship and career advice.',citations:[5]}]},
  {id:'hours',title:'Hours and workload',tone:'positive',takeaway:'Flexible days, about two in the office each week.',estimated:false,conflicting:false,reports:[
   {text:'A data analyst intern reported flexible workdays with two office days a week.',citations:[2]}]},
  {id:'management',title:'Management',tone:'negative',takeaway:'Reviews flag weak delegation and few standard processes.',estimated:false,conflicting:false,reports:[
   {text:'An employee review site rates management 1.5 out of 5 across 10 reviews.',citations:[3]},
   {text:'A July 2025 intern review cited poor management and task delegation.',citations:[4]},
   {text:'A business analyst review cited a lack of standard procedures.',citations:[6]}]},
  {id:'team',title:'Team and culture',tone:'mixed',takeaway:'Often close-knit, but varies a lot by department.',estimated:true,conflicting:false,reports:[]},
 ],
 pay:[
  {label:'Intern pay',value:'S$1,799/mo',caveat:'A related analyst listing, 2024.',citations:[6]},
  {label:'Full-time estimate',value:'S$5.1k–7k/mo',caveat:'A salary site estimate. Not an offer.',citations:[7]},
  {label:'Return offer',value:'Possible',caveat:'Through a graduate programme with no analyst track.',citations:[]},
 ],
 notFound:['Benefits','Typical projects','Conversion rate','Intake size'],
 sources:[site(1,'GenAI Intern job description','Example Health'),site(2,'Encouraging and collaborative team','Glassdoor'),site(3,'Employee reviews about management','Indeed'),
  site(4,'Example Health intern reviews','Glassdoor'),site(5,'Internship post','LinkedIn'),site(6,'Business Analyst Intern salaries','Levels.fyi'),site(7,'Business Analyst salary estimate','JobStreet')],
};

export const interviewBrief:InterviewBrief={
 researchedAt:'2026-11-21T08:00:00Z',sourceCount:6,
 summary:'One short, friendly call with the team manager. Expect questions about you and how you work, not a technical test.',
 process:[
  {step:1,title:'Apply',when:'About 6 months before start',detail:'Applications open with school internship periods.',citations:[1]},
  {step:2,title:'HR call',when:'Reported',detail:'A short screening call.',citations:[2]},
  {step:3,title:'Manager interview',when:'Reported',detail:'Short and online, with the team manager.',citations:[3]},
 ],
 difficulty:{level:'average',estimated:true,reason:'Coordination, communication and health technology scenarios.'},
 questions:[
  {question:'Tell me about yourself and why this team.',prep:'Write a 60-second intro linking your interests to health technology and GenAI.',estimated:true},
  {question:'Which project best shows your planning skills?',prep:'Pick one project. Outline your role, what you did and the result.',estimated:true},
  {question:'How do you keep a team aligned on a project?',prep:'Review stand-ups, timelines and how you tracked progress before.',estimated:true},
  {question:'How would you handle an unhappy stakeholder?',prep:'Practise a delay scenario: acknowledge, reset the plan, follow up.',estimated:true},
 ],
 candidateReports:{
  askedAbout:[{label:'Yourself',citations:[3]},{label:'Past projects',citations:[3]},{label:'Teamwork',citations:[3]},{label:'Work experience',citations:[6]}],
  situational:{text:'How would you handle a client unhappy with the developers?',citations:[4]},
  tone:{text:'Quick, friendly and informal. No technical round.',citations:[5]},
  reports:[
   {text:'An intern candidate was asked about themselves and past projects.',citations:[3]},
   {text:'A candidate was asked how they would handle a client unhappy with developers.',citations:[4]},
   {text:'An intern candidate described a quick, friendly, informal chat with no technical interview.',citations:[5]},
   {text:'An analyst candidate was asked about work experience and situational questions.',citations:[6]}],
 },
 notFound:['Assessment centre','Offer timeline'],
 sources:[site(1,'Students and graduates FAQs','Example Health'),site(2,'Intern interview questions','Glassdoor'),site(3,'Internship interview questions','Glassdoor'),
  site(4,'Business Analyst interview questions','Glassdoor'),site(5,'Working experience and situational questions','Glassdoor'),site(6,'Employee reviews','Indeed')],
};
