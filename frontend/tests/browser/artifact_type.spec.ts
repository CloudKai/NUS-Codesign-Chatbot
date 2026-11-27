/** Course-aligned document creation through the real routed application. */
import { expect, test } from '@playwright/test';
import { startStack, tempWorkspace, type Stack } from './stack';

let stack: Stack;
test.beforeAll(async () => { stack = await startStack(tempWorkspace('codesign-pw-artifact-type-'), 8132); });
test.afterAll(async () => { await stack?.stop(); });

test('a student creates a Reflection document and reopens its selected type', async ({ page }) => {
  await page.goto(stack.url);
  await page.getByRole('button', { name: 'Continue as Guest' }).click();
  await page.getByRole('complementary', { name: 'Your notebooks' }).waitFor();
  const folder = await page.evaluate(async () => {
    const response = await fetch('/api/v1/reader/threads', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'Document categories' }),
    });
    if (!response.ok) throw new Error('Could not create the disposable notebook');
    return (await response.json()).notebook.id as string;
  });
  await page.goto(`${stack.url}/pilot/notebooks/${folder}`);
  await page.getByRole('tab', { name: 'Documents' }).click();
  await page.getByLabel('New document title').fill('What changed in our thinking');
  await page.getByLabel('Document type').selectOption('reflection');
  await page.getByRole('button', { name: 'New document', exact: true }).click();
  await page.getByRole('region', { name: 'Document editor' }).waitFor();
  await page.reload();
  await page.getByRole('button', { name: 'Back to notebook' }).click();
  await page.getByRole('tab', { name: 'Documents' }).click();
  const document = page.getByRole('button', { name: /What changed in our thinking/ });
  await expect(document).toContainText('Reflection');
});
