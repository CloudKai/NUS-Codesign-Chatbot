/**
 * Student-initiated cancellation of an in-flight reply (local ticket 06).
 *
 * The mock provider finishes faster than a browser click can win the stop/save
 * race, so this spec runs the disposable stack against the cancellable fixture
 * (tests/browser/cancellable_stack_app.py): the real workflow pauses after one
 * unvalidated reply delta until released. The student then clicks the real Stop
 * generating control, the real POST /coach-turn/stop answers "stopping", and the
 * released worker reaches a cancellation checkpoint — producing the same terminal
 * wire sequence the FastAPI seam proves in
 * tests/http/test_reader_conversation.py::test_reader_stop_is_owner_scoped_and_prevents_saving
 * (reply_discard, then a 409 error with category "cancelled").
 *
 * Covers ticket 06 checkbox 1 (cancellation journey): the prompt is kept, no
 * reply is saved, no recovery actions appear, and no generation is replayed.
 */
import { expect, test } from '@playwright/test';
import { startStack, tempWorkspace, type Stack } from './stack';

const PROMPT = 'Older residents need safer crossings near the market. What should we investigate?';
const WORKSPACE = tempWorkspace('codesign-pw-cancel-');
const PORT = 8126;

let stack: Stack;

test.beforeAll(async () => {
  stack = await startStack(WORKSPACE, PORT, { cancellableTurns: true });
});

test.afterAll(async () => {
  await stack.stop();
});

test('Stop generating keeps the prompt, saves nothing, and never replays', async ({ page }) => {
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
    const name = `Cancellation journey ${notebook.id}`;
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

  // Count real stream dispatches so the spec can prove there is no automatic replay.
  let streamPosts = 0;
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().includes('/project/stream')) streamPosts += 1;
  });

  const draft = page.getByRole('textbox', { name: 'Your project contribution', exact: true });
  await draft.fill(PROMPT);
  await page.getByRole('button', { name: 'Send message', exact: true }).click();

  // The paused worker emitted one preview delta; Stop is enabled by `started`.
  const stop = page.getByRole('button', { name: 'Stop generating', exact: true });
  await expect(stop).toBeEnabled({ timeout: 30_000 });
  await expect(page.locator('.message.preview')).toContainText('Unfinished preview');

  await stop.click();
  // The real stop route answers "stopping" for the paused in-flight turn.
  await expect(page.locator('.turn-status')).toHaveText('Stopping generation…', { timeout: 10_000 });

  // Release the paused workflow; its cancellation checkpoints end the turn.
  const released = await fetch(`${stack.url}/__fixture__/release-coach-turn`, { method: 'POST' });
  expect(released.ok).toBe(true);

  // The cancelled terminal event keeps the prompt and clears the pending turn.
  await expect(page.locator('.turn-status')).toHaveText('Generation stopped. Your prompt is kept.', {
    timeout: 30_000,
  });
  expect(await draft.inputValue()).toBe(PROMPT);
  await expect(page.locator('.message.coach')).toHaveCount(0);
  await expect(page.locator('.recovery-actions')).toHaveCount(0);
  await expect(page.locator('.message.preview')).toHaveCount(0);

  // The server saved nothing and issued no receipt for the cancelled key.
  const saved = await page.evaluate(async (thread) => {
    const response = await fetch(`/api/v1/reader/threads/${thread}/messages/page`);
    if (!response.ok) throw new Error('Saved-page read failed');
    const page_ = await response.json();
    return { total: page_.total_count as number, receipt: await fetch(
      `/api/v1/reader/threads/${thread}/coach-turn`,
    ).then((r) => r.status) };
  }, chat.id);
  expect(saved.total).toBe(0);

  // Exactly one dispatch: a cancelled turn is never replayed automatically.
  expect(streamPosts).toBe(1);

  // The kept draft survives a reload; the empty transcript shows no saved reply.
  await page.reload();
  await nav.getByRole('button', { name: chat.name, exact: true }).first().click();
  expect(await page.getByRole('textbox', { name: 'Your project contribution', exact: true }).inputValue())
    .toBe(PROMPT);
  await expect(page.locator('.message.coach')).toHaveCount(0);
  expect(await page.locator('.message.student', { hasText: PROMPT }).count()).toBe(0);

  expect(unexpectedErrors).toEqual([]);
});
