import {careerApi} from './career';

export type CvGoalConfirmation = {
 goal_id:string|null; goal_version:number|null; selection_version:number;
 confirmed:boolean; context:({id:string;version:number;selection_version:number;confirmed:true}&Record<string,unknown>)|null;
 reason:string|null;
};
export type ConfirmCvGoal = {expected_goal_id:string;expected_goal_version:number;expected_selection_version:number;mutation_id:string};
const object=(value:unknown):value is Record<string,unknown>=>typeof value==='object'&&value!==null&&!Array.isArray(value);
const integer=(value:unknown):value is number=>Number.isSafeInteger(value)&&Number(value)>=0;
function confirmation(value:unknown):CvGoalConfirmation {
 if(!object(value)||!(value.goal_id===null||typeof value.goal_id==='string'&&/^[a-f0-9]{24}$/.test(value.goal_id))||!(value.goal_version===null||integer(value.goal_version)&&value.goal_version>0)||!integer(value.selection_version)||typeof value.confirmed!=='boolean'||!(value.reason===null||typeof value.reason==='string')||(value.goal_id===null)!==(value.goal_version===null))throw new Error('Career returned an incomplete confirmation. Reload your saved goal before confirming it.');
 if(value.confirmed){
  const context=value.context;
  if(!object(context)||context.confirmed!==true||context.id!==value.goal_id||context.version!==value.goal_version||context.selection_version!==value.selection_version)throw new Error('Career returned an incomplete confirmation. Reload your saved goal before confirming it.');
 }else if(value.context!==null)throw new Error('Career returned an incomplete confirmation. Reload your saved goal before confirming it.');
 return value as CvGoalConfirmation;
}
export async function getCvGoalConfirmation(token:string,signal:AbortSignal){return confirmation(await careerApi<unknown>('/goals/current/cv-confirmation',token,{signal}));}
export async function confirmCvGoal(body:ConfirmCvGoal,token:string,signal:AbortSignal){return confirmation(await careerApi<unknown>('/goals/current/cv-confirmation',token,{method:'POST',body:JSON.stringify(body),signal}));}
