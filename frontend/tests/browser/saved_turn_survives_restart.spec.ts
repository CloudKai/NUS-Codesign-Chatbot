/**
 * Prove saved work survives a real backend restart (local ticket 05 checkbox 2).
 *
 * The guest signs in, sends a deterministic mock coaching turn, and we capture the
 * committed coach reply. The disposable FastAPI process is then actually killed and
 * respawned against the same SQLite workspace; the same browser context (guest
 * cookie preserved) reloads and reopens the chat. The committed reply must be
 * present again, proving durable persistence rather than in-memory state.
 */
import { expect, test } from '@playwright/test';
import { startStack, tempWorkspace, type Stack } from './stack';

const PROMPT = 'Older residents need safer crossings near the market. What should we investigate?';
const WORKSPACE = tempWorkspace('codesign-pw-restart-');
const PORT = 8123;

let stack: Stack;

test.beforeAll(async () => {
  stack = await startStack(WORKSPACE, PORT);
});

test.afterAll(async () => {
  await stack.stop();
});

test('saved coach reply survives a real backend restart', async ({ page }) => {
  const unexpectedErrors: string[] = [];
  page.on('pageerror', (error) => unexpectedErrors.push(error.message));

  await page.goto(stack.url);
  const guest = page.getByRole('button', { name: 'Continue as Guest' });
  const nav = page.getByRole('complementary', { name: 'Your notebooks' });
  await guest.or(nav).waitFor();
  if (await guest.isVisible()) await guest.click();
  await nav.waitFor();

  // Create a chat, send a mock coaching turn, and capture the committed reply.
  const chat = await page.evaluate(async () => {
    const response = await fetch('/api/v1/reader/threads', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind: 'chat' }),
    });
    if (!response.ok) throw new Error('Synthetic chat creation failed');
    const { notebook } = await response.json();
    const name = `Restart persistence ${notebook.id}`;
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
  await page.getByRole('button', { name: 'Send message', exact: true }).click();

  const coachMessage = page.locator('.message.coach .message-content').first();
  await page.waitForFunction(
    () => {
      const el = document.querySelector('.message.coach .message-content');
      return el && el.textContent.trim().length > 0;
    },
    { timeout: 30_000 },
  );
  const savedText = (await coachMessage.innerText()).trim();
  expect(savedText.length).toBeGreaterThan(0);
  const signature = savedText.slice(0, 10);

  // Real restart: stop the server process and respawn it against the same workspace.
  await stack.restart();

  // The same browser context reloads; the guest cookie still authenticates.
  await page.reload();
  await nav.getByRole('button', { name: chat.name, exact: true }).first().click();
  await coachMessage.waitFor();
  const afterRestart = (await coachMessage.innerText().then((text) => text.trim()));
  expect(afterRestart).toContain(signature);

  expect(await page.locator('.chat-progress-percent, .chat-progress-explanation').count()).toBe(0);
  expect(unexpectedErrors).toEqual([]);
});
