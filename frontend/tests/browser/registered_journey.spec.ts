/**
 * Approved synthetic registered-identity journey (local ticket 05 checkbox 2).
 *
 * The disposable stack serves the deterministic Cognito boundary from
 * `tests/browser/registered_stack_app.py`, so this spec signs in a synthetic
 * *registered* student by seeding the verified ID/refresh cookies (the same
 * mechanism the API integration tests use) — no live Cognito, AWS or paid
 * provider. The registered owner opens a notebook, submits a deterministic mock
 * coaching turn, and reopens the committed reply after a real backend restart
 * while staying the same verified identity.
 */
import { expect, test } from '@playwright/test';
import { startStack, tempWorkspace, type Stack } from './stack';

const PROMPT = 'Older residents need safer crossings near the market. What should we investigate?';
const WORKSPACE = tempWorkspace('codesign-pw-registered-');
const PORT = 8125;
// Kept in sync with REGISTERED_* in tests/browser/registered_stack_app.py.
const ID_TOKEN = 'id-token-browser-ci-student';
const REFRESH_TOKEN = 'refresh-token-browser-ci-student';

let stack: Stack;

test.beforeAll(async () => {
  stack = await startStack(WORKSPACE, PORT, { registeredIdentity: true });
});

test.afterAll(async () => {
  await stack.stop();
});

test('registered student submits a mock turn and reopens it after a real backend restart', async ({
  page,
}) => {
  const unexpectedErrors: string[] = [];
  page.on('pageerror', (error) => unexpectedErrors.push(error.message));

  // Seed the verified cookies for the synthetic registered student.
  await page.context().addCookies([
    { name: 'co_design_id', value: ID_TOKEN, url: stack.url },
    { name: 'co_design_refresh', value: REFRESH_TOKEN, url: stack.url },
  ]);

  await page.goto(stack.url);
  const nav = page.getByRole('complementary', { name: 'Your notebooks' });
  await nav.waitFor();
  // Registered identity: no Guest entry point, and the profile offers Sign out.
  expect(await page.getByRole('button', { name: 'Continue as Guest' }).count()).toBe(0);
  await expect(page.getByRole('link', { name: 'Sign out' })).toBeVisible();

  const chat = await page.evaluate(async () => {
    const response = await fetch('/api/v1/reader/threads', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind: 'chat' }),
    });
    if (!response.ok) throw new Error(`Registered chat creation failed: ${response.status}`);
    const notebook = (await response.json()).notebook;
    const name = `Registered journey ${notebook.id}`;
    const renamed = await fetch(`/api/v1/reader/threads/${notebook.id}/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    if (!renamed.ok) throw new Error('Registered chat rename failed');
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

  // Real restart against the same workspace; the registered cookies still verify.
  await stack.restart();
  await page.reload();
  await nav.waitFor();
  await expect(page.getByRole('link', { name: 'Sign out' })).toBeVisible();
  await nav.getByRole('button', { name: chat.name, exact: true }).first().click();
  await coachMessage.waitFor();
  expect((await coachMessage.innerText()).trim()).toContain(signature);

  expect(await page.locator('.chat-progress-percent, .chat-progress-explanation').count()).toBe(0);
  expect(unexpectedErrors).toEqual([]);
});
