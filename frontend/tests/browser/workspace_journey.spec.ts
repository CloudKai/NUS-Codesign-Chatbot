/** Student authoring, coaching, and recovery through the production-built reader. */
import { expect, test, type Page } from '@playwright/test';
import { startStack, tempWorkspace, type Stack } from './stack';

let stack: Stack;
test.beforeAll(async () => { stack = await startStack(tempWorkspace('codesign-pw-workspace-'), 8131); });
test.afterAll(async () => { await stack?.stop(); });

async function sendContribution(page: Page, text: string) {
  const composer = page.getByRole('textbox', { name: 'Your project contribution', exact: true });
  await composer.fill(text);
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  await expect(composer).toHaveValue('');
  await expect(page.locator('.message.student .message-content').filter({ hasText: text })).toBeVisible();
}

test('authored work, confirmed progress, and Deep Review survive a restart', async ({ page }) => {
  test.setTimeout(90_000);
  const browserErrors: string[] = [];
  page.on('pageerror', error => browserErrors.push(error.message));
  await page.goto(stack.url);
  await page.getByRole('button', { name: 'Continue as Guest' }).click();
  await page.getByRole('complementary', { name: 'Your notebooks' }).waitFor();
  const folder = await page.evaluate(async () => {
    const response = await fetch('/api/v1/reader/threads', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'Crossing study' }),
    });
    if (!response.ok) throw new Error(`Notebook fixture failed: ${response.status}`);
    return (await response.json()).notebook.id as string;
  });
  await page.goto(`${stack.url}/pilot/notebooks/${folder}`);
  await page.getByRole('tab', { name: 'Documents' }).click();
  await page.getByLabel('New document title').fill('Crossing field notes');
  await page.getByRole('button', { name: 'New document', exact: true }).click();
  const editor = page.locator('.tiptap[contenteditable="true"]');
  const evidence = 'We observed older residents waiting for a safe gap near the market.';
  await editor.fill(evidence);
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByText('All changes saved.')).toBeVisible();
  const documentUrl = page.url();

  await page.getByRole('button', { name: 'Back to notebook' }).click();
  await page.getByRole('tab', { name: 'Canvas' }).click();
  await page.getByLabel('New canvas title').fill('Crossing map');
  await page.getByRole('button', { name: 'New canvas', exact: true }).click();
  await expect(page).toHaveURL(/\/canvases\//);
  const canvasUrl = page.url();
  for (const title of ['Crossing problem', 'Field observation']) {
    await page.locator('#canvas-node-title').fill(title);
    await page.getByRole('button', { name: 'Add node' }).click();
  }
  await page.locator('#canvas-edge-source').selectOption({ label: 'Field observation' });
  await page.locator('#canvas-edge-target').selectOption({ label: 'Crossing problem' });
  await page.locator('#canvas-edge-relation').selectOption('supports');
  await page.getByRole('button', { name: 'Connect', exact: true }).click();
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByText('All changes saved.')).toBeVisible();

  await page.getByRole('button', { name: 'Develop canvas nodes into an artifact' }).click();
  const develop = page.getByRole('dialog', { name: 'Develop canvas nodes into an artifact' });
  await develop.getByRole('checkbox', { name: /Crossing problem/ }).check();
  await develop.getByRole('button', { name: 'Assemble myself' }).click();
  await expect(develop.getByRole('status')).toContainText('Artifact created.');
  await develop.getByRole('button', { name: 'Close', exact: true }).first().click();
  await page.goto(documentUrl);
  await page.getByRole('button', { name: 'Add to canvas' }).click();
  const transferDocument = page.getByRole('dialog', { name: 'Add document content to a canvas' });
  await transferDocument.getByRole('button', { name: 'Propose a new node' }).click();
  await transferDocument.getByLabel('Title', { exact: true }).fill('Saved field note');
  await transferDocument.getByRole('button', { name: 'Create new node' }).click();
  await expect(transferDocument.getByRole('status')).toContainText('The canvas was saved.');
  await page.goto(canvasUrl);

  await page.getByLabel('Search nodes').fill('Crossing problem');
  await page.getByRole('button', { name: /Locate.*Crossing problem/ }).click();
  await page.getByRole('button', { name: 'Ask the coach about the selected node' }).click();
  await page.getByRole('radio', { name: 'Design coaching', exact: true }).check();
  const firstContribution = 'Older residents need a safe way to cross near the market entrance.';
  await sendContribution(page, firstContribution);
  await page.getByRole('button', { name: 'Review suggestion', exact: true }).click();
  const suggestion = page.getByRole('dialog', { name: 'Review coach suggestion' });
  await suggestion.getByLabel('Node title').fill('Reviewed crossing idea');
  await suggestion.getByRole('button', { name: 'Add to canvas' }).click();
  await expect(suggestion).toBeHidden();

  const contribution = page.locator('.message.student').filter({ hasText: firstContribution });
  await contribution.getByRole('button', { name: 'Add to canvas' }).click();
  const transferChat = page.getByRole('dialog', { name: 'Add chat content to a canvas' });
  await transferChat.getByLabel('Title', { exact: true }).fill('Saved chat observation');
  await transferChat.getByRole('button', { name: 'Add node' }).click();
  await expect(transferChat).toBeHidden();

  const transitions = [
    ['Concept generation', 'We observed long waits and poor visibility when traffic turned near the crossing.'],
    ['Design specification', 'Compare a refuge island with a raised crossing for cost, safety and accessibility.'],
    ['Ethics & Critical Thinking', 'Specify clear sight lines and a level walking surface with measurable safety criteria.'],
    ['Reflection', 'Assess trade-offs for wheelchair users, older residents and drivers when judging the proposal.'],
  ];
  for (const [next, text] of transitions) {
    const confirm = page.getByRole('button', { name: `Move to ${next}`, exact: true });
    await sendContribution(page, text);
    if (!await confirm.isVisible()) await sendContribution(page, `${text} We would test this with observations at two times of day.`);
    await expect(confirm).toBeVisible();
    await confirm.click();
    await expect(confirm).toBeHidden();
    await page.getByRole('button', { name: 'Dismiss milestone' }).click();
  }
  const reflection = 'We changed our design because residents valued a shorter wait and predictable crossing time.';
  await sendContribution(page, reflection);
  await sendContribution(page, 'Next, we would share our evidence with residents and measure whether those changes helped.');
  const openReview = page.getByRole('button', { name: /^Review \d/ });
  await openReview.click();
  await page.getByRole('tab', { name: 'Summary' }).click();
  const review = page.getByRole('region', { name: 'Deep Review', exact: true });
  await review.getByRole('button', { name: 'Start Deep Review', exact: true }).click();
  await expect(review.getByRole('status')).toHaveText('Deep Review is saved.');

  await page.evaluate(() => sessionStorage.clear());
  await stack.restart();
  await page.goto(stack.url);
  const resume = page.getByRole('article', { name: 'Continue where you left off' });
  await expect(resume.getByRole('region', { name: 'Milestone recap' })).toBeVisible();
  await expect(resume.getByRole('button', { name: /Crossing field notes/ })).toBeVisible();
  await resume.getByRole('button', { name: 'Continue', exact: true }).click();
  await expect(page).toHaveURL(/\/chats\//);
  await openReview.click();
  await page.getByRole('tab', { name: 'Summary' }).click();
  await expect(review.getByRole('status')).toHaveText('Deep Review is saved.');

  await page.goto(documentUrl);
  await expect(editor).toHaveText(evidence);
  await page.goto(canvasUrl);
  await expect(page.getByRole('list', { name: 'Connection list' })).toContainText('Field observation — supports — Crossing problem');
  const outline = page.getByRole('list', { name: 'Node list' });
  for (const title of ['Reviewed crossing idea', 'Saved chat observation', 'Saved field note']) {
    await expect(outline).toContainText(title);
  }
  await page.getByRole('button', { name: 'Back to notebook' }).click();
  await page.getByRole('tab', { name: 'Canvas' }).click();
  await page.getByRole('button', { name: 'Delete canvas: Crossing map' }).click();
  await page.getByRole('button', { name: 'Confirm canvas deletion' }).click();
  await expect(page.getByText('No canvases yet.', { exact: false })).toBeVisible();
  expect(browserErrors).toEqual([]);
});
