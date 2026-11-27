import { chromium } from '@playwright/test';
import { startStack, tempWorkspace } from './stack.ts';
const WORKSPACE = tempWorkspace('codesign-pw-dbg-');
const stack = await startStack(WORKSPACE, 8140);
const browser = await chromium.launch();
const page = await browser.newPage();
await page.goto(stack.url);
const guest = page.getByRole('button', { name: 'Continue as Guest' });
const nav = page.getByRole('complementary', { name: 'Your notebooks' });
await guest.or(nav).waitFor();
if (await guest.isVisible()) await guest.click();
await nav.waitFor();
const ids = await page.evaluate(async () => {
  const created = await fetch('/api/v1/reader/threads', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: 'DBG' }) });
  const { notebook } = await created.json();
  const artifact = await fetch(`/api/v1/reader/threads/${notebook.id}/artifacts`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: 'D', kind: 'notes', document: { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'Hello' }] }] } }) });
  const body = await artifact.json();
  return { folderId: notebook.id, artifactId: body.id };
});
await page.goto(`${stack.url}/pilot/notebooks/${ids.folderId}/artifacts/${ids.artifactId}`);
await page.getByRole('region', { name: 'Document editor' }).waitFor();
await page.getByRole('button', { name: 'Add to canvas' }).click();
const dialog = page.getByRole('dialog', { name: 'Add document content to a canvas' });
await dialog.waitFor();
console.log('open dialogs:', await page.evaluate(() => [...document.querySelectorAll('dialog')].map(d => ({ label: d.getAttribute('aria-label'), open: d.open, modal: d.matches(':modal') }))));
for (let i = 0; i < 8; i++) {
  await page.keyboard.press('Tab');
  console.log(i, await page.evaluate(() => `${document.activeElement?.tagName} ${document.activeElement?.getAttribute('aria-label') ?? document.activeElement?.textContent?.slice(0, 20)} inDialog=${document.querySelector('dialog[open]')?.contains(document.activeElement)}`));
}
await browser.close(); await stack.stop();
