/**
 * Selected project export through the production-built reader (ticket 52).
 *
 * The disposable guest stack serves the deterministic mock provider, so this
 * spec signs in, seeds a notebook with a saved document and canvas through the
 * same-origin reader API, then selects exactly that saved work on the notebook
 * page and downloads the bounded project export. No live AWS, Cognito or paid
 * provider is touched.
 */
import { expect, test } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { startStack, tempWorkspace, type Stack } from './stack';

const WORKSPACE = tempWorkspace('codesign-pw-project-export-');
const PORT = 8130;

let stack: Stack;

test.beforeAll(async () => {
  stack = await startStack(WORKSPACE, PORT);
});

test.afterAll(async () => {
  await stack.stop();
});

test('guest selects saved documents and canvases and downloads the project export', async ({
  page,
}) => {
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

  // Seed one notebook with one saved document and one canvas through the API.
  const seeded = await page.evaluate(async () => {
    const created = await fetch('/api/v1/reader/threads', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'Export journey notebook' }),
    });
    if (!created.ok) throw new Error(`Notebook creation failed: ${created.status}`);
    const { notebook } = await created.json();
    const document = await fetch(`/api/v1/reader/threads/${notebook.id}/artifacts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: 'Exported field notes', kind: 'notes',
        document: { type: 'doc', content: [{ type: 'paragraph', content: [
          { type: 'text', text: 'Crossing observations' }] }] },
      }),
    });
    if (!document.ok) throw new Error(`Artifact creation failed: ${document.status}`);
    const canvas = await fetch(`/api/v1/reader/threads/${notebook.id}/canvases`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: 'Exported map', graph: { nodes: [], edges: [] } }),
    });
    if (!canvas.ok) throw new Error(`Canvas creation failed: ${canvas.status}`);
    return { id: notebook.id, name: 'Export journey notebook' };
  });

  await page.reload();
  await nav.getByRole('button', { name: seeded.name, exact: true }).first().click();

  await page.getByRole('tab', { name: 'Export' }).click();
  await page.getByRole('checkbox', { name: 'Include Exported field notes' }).check();
  await page.getByRole('checkbox', { name: 'Include Exported map' }).check();

  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download project export' }).click();
  const file = await download;
  expect(file.suggestedFilename().endsWith('-project.json')).toBe(true);
  const path = await file.path();
  const envelope = JSON.parse(await readFile(path!, 'utf8'));
  expect(envelope.kind).toBe('project_export');
  expect(envelope.title).toBe(seeded.name);
  expect(envelope.artifacts.map((entry: { title: string }) => entry.title))
    .toEqual(['Exported field notes']);
  expect(envelope.canvases.map((entry: { title: string }) => entry.title))
    .toEqual(['Exported map']);

  expect(unexpectedErrors).toEqual([]);
});
