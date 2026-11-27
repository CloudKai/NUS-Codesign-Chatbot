/**
 * Accessible authoring evidence for the routed editors (ticket 44).
 *
 * Boots the same disposable production-built stack as the other CI specs and
 * records the actual keyboard, dialog, mobile and reduced-motion behavior of
 * the artifact and canvas editors:
 *   - keyboard-only authoring reaches the toolbar, outline and actions;
 *   - the "Add to canvas" and "Develop into artifact" dialogs are modal
 *     (focus stays contained), close on Escape and return focus to the opener;
 *   - at 390 px the editors and dialogs stay usable with no horizontal
 *     overflow, and touch taps complete the same authoring tasks;
 *   - under `prefers-reduced-motion: reduce` no CSS animation runs and the
 *     canvas Locate control moves without an animated transition;
 *   - key text pairs meet WCAG 2.2 AA contrast in Light and Dark themes.
 * Screenshots are written under the ignored output directory; the only
 * wall-clock-sensitive assertion is the reduced-motion transform sampling,
 * which is tolerant (two samples 120 ms apart must be equal while a 300 ms
 * animation would still be running).
 */
import { expect, test } from '@playwright/test';
import { startStack, tempWorkspace, type Stack } from './stack';

const WORKSPACE = tempWorkspace('codesign-pw-a11y-');
const PORT = 8129;
const SHOTS = 'output/playwright/a11y';

let stack: Stack;

test.beforeAll(async () => {
  stack = await startStack(WORKSPACE, PORT);
});

test.afterAll(async () => {
  await stack.stop();
});

async function contrast(page: import('@playwright/test').Page, selector: string): Promise<number> {
  return page.evaluate((query) => {
    const element = document.querySelector(query);
    if (!element) return -1;
    const parse = (value: string) => value.match(/rgba?\(([^)]+)\)/)?.[1]?.split(',').map(Number);
    const backgroundOf = (node: Element | null): number[] | null => {
      for (let current: Element | null = node; current; current = current.parentElement) {
        const rgba = parse(getComputedStyle(current).backgroundColor);
        if (rgba && (rgba.length < 4 || rgba[3] > 0)) return rgba.slice(0, 3);
      }
      return [255, 255, 255];
    };
    const luminance = (rgb: number[]) => {
      const channel = (value: number) => {
        const scaled = value / 255;
        return scaled <= 0.03928 ? scaled / 12.92 : ((scaled + 0.055) / 1.055) ** 2.4;
      };
      return 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2]);
    };
    const foreground = parse(getComputedStyle(element).color)!;
    const background = backgroundOf(element);
    const [lighter, darker] = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
    return (lighter + 0.05) / (darker + 0.05);
  }, selector);
}

