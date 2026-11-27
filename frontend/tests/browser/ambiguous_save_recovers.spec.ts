/**
 * Ambiguous save, read-only recovery and explicit discard (local ticket 06).
 *
 * The stream request completes server-side (`route.fetch()`), then the page's
 * connection is dropped — the client cannot know whether the turn was saved.
 * The saved-receipt read is then intercepted to return `null`, the exact body
 * the real route serves for an unsaved key, so the check is genuinely
 * ambiguous. The client must keep the question pending, offer explicit actions
 * only (never replay automatically), recover through a later successful check,
 * and restore the composer text on discard.
 *
 * Covers ticket 06 checkbox 1 (ambiguous save and discard journeys) alongside
 * the exact-key recovery already proven by interrupted_stream_recovers.spec.ts.
 */
import { expect, test } from '@playwright/test';
import { startStack, tempWorkspace, type Stack } from './stack';

const WORKSPACE = tempWorkspace('codesign-pw-ambiguous-');
const PORT = 8127;
const FIRST = 'Draft a survey about market crossing safety for older residents.';
const SECOND = 'Which nearby shops rely on customer foot traffic at the market?';

let stack: Stack;

test.beforeAll(async () => {
  stack = await startStack(WORKSPACE, PORT);
});

test.afterAll(async () => {
  await stack.stop();
});

/** Drop the page's stream connection after the server has committed the turn. */
async function interruptStream(page: import('@playwright/test').Page): Promise<void> {
  await page.route('**/project/stream', async (route) => {
    const response = await route.fetch();
    await new Promise((resolve) => setTimeout(resolve, 150));
    await route.abort('connectionreset').catch(() => {});
    void response;
  });
}

/** The recovery-read URL: shared reference so `route` and `unroute` match. */
const isReceiptUrl = (url: URL) => url.pathname.endsWith('/coach-turn');

/** Serve the unsaved-receipt body for recovery reads (null = nothing saved). */
async function hideSavedReceipt(page: import('@playwright/test').Page): Promise<void> {
  await page.route(
    isReceiptUrl,
    (route) => route.fulfill({ status: 200, contentType: 'application/json', body: 'null' }),
  );
}

test('ambiguous save recovers by checking and discards only on request', async ({ page }) => {
  const unexpectedErrors: string[] = [];
  page.on('pageerror', (error) => unexpectedErrors.push(error.message));

  await page.goto(stack.url);
  const guest = page.getByRole('button', { name: 'Continue as Guest' });
  const nav = page.getByRole('complementary', { name: 'Your notebooks' });
  await guest.or(nav).waitFor();
  if (await guest.isVisible()) await guest.click();
  await nav.waitFor();

  const chat = await page.evaluate(async () => {
    const response = await fetch('/api/v1/reader/threads', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind: 'chat' }),
    });
    if (!response.ok) throw new Error('Synthetic chat creation failed');
    const notebook = (await response.json()).notebook;
    const name = `Ambiguous save journey ${notebook.id}`;
    const renamed = await fetch(`/api/v1/reader/threads/${notebook.id}/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    if (!renamed.ok) throw new Error('Synthetic chat rename failed');
    return { id: notebook.id, name };
  });

  await page.reload();
  await nav.getByRole('button', { name: chat.name, exact: true }).first().click();
  await page.getByRole('radio', { name: 'Design coaching', exact: true }).check();
  const draft = page.getByRole('textbox', { name: 'Your project contribution', exact: true });

  // --- Turn 1: ambiguous save, then explicit check recovers the saved reply. ---
  await interruptStream(page);
  await hideSavedReceipt(page);
  await draft.fill(FIRST);
  await page.getByRole('button', { name: 'Send message', exact: true }).click();

  // The client could not confirm the save; the question stays pending with
  // explicit actions and no automatic retry.
  await expect(page.locator('.turn-status')).toHaveText(
    'We couldn’t confirm the reply was saved. Your question is safe. Check again before retrying.',
    { timeout: 30_000 },
  );
  await expect(page.locator('.recovery-actions')).toContainText(`Pending question: ${FIRST}`);
  const retry = page.getByRole('button', { name: 'Retry same question' });
  await expect(retry).toBeEnabled();
  expect(await page.locator('.message.coach').count()).toBe(0);

  // The server did save the turn: the ambiguity is on the client side only.
  const savedTotal = await page.evaluate(async (thread) => {
    const response = await fetch(`/api/v1/reader/threads/${thread}/messages/page`);
    return (await response.json()).total_count as number;
  }, chat.id);
  expect(savedTotal).toBe(2);

  // Stop hiding the receipt: an explicit check now reads the saved answer.
  await page.unroute(isReceiptUrl);
  await page.getByRole('button', { name: 'Check saved answer' }).click();
  await expect(page.locator('.message.coach')).toHaveCount(1, { timeout: 30_000 });
  await expect(page.locator('.turn-status')).toHaveText('Your answer is ready.');
  await expect(page.locator('.recovery-actions')).toHaveCount(0);
  await expect(draft).toHaveValue('');

  // --- Turn 2: ambiguous save, then explicit discard restores the draft. ---
  await hideSavedReceipt(page);
  await draft.fill(SECOND);
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  await expect(page.locator('.turn-status')).toHaveText(
    'We couldn’t confirm the reply was saved. Your question is safe. Check again before retrying.',
    { timeout: 30_000 },
  );
  await page.getByRole('button', { name: 'Discard and edit' }).click();
  await expect(page.locator('.turn-status')).toHaveText(
    'Not sent. Your text is back in the composer to edit.',
  );
  await expect(draft).toHaveValue(SECOND);
  await expect(page.locator('.recovery-actions')).toHaveCount(0);
  await expect(page.locator('.message.coach')).toHaveCount(1);

  expect(unexpectedErrors).toEqual([]);
});
