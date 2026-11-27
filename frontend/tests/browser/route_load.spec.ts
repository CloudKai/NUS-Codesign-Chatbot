/**
 * Route-load measurement and lazy-editor guard (ticket 43).
 *
 * Boots the same disposable production-built stack as the other CI specs, signs
 * in a synthetic guest, and measures what JavaScript each student view actually
 * downloads: the home view (chat-first startup), then deep links to the routed
 * design canvas and document editor. The public contract asserted here:
 *   - the home view downloads strictly less JavaScript than the canvas/artifact
 *     routes (the heavy editors must be behind dynamic imports, not the
 *     startup bundle);
 *   - deep links still mount the real editors (lazy loading must not break
 *     direct hosting);
 *   - the hashed entry chunk stays identical across views, so the browser
 *     HTTP cache keeps working between navigations.
 * Measured transfer/parse timings are printed as one JSON line for the ledger;
 * the test only asserts structure and presence, never a wall-clock threshold.
 */
import { expect, test } from '@playwright/test';
import { startStack, tempWorkspace, type Stack } from './stack';

const WORKSPACE = tempWorkspace('codesign-pw-route-load-');
const PORT = 8126;

let stack: Stack;

test.beforeAll(async () => {
  stack = await startStack(WORKSPACE, PORT);
});

test.afterAll(async () => {
  await stack.stop();
});

interface JsLoad {
  /** Distinct JS URLs downloaded for this navigation. */
  urls: string[];
  /** Transfer bytes summed over every JS resource entry. */
  transferBytes: number;
  /** Decoded (uncompressed) JS bytes summed over every resource entry. */
  decodedBytes: number;
}

async function jsLoads(page: import('@playwright/test').Page): Promise<JsLoad> {
  return page.evaluate(() => {
    const entries = performance.getEntriesByType('resource')
      .filter((entry) => entry.name.endsWith('.js'));
    return {
      urls: [...new Set(entries.map((entry) => entry.name))],
      transferBytes: entries.reduce((sum, entry) => sum + entry.transferSize, 0),
      decodedBytes: entries.reduce((sum, entry) => sum + entry.decodedBodySize, 0),
    };
  });
}

test('the chat-first home view loads less JavaScript than the editor routes, which still mount by deep link', async ({
  page,
}) => {
  const unexpectedErrors: string[] = [];
  page.on('pageerror', (error) => unexpectedErrors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error' && !message.text().includes('status of 401')
      && !message.text().includes('Failed to load resource')) {
      unexpectedErrors.push(message.text());
    }
  });

  // Sign in a synthetic guest and create a notebook holding one canvas and one artifact.
  await page.goto(stack.url);
  const guest = page.getByRole('button', { name: 'Continue as Guest' });
  const nav = page.getByRole('complementary', { name: 'Your notebooks' });
  await guest.or(nav).waitFor();
  if (await guest.isVisible()) await guest.click();
  await nav.waitFor();
  const ids = await page.evaluate(async () => {
    const created = await fetch('/api/v1/reader/threads', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'Route load notebook' }),
    });
    if (!created.ok) throw new Error(`Synthetic notebook creation failed: ${created.status}`);
    const { notebook } = await created.json();
    const artifact = await fetch(`/api/v1/reader/threads/${notebook.id}/artifacts`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: 'Route load artifact', kind: 'notes', document: { type: 'doc', content: [] } }),
    });
    if (!artifact.ok) throw new Error(`Synthetic artifact creation failed: ${artifact.status}`);
    const canvas = await fetch(`/api/v1/reader/threads/${notebook.id}/canvases`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: 'Route load canvas', graph: { nodes: [], edges: [] } }),
    });
    if (!canvas.ok) throw new Error(`Synthetic canvas creation failed: ${canvas.status}`);
    const artifactBody = await artifact.json();
    const canvasBody = await canvas.json();
    return { folderId: notebook.id, artifactId: artifactBody.id, canvasId: canvasBody.id };
  });

  // 1. Chat-first home startup.
  const homeStart = Date.now();
  await page.goto(stack.url);
  await nav.waitFor();
  const homeMs = Date.now() - homeStart;
  const home = await jsLoads(page);
  expect(home.urls.length).toBeGreaterThan(0);

  // 2. Routed document editor deep link.
  const artifactStart = Date.now();
  await page.goto(`${stack.url}/pilot/notebooks/${ids.folderId}/artifacts/${ids.artifactId}`);
  await page.getByRole('region', { name: 'Document editor' }).waitFor();
  const artifactMs = Date.now() - artifactStart;
  const artifact = await jsLoads(page);

  // 3. Routed design canvas deep link.
  const canvasStart = Date.now();
  await page.goto(`${stack.url}/pilot/notebooks/${ids.folderId}/canvases/${ids.canvasId}`);
  await page.getByRole('region', { name: 'Design canvas' }).waitFor();
  const canvasMs = Date.now() - canvasStart;
  const canvas = await jsLoads(page);

  // The heavy editors must not ride in the startup bundle: the home view
  // downloads strictly fewer JS resources than either editor route.
  expect(artifact.urls.length).toBeGreaterThan(home.urls.length);
  expect(canvas.urls.length).toBeGreaterThan(home.urls.length);
  expect(artifact.transferBytes).toBeGreaterThan(home.transferBytes);
  expect(canvas.transferBytes).toBeGreaterThan(home.transferBytes);

  // Hashed asset caching: the entry chunk seen on the home view is reused
  // unchanged by the editor routes, so the browser cache stays effective.
  const entryChunk = home.urls.find((url) => url.includes('/assets/index-'));
  expect(entryChunk).toBeTruthy();
  expect(canvas.urls).toContain(entryChunk!);
  expect(artifact.urls).toContain(entryChunk!);

  // One JSON evidence line for the implementation ledger (no wall-clock assertions).
  console.log(`route-load-measurement ${JSON.stringify({
    home: { js_urls: home.urls.length, transfer_bytes: home.transferBytes, decoded_bytes: home.decodedBytes, ready_ms: homeMs },
    artifact_route: { js_urls: artifact.urls.length, transfer_bytes: artifact.transferBytes, decoded_bytes: artifact.decodedBytes, editor_ready_ms: artifactMs },
    canvas_route: { js_urls: canvas.urls.length, transfer_bytes: canvas.transferBytes, decoded_bytes: canvas.decodedBytes, editor_ready_ms: canvasMs },
  })}`);

  expect(unexpectedErrors).toEqual([]);
});