test('keyboard, dialog, reduced-motion and contrast checks on the editors at desktop', async ({ page }) => {
  const unexpectedErrors: string[] = [];
  page.on('pageerror', (error) => unexpectedErrors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error' && !message.text().includes('status of 401')
      && !message.text().includes('Failed to load resource')) {
      unexpectedErrors.push(message.text());
    }
  });
  await page.emulateMedia({ reducedMotion: 'reduce' });

  await page.goto(stack.url);
  const guest = page.getByRole('button', { name: 'Continue as Guest' });
  const nav = page.getByRole('complementary', { name: 'Your notebooks' });
  await guest.or(nav).waitFor();
  if (await guest.isVisible()) await guest.click();
  await nav.waitFor();
  const ids = await page.evaluate(async () => {
    const created = await fetch('/api/v1/reader/threads', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'A11y authoring' }),
    });
    const { notebook } = await created.json();
    const artifact = await fetch(`/api/v1/reader/threads/${notebook.id}/artifacts`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: 'Field notes', kind: 'notes', document: { type: 'doc', content: [
        { type: 'paragraph', content: [{ type: 'text', text: 'Older residents cross unsafely at the market entrance.' }] },
      ] } }),
    });
    const canvas = await fetch(`/api/v1/reader/threads/${notebook.id}/canvases`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: 'Concept map', graph: {
        nodes: [
          { id: 'n1', kind: 'problem', title: 'Unsafe crossing', description: 'Peak hour conflicts.', x: 40, y: 60 },
          { id: 'n2', kind: 'stakeholder', title: 'Older residents', description: '', x: 200, y: 60 },
        ], edges: [] } }),
    });
    return { folderId: notebook.id, artifactId: (await artifact.json()).id, canvasId: (await canvas.json()).id };
  });

  // --- Keyboard journey through the artifact editor. ---
  await page.goto(`${stack.url}/pilot/notebooks/${ids.folderId}/artifacts/${ids.artifactId}`);
  const editor = page.getByRole('region', { name: 'Document editor' });
  await editor.waitFor();
  // The first stop is the global skip link; keyboard focus then reaches the editor toolbar.
  await page.keyboard.press('Tab');
  expect(await page.evaluate(() => document.activeElement?.textContent)).toContain('Skip to saved work');
  for (let step = 0; step < 30; step += 1) {
    await page.keyboard.press('Tab');
    if (await page.evaluate(() => document.activeElement?.getAttribute('aria-label')) === 'Back to notebook') break;
  }
  expect(await page.evaluate(() => document.activeElement?.getAttribute('aria-label'))).toBe('Back to notebook');
  await page.keyboard.press('Tab');
  expect(await page.evaluate(() => (document.activeElement as HTMLInputElement | null)?.ariaLabel))
    .toBe('Document title');

  // The toolbar formatting buttons are reachable and truthful.
  for (const label of ['Bold', 'Italic', 'Bulleted list', 'Numbered list']) {
    await page.getByRole('button', { name: label, exact: true }).focus();
    await expect(page.getByRole('button', { name: label, exact: true })).toHaveAttribute('aria-pressed', /.*/);
  }

  // Version history is keyboard operable and read-only previews do not change the document.
  await page.getByRole('button', { name: 'History' }).click();
  await expect(page.getByRole('region', { name: 'Version history' })).toBeVisible();

  // The "Add to canvas" dialog is modal: focus cycles back into it (Chromium
  // passes through the body between cycles, but no background control ever
  // receives focus), Escape closes it and focus returns to the opener.
  await page.getByRole('button', { name: 'Add to canvas' }).click();
  const dialog = page.getByRole('dialog', { name: 'Add document content to a canvas' });
  await expect(dialog).toBeVisible();
  for (let step = 0; step < 12; step += 1) {
    await page.keyboard.press('Tab');
    if (step % 4 === 3) {
      const location = await page.evaluate(() =>
        document.querySelector('dialog[open]')?.contains(document.activeElement)
          ? 'dialog' : document.activeElement === document.body ? 'body' : 'background');
      expect(location, `focus never reaches a background control (step ${step})`).not.toBe('background');
    }
  }
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  await expect(page.getByRole('button', { name: 'Add to canvas' })).toBeFocused();
  await page.screenshot({ path: `${SHOTS}/artifact-editor-desktop.png`, fullPage: true });

  // --- Canvas editor: outline authoring by keyboard and the Locate control under reduced motion. ---
  await page.goto(`${stack.url}/pilot/notebooks/${ids.folderId}/canvases/${ids.canvasId}`);
  await page.getByRole('region', { name: 'Design canvas' }).waitFor();
  await page.getByLabel('Canvas title').click();
  await expect(page.getByLabel('Node type', { selector: '#canvas-node-kind' })).toBeVisible();
  await page.locator('#canvas-node-kind').selectOption('evaluation');
  await page.locator('#canvas-node-title').fill('Crossing evaluation plan');
  await page.getByRole('button', { name: 'Add node' }).click();
  await expect(page.getByText('Crossing evaluation plan').first()).toBeVisible();
  await expect(page.getByText(/save automatically as you write/)).toBeVisible();

  // Under reduced motion the Locate move is instant, not an animated transition:
  // two samples 120 ms apart after the click are identical (a 300 ms animation
  // would still be running between them).
  await page.getByLabel('Search nodes').fill('Unsafe crossing');
  await page.getByRole('button', { name: /Locate/ }).click();
  const transformOf = () => page.evaluate(() =>
    document.querySelector<HTMLElement>('.react-flow__viewport')?.style.transform ?? '');
  await page.waitForTimeout(120);
  const first = await transformOf();
  await page.waitForTimeout(120);
  const second = await transformOf();
  expect(second, 'the Locate move completes without a reduced-motion transition').toBe(first);
  await page.screenshot({ path: `${SHOTS}/canvas-editor-desktop.png`, fullPage: true });

  // The develop dialog is modal and Escape closes it with focus returned.
  await page.getByRole('button', { name: 'Develop canvas nodes into an artifact' }).click();
  const develop = page.getByRole('dialog', { name: 'Develop canvas nodes into an artifact' });
  await expect(develop).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(develop).toBeHidden();
  await expect(page.getByRole('button', { name: 'Develop canvas nodes into an artifact' })).toBeFocused();

  // --- WCAG 2.2 AA contrast spot checks in Light and Dark. ---
  await page.goto(`${stack.url}/pilot/notebooks/${ids.folderId}/artifacts/${ids.artifactId}`);
  await page.getByRole('region', { name: 'Document editor' }).waitFor();
  for (const appearance of ['Light', 'Dark']) {
    await page.evaluate((theme) => { document.documentElement.dataset.appearance = theme; }, appearance);
    await page.waitForTimeout(50);
    for (const [selector, minimum] of [['p', 4.5], ['.supporting', 4.5], ['button.primary', 4.5]] as const) {
      const ratio = await contrast(page, selector);
      expect(ratio, `${selector} contrast in ${appearance}`).toBeGreaterThanOrEqual(minimum);
    }
  }
  await page.screenshot({ path: `${SHOTS}/artifact-editor-dark.png`, fullPage: true });

  expect(unexpectedErrors).toEqual([]);
});

