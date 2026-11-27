/** Verify the shared transcript and mode-specific Review on the disposable mock stack. */
import { expect, test, type Page } from '@playwright/test';
import { startStack, tempWorkspace, type Stack } from './stack';

let stack: Stack;

test.beforeAll(async () => {
  stack = await startStack(tempWorkspace('codesign-pw-improve-'), 8136);
});

test.afterAll(async () => {
  await stack?.stop();
});

async function chooseMode(page: Page, name: string) {
  const radio = page.getByRole('radio', { name, exact: true });
  await page.locator('.mode-switch label').filter({ has: radio }).click();
  await expect(radio).toBeChecked();
}

for (const viewport of [{ width: 1440, height: 960 }, { width: 390, height: 844 }]) {
  test(`Improve Review preserves bookmarks and Design coaching progress at ${viewport.width} px`, async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => {
      if (message.type() === 'error' && !message.text().includes('status of 401')) errors.push(message.text());
    });
    await page.setViewportSize(viewport);
    await page.goto(stack.url);
    await page.getByRole('button', { name: 'Continue as Guest' }).click();
    await page.getByRole('button', { name: 'Improve my design', exact: true }).click();
    const improveDraft = page.getByRole('textbox', { name: 'What you want to improve' });
    const projectDraft = page.getByRole('textbox', { name: 'Your project contribution' });
    const send = page.getByRole('button', { name: 'Send message' });
    const replies = page.locator('.message.coach .message-content');

    await improveDraft.fill('How can I improve the visibility of my crossing timer?');
    await send.click();
    await expect(replies).toHaveCount(1);
    await expect(improveDraft).toHaveValue('');
    const improveReply = page.locator('.message.coach').first();
    await improveReply.getByRole('button', { name: 'Star message', exact: true }).click();
    await expect(improveReply.getByRole('button', { name: 'Unstar message', exact: true })).toBeVisible();

    await chooseMode(page, 'Design coaching');
    await projectDraft.fill('Older residents need to cross safely to reach the shops.');
    await send.click();
    await expect(replies).toHaveCount(2);
    await expect(projectDraft).toHaveValue('');
    await projectDraft.fill('Older residents must have enough time to finish crossing near the shops.');
    await send.click();
    await expect(replies).toHaveCount(3);
    await expect(projectDraft).toHaveValue('');
    const recommendation = page.getByRole('region', { name: 'Coach recommendation' });
    await expect(recommendation).toBeVisible();

    await chooseMode(page, 'Improve my design');
    await expect(recommendation).toHaveCount(0);
    await page.getByRole('button', { name: 'Review', exact: true }).click();
    const review = page.getByRole('dialog', { name: 'Review' });
    await expect(review.getByRole('heading', { name: 'My work' })).toBeVisible();
    await expect(review.getByRole('tab')).toHaveCount(0);
    await expect(review.getByRole('button', { name: 'Download project summary' })).toHaveCount(0);
    await expect(review.getByRole('button', { name: 'Remove star' })).toBeVisible();
    await review.getByRole('button', { name: 'Jump to message' }).click();
    await expect(review).toHaveCount(0);
    await expect(improveReply).toBeFocused();

    await chooseMode(page, 'Design coaching');
    await expect(recommendation).toBeVisible();
    await page.getByRole('button', { name: /^Review/ }).click();
    await expect(review.getByRole('tab', { name: 'Progression', selected: true })).toBeVisible();
    await expect(review.getByRole('button', { name: 'Confirm next stage' })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width);
    expect(errors).toEqual([]);
  });
}
