/**
 * A restored-open Review panel must never block the chat (student bug report).
 *
 * A student who closes the tab with the Thinking Path Review panel open gets it
 * restored from tab storage on the next visit. The public contract asserted here:
 *   - the restored panel opens non-blocking on a drawer layout: the page behind
 *     it (sidebar, composer) stays hit-testable and clickable, and no native
 *     modal dialog is left open on chat entry;
 *   - the restored panel announces itself: it is a visible, named dialog and
 *     the Review toggle reports expanded;
 *   - an explicit Review-button click on a non-docked layout still opens the
 *     real modal (explicit intent earns the modal contract), Escape dismisses
 *     it, and focus returns to the toggle;
 *   - the docked layout keeps its non-modal side-by-side panel.
 */
import { expect, test } from '@playwright/test';
import { startStack, tempWorkspace, type Stack } from './stack';

const WORKSPACE = tempWorkspace('codesign-pw-review-restore-');
const PORT = 8134;

let stack: Stack;

test.beforeAll(async () => {
  stack = await startStack(WORKSPACE, PORT);
});

test.afterAll(async () => {
  await stack.stop();
});

/** Drawer layout width: Review cannot dock, so a modal would block the page. */
const DRAWER_VIEWPORT = { width: 900, height: 700 };

async function signInAndCreateChat(page: import('@playwright/test').Page): Promise<string> {
  await page.goto(stack.url);
  const guest = page.getByRole('button', { name: 'Continue as Guest' });
  const nav = page.getByRole('complementary', { name: 'Your notebooks' });
  await guest.or(nav).waitFor();
  if (await guest.isVisible()) await guest.click();
  await nav.waitFor();
  return page.evaluate(async () => {
    const response = await fetch('/api/v1/reader/threads', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind: 'chat' }),
    });
    if (!response.ok) throw new Error(`Synthetic chat creation failed: ${response.status}`);
    return (await response.json()).notebook.id as string;
  });
}

async function restoreOpenReviewBeforeLoad(
  page: import('@playwright/test').Page,
  chatId: string,
): Promise<void> {
  const { owner, value } = await page.evaluate(async () => {
    const session = await fetch('/api/v1/reader/session').then((r) => r.json());
    return { owner: session.owner_id as string, value: JSON.stringify({ open: true, tab: 'Progression' }) };
  });
  await page.addInitScript(({ key, stored }) => {
    sessionStorage.setItem(key, stored);
  }, { key: `codesign-review:${owner}:${chatId}`, stored: value });
}

test('a restored-open Review panel opens non-blocking and the page stays clickable', async ({ page }) => {
  const chatId = await signInAndCreateChat(page);
  await restoreOpenReviewBeforeLoad(page, chatId);
  await page.setViewportSize(DRAWER_VIEWPORT);
  await page.goto(`${stack.url}/chats/${chatId}`);

  // The panel is restored and announces itself as a visible, named dialog.
  const panel = page.getByRole('dialog', { name: 'Review' });
  await expect(panel).toBeVisible();
  await expect(page.locator('.path-toggle')).toHaveAttribute('aria-expanded', 'true');
  await expect(panel.getByText('Reopened your saved Review panel from your last visit.')).toBeVisible();

  // It must not be a native modal: a modal would make every click outside the
  // panel dead through its full-page ::backdrop.
  expect(await panel.evaluate((el) => el.matches(':modal'))).toBe(false);
  await expect(page.locator('dialog:modal')).toHaveCount(0);

  // Hit-testing proves the sidebar is reachable, not intercepted by a backdrop.
  const intercepted = await page.evaluate(() => {
    const home = [...document.querySelectorAll('aside button, nav button')]
      .find((button) => button.textContent?.trim() === 'Home');
    if (!home) return 'no Home button';
    const box = home.getBoundingClientRect();
    const hit = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2);
    return home.contains(hit) || hit === home ? null : hit?.tagName + '.' + hit?.className;
  });
  expect(intercepted).toBeNull();

  // The page is functionally clickable: the student can navigate away.
  await page.getByRole('button', { name: 'Home', exact: true }).click();
  await page.getByRole('complementary', { name: 'Your notebooks' }).waitFor();
  expect(page.url()).not.toContain('/chats/');
});

test('an explicit Review click on a drawer layout still opens a modal that Escape dismisses', async ({ page }) => {
  const chatId = await signInAndCreateChat(page);
  await page.setViewportSize(DRAWER_VIEWPORT);
  await page.goto(`${stack.url}/chats/${chatId}`);

  const toggle = page.locator('.path-toggle');
  await toggle.click();
  const panel = page.getByRole('dialog', { name: 'Review' });
  await expect(panel).toBeVisible();
  // Explicit intent keeps the modal contract on a non-docked layout.
  expect(await panel.evaluate((el) => el.matches(':modal'))).toBe(true);

  await page.keyboard.press('Escape');
  await expect(panel).toHaveCount(0);
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await expect.poll(() => page.evaluate(() => document.activeElement?.className)).toContain('path-toggle');
});

test('the docked layout keeps its non-modal side-by-side Review panel', async ({ page }) => {
  const chatId = await signInAndCreateChat(page);
  await page.goto(`${stack.url}/chats/${chatId}`);

  await page.locator('.path-toggle').click();
  const panel = page.getByRole('dialog', { name: 'Review' });
  await expect(panel).toBeVisible();
  expect(await panel.evaluate((el) => el.matches(':modal'))).toBe(false);
  await expect(page.locator('dialog:modal')).toHaveCount(0);
});
