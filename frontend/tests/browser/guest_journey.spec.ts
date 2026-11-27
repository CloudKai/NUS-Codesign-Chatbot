/**
 * Guest journey through the production-built reader: sign in, open a chat, send a
 * deterministic mock coaching turn, and reopen the saved reply after a reload
 * (exact-key saved-turn recovery). Covers local ticket 05 checkbox 2.
 */
import { expect, test } from '@playwright/test';
import { startStack, tempWorkspace, type Stack } from './stack';

const PROMPT = 'Older residents need safer crossings near the market. What should we investigate?';
const WORKSPACE = tempWorkspace('codesign-pw-guest-');
const PORT = 8121;

let stack: Stack;

test.beforeAll(async () => {
  stack = await startStack(WORKSPACE, PORT);
});

test.afterAll(async () => {
  await stack.stop();
});

test('Guest opens a notebook, sends a mock coaching turn, and reopens the saved reply', async ({
  page,
}) => {
  // Signed-out session probes return expected 401s before the guest signs in; only
  // genuinely unexpected errors (JS exceptions, non-401 server failures) fail the run.
  const unexpectedErrors: string[] = [];
  const isExpected401 = (text: string) => text.includes('status of 401');
  page.on('pageerror', (error) => unexpectedErrors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error' && !isExpected401(message.text())) {
      unexpectedErrors.push(message.text());
    }
  });

  await page.goto(stack.url);
  const guest = page.getByRole('button', { name: 'Continue as Guest' });
  const nav = page.getByRole('complementary', { name: 'Your notebooks' });
  await guest.or(nav).waitFor();
  if (await guest.isVisible()) await guest.click();
  await nav.waitFor();

  // Create and rename a synthetic chat through the same-origin reader API.
  const chat = await page.evaluate(async () => {
    const response = await fetch('/api/v1/reader/threads', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind: 'chat' }),
    });
    if (!response.ok) throw new Error(`Synthetic chat creation failed: ${response.status}`);
    const { notebook } = await response.json();
    const name = `Ticket 05 guest journey ${notebook.id}`;
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
  await draft.fill(PROMPT);

  // Send the turn and wait for the committed coach reply with real text. Waiting on
  // the completed coach message (not the transient unsaved preview) avoids a race
  // where a fast mock reply commits before the preview node is observed.
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  const coachMessage = page.locator('.message.coach .message-content').first();
  // Wait for the committed coach reply to carry real text (version-agnostic matcher).
  await page.waitForFunction(
    () => {
      const el = document.querySelector('.message.coach .message-content');
      return el && el.textContent.trim().length > 0;
    },
    { timeout: 30_000 },
  );
  const savedText = (await coachMessage.innerText()).trim();
  expect(savedText.length).toBeGreaterThan(0);
  // Generation committed the reply to a saved message; the draft is cleared.
  expect(await draft.inputValue()).toBe('');

  // Reopen after reload: the committed reply is recovered by its saved turn.
  await page.reload();
  await nav.getByRole('button', { name: chat.name, exact: true }).first().click();
  await coachMessage.waitFor();
  const recovered = (await coachMessage.innerText()).trim();
  expect(recovered.length).toBeGreaterThan(0);
  expect(recovered).toContain(savedText.slice(0, 10));

  // No fabricated chat-activity percentages (the stage review count is legitimate).
  expect(await page.locator('.chat-progress-percent, .chat-progress-explanation').count()).toBe(0);
  expect(unexpectedErrors).toEqual([]);
});
