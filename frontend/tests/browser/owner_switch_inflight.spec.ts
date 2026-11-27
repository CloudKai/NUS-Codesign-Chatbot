/**
 * Switch guests while a generation request is pending and approve a synthetic
 * late reply for the previous owner. The pending generation must abort, the
 * late private result must never render, and the new guest must not see the old
 * chat. Covers local ticket 05 checkbox 3 (controlled owner-change fault
 * injection) and the never-replay invariant.
 */
import { expect, test } from '@playwright/test';
import { startStack, tempWorkspace, type Stack } from './stack';

const WORKSPACE = tempWorkspace('codesign-pw-owner-');
const PORT = 8122;

let stack: Stack;

test.beforeAll(async () => {
  stack = await startStack(WORKSPACE, PORT);
});

test.afterAll(async () => {
  await stack.stop();
});

test('owner switch while generation is pending drops the late result and never replays', async ({
  page,
}) => {
  const unexpectedErrors: string[] = [];
  page.on('pageerror', (error) => unexpectedErrors.push(error.message));

  const nav = page.getByRole('complementary', { name: 'Your notebooks' });
  await page.goto(stack.url);
  const guest = page.getByRole('button', { name: 'Continue as Guest' });
  await guest.or(nav).waitFor();
  if (await guest.isVisible()) await guest.click();
  await nav.waitFor();

  const created = await page.evaluate(async () => {
    const response = await fetch('/api/v1/reader/threads', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind: 'chat' }),
    });
    if (!response.ok) throw new Error('Synthetic chat creation failed');
    const notebook = (await response.json()).notebook;
    const name = `Pending identity test ${notebook.id}`;
    const renamed = await fetch(`/api/v1/reader/threads/${notebook.id}/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    if (!renamed.ok) throw new Error('Synthetic chat rename failed');
    return { ...notebook, name };
  });

  await page.reload();
  await nav.getByRole('button', { name: created.name, exact: true }).first().click();
  await page.getByRole('radio', { name: 'Design coaching', exact: true }).check();

  const draft = page.getByRole('textbox', { name: 'Your project contribution', exact: true });
  await draft.fill('Synthetic owner A project prompt.');

  let sends = 0;
  let release: ((route: import('@playwright/test').Route) => void) | undefined;
  const intercepted = new Promise<void>((resolve) => {
    release = (route) => resolve(route);
  });
  await page.route('**/project/stream', (route) => {
    sends += 1;
    release?.(route);
  });

  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  const route = (await intercepted) as import('@playwright/test').Route;
  const request = route.request();
  const payload = request.postDataJSON() as { idempotency_key?: string };

  // The guest switch aborts the in-flight read before we approve the late reply.
  const aborted = page.waitForEvent('requestfailed', {
    predicate: (failed) => failed.url().endsWith('/project/stream'),
  });
  await page.context().clearCookies();
  await page.evaluate(() =>
    window.dispatchEvent(
      new StorageEvent('storage', {
        key: 'codesign-signed-out',
        newValue: String(Date.now()),
      }),
    ),
  );
  await aborted;

  await page.getByRole('button', { name: 'Continue as Guest', exact: true }).click();
  await nav.waitFor();

  // Approve the late reply for the previous owner after the switch; it must be
  // discarded by the new owner's session and never rendered.
  await route.fulfill({
    status: 200,
    contentType: 'application/x-ndjson',
    body: [
      {
        event: 'started',
        thread_id: created.id,
        idempotency_key: payload.idempotency_key,
        stage: 'problem_identification',
      },
      { event: 'reply_delta', text: 'OLD OWNER PRIVATE RESULT' },
      {
        event: 'done',
        turn: {
          response_text: 'OLD OWNER PRIVATE RESULT',
          assessment: { response_mode: 'coaching', citations: [] },
        },
      },
    ]
      .map((event) => JSON.stringify(event))
      .join('\n') + '\n',
  }).catch(() => {});
  await page.unroute('**/project/stream');

  await page.evaluate(() =>
    new Promise<void>((resolve) => {
      requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
    }),
  );

  expect(await page.getByText('OLD OWNER PRIVATE RESULT', { exact: true }).count()).toBe(0);
  expect(await page.locator('.chat-progress, .message.preview').count()).toBe(0);
  expect(await nav.getByRole('button', { name: created.name, exact: true }).count()).toBe(0);
  expect(sends).toBe(1);
  expect(unexpectedErrors).toEqual([]);
});
