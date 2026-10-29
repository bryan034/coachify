import { expect, type Page } from '@playwright/test';

/** An empty saved transcript keeps older boundary journeys focused on their original behavior. */
export async function mockEmptyConversation(page: Page) {
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

/** Existing review tools now live behind explicit disclosures in the chat workspace. */
export async function openCvReviewTools(page: Page) {
  await expect(page.locator('summary').filter({hasText: 'CV files'})).toHaveCount(1);
  // The initial empty-list response opens CV files automatically. Wait for that
  // transition before clicking, otherwise a click can close the newly opened panel.
  await expect(page.getByText('Loading saved CVs…', {exact: true})).toHaveCount(0);
  for (const label of ['CV files', 'Your CV summary']) {
    const summary = page.locator('summary').filter({hasText: label});
    await expect(summary).toHaveCount(1);
    const details = summary.locator('..');
    if (await details.getAttribute('open') === null) await summary.click();
    await expect(details).toHaveAttribute('open', '');
  }
}