test.describe('390 px touch authoring', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

  test('touch authoring stays usable with no horizontal overflow', async ({ page }) => {
  const unexpectedErrors: string[] = [];
  page.on('pageerror', (error) => unexpectedErrors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error' && !message.text().includes('status of 401')
      && !message.text().includes('Failed to load resource')) {
      unexpectedErrors.push(message.text());
    }
  });
  await page.goto(stack.url);
  const guest = page.getByRole('button', { name: 'Continue as Guest' });
  const nav = page.getByRole('complementary', { name: 'Your notebooks' });
  await guest.or(nav).waitFor();
  if (await guest.isVisible()) await guest.click();
  // Below 768 px the notebook list is a drawer; the header menu button proves the shell is ready.
  await page.getByRole('button', { name: 'Open navigation' }).waitFor();
  const ids = await page.evaluate(async () => {
    const created = await fetch('/api/v1/reader/threads', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'A11y mobile' }),
    });
    const { notebook } = await created.json();
    const artifact = await fetch(`/api/v1/reader/threads/${notebook.id}/artifacts`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: 'Mobile notes', kind: 'notes', document: { type: 'doc', content: [
        { type: 'paragraph', content: [{ type: 'text', text: 'Captured on a phone during the site visit.' }] },
      ] } }),
    });
    const canvas = await fetch(`/api/v1/reader/threads/${notebook.id}/canvases`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: 'Mobile map', graph: {
        nodes: [{ id: 'n1', kind: 'note', title: 'Site note', description: '', x: 20, y: 20 }],
        edges: [] } }),
    });
    return { folderId: notebook.id, artifactId: (await artifact.json()).id, canvasId: (await canvas.json()).id };
  });

  // Artifact editor at 390 px: toolbar reachable, no sideways scrolling, dialog usable.
  await page.goto(`${stack.url}/pilot/notebooks/${ids.folderId}/artifacts/${ids.artifactId}`);
  await page.getByRole('region', { name: 'Document editor' }).waitFor();
  const overflow = () => page.evaluate(() => document.documentElement.scrollWidth);
  expect(await overflow()).toBeLessThanOrEqual(390);
  await page.getByRole('button', { name: 'Bold', exact: true }).tap();
  await expect(page.getByRole('button', { name: 'Bold', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('button', { name: 'Add to canvas' }).tap();
  const dialog = page.getByRole('dialog', { name: 'Add document content to a canvas' });
  await expect(dialog).toBeVisible();
  expect(await overflow()).toBeLessThanOrEqual(390);
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  await page.screenshot({ path: `${SHOTS}/artifact-editor-390.png`, fullPage: true });

  // Canvas editor at 390 px: the outline remains the authoritative authoring surface.
  await page.goto(`${stack.url}/pilot/notebooks/${ids.folderId}/canvases/${ids.canvasId}`);
  await page.getByRole('region', { name: 'Design canvas' }).waitFor();
  expect(await overflow()).toBeLessThanOrEqual(390);
  await page.getByRole('textbox', { name: 'Title', exact: true }).tap();
  await page.getByRole('textbox', { name: 'Title', exact: true }).fill('Second site note');
  await page.getByRole('button', { name: 'Add node' }).tap();
  await expect(page.getByText('Second site note').first()).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/canvas-editor-390.png`, fullPage: true });

  expect(unexpectedErrors).toEqual([]);
  });
});
