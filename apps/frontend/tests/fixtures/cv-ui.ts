import { expect, type Page } from '@playwright/test';
import { emptySkillList } from './cv';

export async function mockEmptyConversation(page: Page) {
  await page.route('**/api/v1/assessments/**', route => route.fulfill({json:{version:0,stale:false,ready:false,model_available:true,result:null,operation:null,issues:[]}}));
  await page.route(url => url.pathname === '/api/v1/cv/skills', route => {
    const cvId = new URL(route.request().url()).searchParams.get('cv_id');
    return route.fulfill({json: {...emptySkillList, cv_id: cvId, cv_version: cvId ? 1 : null}});
  });
  const saved = new Map<string, object>();
  await page.route('**/api/v1/cv/conversations{,/**}', route => {
    const request = route.request(), url = new URL(request.url());
    if (request.method() === 'POST' && url.pathname.endsWith('/conversations')) {
      const cvId = request.postDataJSON().cv_id as string | null;
      const id = `conversation-${cvId ?? 'manual'}`;
      const conversation = {id, cv_id: cvId, revision: 1, read_only: false,
        previous_conversation_id: null, active_question: null, context: null,
        messages: [], next_before: null, limits: {max_message_chars: 4000, max_messages: 500}};
      saved.set(id, conversation);
      return route.fulfill({json: conversation});
    }
    const id = url.pathname.split('/')[5];
    if (saved.has(id)) return route.fulfill({json: saved.get(id)});
    return route.fulfill({json: {conversations: []}});
  });
}

export async function openCvLibrary(page: Page) {
  await expect(page.getByLabel('Selected CV', {exact:true})).toContainText(/No active CV yet|Active CV:/);
  await expect(page.getByRole('heading', {name:'Your CVs', exact:true})).toBeVisible();
}

export async function openCvReviewTools(page: Page) {
  await expect(page.locator('.cv-workspace')).toHaveAttribute('aria-busy','false');
  const review = new URL(page.url()).searchParams.get('review');
  if (review) {
    if (await page.getByRole('region',{name:'CV conversation',exact:true}).count()) {
      await expect(page.getByRole('textbox',{name:'Message elo',exact:true})).toBeEnabled({timeout:35_000});
      await expect(page.locator('.cv-chat-action-pending')).toHaveCount(0,{timeout:35_000});
    }
    await page.getByRole('button', {name:review === 'manual' ? 'Back to Skills Profile' : 'Save and review later', exact:true}).click();
  }
  const uploadNew = page.getByRole('button', {name:'Upload new CV', exact:true});
  await expect(uploadNew.or(page.getByLabel('CV document', {exact:true})).first()).toBeVisible();
  if (await uploadNew.count()) await uploadNew.click();
  await expect(page.getByLabel('CV document', {exact:true})).toBeVisible();
  if(await page.getByRole('heading',{name:'Your CVs',exact:true}).count())await openCvLibrary(page);
  await expect(page.getByText('Loading saved CVs…', {exact: true})).toHaveCount(0);
  const tools=page.getByRole('button',{name:'Review details and corrections',exact:true});
  if(await tools.count()&&await tools.getAttribute('aria-expanded')==='false')await tools.click();
  await expect(page.locator('summary').filter({hasText: 'CV details and corrections'})).toHaveCount(0);
}
