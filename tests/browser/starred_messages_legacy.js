/** Run after seeding the disposable guest's Imported bookmarks QA imported history. */
async page => {
  await page.unrouteAll({ behavior: 'wait' });
  await page.setViewportSize({ width: 390, height: 960 });
  await page.goto('http://127.0.0.1:8094/');
  const assert = (value, text) => { if (!value) throw new Error(text); };
  const nav = page.getByRole('complementary', { name: 'Your notebooks' });
  if (!await nav.isVisible()) await page.getByRole('button', { name: 'Open navigation', exact: true }).click();
  await nav.getByRole('button', { name: 'Imported bookmarks QA', exact: true }).click();
  await page.getByRole('heading', { name: 'Imported bookmarks QA', exact: true }).waitFor();
  await page.getByRole('button', { name: /Review/ }).filter({ hasText: 'Review' }).first().click();
  await page.getByRole('tab', { name: 'My work', exact: true }).click();
  const work = page.getByRole('tabpanel', { name: 'My work', exact: true });
  await work.getByRole('button', { name: /No stage/ }).waitFor();
  const none = work.getByRole('button', { name: /No stage/ });
  assert(await none.getAttribute('aria-expanded') === 'false', 'Populated No stage starts collapsed');
  assert(!(await work.innerText()).includes('Unstarred work must stay out'), 'Unstarred legacy work must be excluded');
  await none.click();
  await work.getByText('Historical idea without a saved stage.', { exact: true }).waitFor();
  await page.screenshot({ path: 'output/playwright/stars-31/legacy-no-stage-390.png' });
  await work.locator('#bookmarks-none').getByRole('button', { name: 'Remove star' }).click();
  await none.waitFor({ state: 'detached' });
  assert(await work.locator('.bookmark-heading').count() === 5, 'No stage disappears after its last star is removed');
  const empty = work.getByRole('button', { name: /Concept generation/ });
  await empty.click();
  await work.getByText('No starred messages in this stage yet.', { exact: true }).first().waitFor();
  return 'Legacy No stage, removal and empty-state checks passed';
}
