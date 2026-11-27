/**
 * Interrupted-response recovery under the original request key (local ticket 05).
 *
 * The stream route is intercepted so the real request completes and persists
 * server-side (`route.fetch()`), and only then is the page's request aborted — a
 * deterministic dropped connection after the server committed. The client must not
 * replay the write: it reconciles read-only against
 * `GET /threads/{id}/coach-turn?idempotency_key=<original key>` and renders exactly
 * one confirmed turn. Covers ticket 05 checkbox 3 (exact-key recovery).
 */
import { expect, test } from '@playwright/test';
import { startStack, tempWorkspace, type Stack } from './stack';

const PROMPT = 'Older residents need safer crossings near the market. What should we investigate?';
const WORKSPACE = tempWorkspace('codesign-pw-interrupt-');
const PORT = 8124;

let stack: Stack;

test.beforeAll(async () => {
  stack = await startStack(WORKSPACE, PORT);
});

test.afterAll(async () => {
  await stack.stop();
});

test('interrupted stream recovers once under the original request key', async ({ page }) => {
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
    const name = `Interrupted recovery ${notebook.id}`;
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

  // Capture the original key, let the real request finish server-side, then drop
  // the page's connection so the client sees an interrupted response.
  let originalKey = '';
  await page.route('**/project/stream', async (route) => {
    const body = route.request().postDataJSON() as { idempotency_key?: string };
    originalKey = body.idempotency_key ?? '';
    const response = await route.fetch();
    await new Promise((resolve) => setTimeout(resolve, 150));
    await route.abort('connectionreset').catch(() => {});
    void response;
  });

  // Observe the read-only recovery call without changing it.
  let recoveredKey = '';
  page.on('request', (request) => {
    if (request.url().includes('/coach-turn?')) {
      recoveredKey = new URL(request.url()).searchParams.get('idempotency_key') ?? '';
    }
  });

  const draft = page.getByRole('textbox', { name: 'Your project contribution', exact: true });
  await draft.fill(PROMPT);
  await page.getByRole('button', { name: 'Send message', exact: true }).click();

  // Read-only recovery replaces the lost stream: exactly one confirmed turn.
  const coachMessages = page.locator('.message.coach');
  await expect(coachMessages).toHaveCount(1, { timeout: 30_000 });
  const coachText = (await coachMessages.locator('.message-content').first().innerText()).trim();
  expect(coachText.length).toBeGreaterThan(0);

  expect(originalKey, 'the turn was sent under an idempotency key').not.toBe('');
  expect(recoveredKey, 'recovery reused the original request key').toBe(originalKey);

  // No replayed write: the prompt is saved exactly once.
  expect(await page.locator('.message.student', { hasText: PROMPT }).count()).toBe(1);
  expect(await page.getByText('Your answer is ready.').count()).toBeGreaterThan(0);

  expect(await page.locator('.chat-progress-percent, .chat-progress-explanation').count()).toBe(0);
  expect(unexpectedErrors).toEqual([]);
});
