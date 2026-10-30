import { openCvReviewTools, mockEmptyConversation } from '../fixtures/cv-ui';
import {test,expect,type Page} from '@playwright/test';
import {policy,savedCv,emptyDeclarations,clarificationState,confirmedTarget} from '../fixtures/cv';
import type {CvDetail,Declarations} from '../../src/features/cv-ingestion/types';
async function workspace(page:Page){
 await mockEmptyConversation(page);
 await page.addInitScript(()=>{localStorage.setItem('elo.access-epoch','1');sessionStorage.setItem('elo.session',JSON.stringify({token:'synthetic-session',epoch:'1'}));});
 await page.route('**/api/v1/profile**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/auth-config'))return route.fulfill({json:{mode:'email',google_enabled:false}});
  if(path.endsWith('/auth/session'))return route.fulfill({json:{id:'synthetic-account',name:'Synthetic User',email_verified:true,provider:'email'}});
  if(path.endsWith('/school-categories'))return route.fulfill({json:[]});
  return route.fulfill({json:{version:1,onboarding_complete:true,occupational_status:'employed',education:{},education_review_required:false}});
 });
}
test('saved CV upload, explicit selection, correction, declaration and reload',async({page},testInfo)=>{
 await workspace(page);let cvs:CvDetail[]=[savedCv('cv-one')],selection={cv_id:'cv-one',version:1},declarations:Declarations=structuredClone(emptyDeclarations);let failCorrection=true;
 await page.route('**/api/v1/profile/capabilities',route=>{
  if(route.request().method()==='POST'){const body=route.request().postDataJSON();expect(body.expected_version).toBe(declarations.version);declarations={...declarations,version:declarations.version+1,declarations:[...declarations.declarations,{id:'manual-one',name:body.name,description:body.description,skill_id:'manual-skill',provenance:'user_declared',created_at:'2026-10-25T00:00:00Z',updated_at:'2026-10-25T00:00:00Z'}]};}
  return route.fulfill({json:declarations});
 });
 await page.route('**/api/v1/cv{,/**}',route=>{
  const request=route.request(),path=new URL(request.url()).pathname;if(path.includes('/conversations'))return route.fallback();expect(request.headers().authorization).toBe('Bearer synthetic-session');
  if(path.endsWith('/policy'))return route.fulfill({json:policy});
  if(path==='/api/v1/cv')return route.fulfill({json:{cvs,selection}});
  if(path.endsWith('/uploads')){expect(request.headers()['content-type']).toContain('multipart/form-data');const value=savedCv('cv-two');cvs=[...cvs,value];return route.fulfill({status:202,json:value});}
  if(path.endsWith('/selection')){const body=request.postDataJSON();expect(body.expected_version).toBe(selection.version);selection={cv_id:body.cv_id,version:selection.version+1};return route.fulfill({json:selection});}
  if(path.endsWith('/clarifications'))return route.fulfill({json:clarificationState(cvs.find(cv=>cv.id===path.split('/')[4])!)});
  const id=path.split('/')[4],cv=cvs.find(c=>c.id===id)!;
  if(path.includes('/items/')){if(failCorrection){failCorrection=false;return route.fulfill({status:503,json:{detail:'The save was interrupted. Retry safely.'}});}const body=request.postDataJSON();expect(body.expected_version).toBe(cv.version);cv.items=cv.items.map(i=>i.id===path.split('/')[6]?{...i,title:body.title??i.title,description:body.description??i.description,provenance:'user_corrected',removed:body.action==='remove'}:i);cv.version++;cv.effective_version++;}
  return route.fulfill({json:cv});
 });
 await page.goto('/cv');await openCvReviewTools(page);await expect(page.getByLabel('Selected CV',{exact:true})).toContainText('cv-one');
 await page.getByLabel('CV document',{exact:true}).setInputFiles({name:'resume.pdf',mimeType:'application/pdf',buffer:Buffer.from('synthetic fixture; API mocked')});await page.getByRole('button',{name:'Upload CV',exact:true}).click();
 await expect(page.getByLabel('CV cv-two',{exact:true})).toBeVisible();await expect(page.getByLabel('Selected CV',{exact:true})).toContainText('cv-one');
 await page.getByLabel('CV cv-two',{exact:true}).getByRole('button',{name:'Select for analysis'}).click();await expect(page.getByLabel('Selected CV',{exact:true})).toContainText('cv-two');
 await page.getByRole('button',{name:'Edit or remove Team dashboard'}).click();await page.getByRole('textbox',{name:'Description',exact:true}).fill('I cleaned the data. My teammate built the dashboard.');await page.getByRole('button',{name:'Save correction'}).click();await expect(page.getByRole('main').getByRole('alert')).toContainText('interrupted');await expect(page.getByRole('textbox',{name:'Description',exact:true})).toHaveValue('I cleaned the data. My teammate built the dashboard.');await page.getByRole('button',{name:'Save correction'}).click();await expect(page.getByText('Your correction',{exact:true})).toBeVisible();
 await page.getByRole('textbox',{name:'Capability name',exact:true}).fill('Public speaking');await page.getByRole('textbox',{name:'Capability description',exact:true}).fill('I gave three classroom presentations.');await page.getByRole('button',{name:'Add capability',exact:true}).click();await expect(page.getByRole('heading',{name:'Public speaking',exact:true})).toBeVisible();
 await page.reload();await openCvReviewTools(page);await expect(page.getByLabel('Selected CV',{exact:true})).toContainText('cv-two');await expect(page.getByText('I cleaned the data. My teammate built the dashboard.',{exact:true})).toBeVisible();await expect(page.getByRole('heading',{name:'Public speaking',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Edit or remove Team dashboard'}).click();await page.getByRole('button',{name:'Remove this item'}).click();await expect(page.getByRole('heading',{name:'Team dashboard',exact:true})).toHaveCount(0);await expect(page.getByRole('heading',{name:'Public speaking',exact:true})).toBeVisible();
 await page.screenshot({path:testInfo.outputPath('cv-desktop.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.getByRole('button',{name:'Refresh saved status'}).focus();await expect(page.getByRole('button',{name:'Refresh saved status'})).toBeFocused();
 await page.screenshot({path:testInfo.outputPath('cv-mobile.png'),fullPage:true});
 const stored=await page.evaluate(()=>JSON.stringify([Object.entries(localStorage),Object.entries(sessionStorage)]));expect(stored).not.toContain('classroom');expect(stored).not.toContain('teammate');
});

test('failed pending replacement preserves the selected source and offers processing retry',async({page})=>{
 await workspace(page);await page.route('**/api/v1/profile/capabilities',route=>route.fulfill({json:emptyDeclarations}));const first=savedCv('cv-one'),failed={...savedCv('cv-failed'),status:'failed' as const,error:{code:'provider_timeout',message:'Extraction timed out. Retry this file.',retryable:true}};
 await page.route('**/api/v1/cv{,/**}',route=>{const path=new URL(route.request().url()).pathname;if(path.includes('/conversations'))return route.fallback();if(path.endsWith('/policy'))return route.fulfill({json:policy});if(path==='/api/v1/cv')return route.fulfill({json:{cvs:[first,failed],selection:{cv_id:first.id,version:1}}});if(path.endsWith('/clarifications'))return route.fulfill({json:clarificationState(path.includes(first.id)?first:failed)});return route.fulfill({json:path.endsWith(first.id)?first:failed});});
 await page.goto('/cv');await openCvReviewTools(page);await page.getByLabel('CV cv-failed',{exact:true}).getByRole('button',{name:'Review CV'}).click();await expect(page.getByRole('heading',{name:'Processing failed: resume.pdf'})).toBeVisible();await expect(page.getByRole('button',{name:'Retry processing'})).toBeEnabled();await expect(page.getByLabel('Selected CV',{exact:true})).toContainText('cv-one');await expect(page.getByLabel('CV cv-failed',{exact:true}).getByRole('button',{name:'Select for analysis'})).toBeDisabled();
});


test('confirmed target prepares relevant questions and preserves answers and skips after a target change',async({page})=>{
 await workspace(page);await page.route('**/api/v1/profile/capabilities',route=>route.fulfill({json:emptyDeclarations}));
 const cv=savedCv('cv-context');let prepared=false,context={...confirmedTarget};
 const state=()=>({...clarificationState(cv,context,prepared),questions:context.id===confirmedTarget.id?cv.clarifications:[]});
 await page.route('**/api/v1/cv{,/**}',route=>{
  const request=route.request(),path=new URL(request.url()).pathname;if(path.includes('/conversations'))return route.fallback();
  if(path.endsWith('/policy'))return route.fulfill({json:policy});
  if(path==='/api/v1/cv')return route.fulfill({json:{cvs:[cv],selection:{cv_id:cv.id,version:1}}});
  if(path.endsWith('/clarifications/prepare')){const body=request.postDataJSON();expect(body).toMatchObject({expected_version:cv.version,career_target_id:context.id,career_target_version:context.version,career_target_selection_version:context.selection_version});prepared=true;cv.version++;cv.clarifications=[{id:'contribution',item_id:cv.items[0].id,kind:'project',question:'Which Python work was yours?',uncertainty_key:'contribution',status:'unanswered',answer:null,career_target_id:context.id,career_target_version:context.version},{id:'duration',item_id:cv.items[1].id,kind:'other',question:'How long did you use Python?',uncertainty_key:'duration',status:'unanswered',answer:null,career_target_id:context.id,career_target_version:context.version}];return route.fulfill({json:state()});}
  if(path.endsWith('/clarifications'))return route.fulfill({json:state()});
  if(path.includes('/clarifications/')){const body=request.postDataJSON();expect(body.expected_version).toBe(cv.version);const question=cv.clarifications.find(q=>q.id===path.split('/').at(-1))!;question.status=body.action==='skip'?'skipped':'answered';question.answer=body.answer??null;cv.version++;}
  return route.fulfill({json:cv});
 });
 await page.goto('/cv');await openCvReviewTools(page);await expect(page.getByLabel('Confirmed clarification target')).toContainText('Data analyst');await page.getByRole('button',{name:'Prepare relevant questions'}).click();
 const contribution=page.locator('.cv-question').filter({has:page.getByRole('heading',{name:'Which Python work was yours?'})});await contribution.getByRole('textbox',{name:'Your explanation'}).fill('I cleaned the Python data. A teammate designed the dashboard.');await contribution.getByRole('button',{name:'Save explanation'}).click();await expect(contribution.getByRole('button',{name:'Edit explanation'})).toBeVisible();
 const duration=page.locator('.cv-question').filter({has:page.getByRole('heading',{name:'How long did you use Python?'})});await duration.getByRole('button',{name:'Skip and continue'}).click();await expect(duration.getByText(/Skipped.*still uncertain/)).toBeVisible();
 await page.reload();await openCvReviewTools(page);await expect(page.getByText('I cleaned the Python data. A teammate designed the dashboard.',{exact:true})).toBeVisible();await expect(page.getByRole('button',{name:'Answer voluntarily'})).toBeVisible();await expect(page.getByRole('button',{name:'Prepare relevant questions'})).toHaveCount(0);
 context={...context,id:'target-design',selection_version:2,role:'Design researcher',skill_ids:['research']};await page.getByRole('button',{name:'Refresh clarification context'}).click();await expect(page.getByLabel('Confirmed clarification target')).toContainText('Design researcher');await expect(page.getByRole('textbox',{name:'Your explanation'})).toHaveCount(0);await expect(page.getByText('I cleaned the Python data. A teammate designed the dashboard.',{exact:true})).toBeVisible();await expect(page.getByText(/No relevant clarification questions are pending for this target/)).toBeVisible();
});
