/** Visual, keyboard, empty-state and explicit failure recovery checks for the project brief. */
async page => {
  page.setDefaultTimeout(10000);
  const assert = (value, message) => { if (!value) throw new Error(message); };
  const errors = []; let expectedFailure = false;
  const pageError = error => errors.push(error.message);
  const consoleError = message => { if (message.type() === 'error' && !expectedFailure) errors.push(message.text()); };
  page.on('pageerror', pageError); page.on('console', consoleError);
  const review = page.getByRole('dialog', { name: 'Review', exact: true });
  const brief = page.getByRole('region', { name: 'Your project so far', exact: true });
  const downloadReady = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download project summary', exact: true }).click();
  const download = await downloadReady;
  await download.saveAs('output/playwright/project-brief/project-summary.md');
  for (const appearance of ['Light', 'Dark']) {
    await page.evaluate(async appearance => {
      const response = await fetch('/api/v1/reader/preferences', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ appearance }) });
      if (!response.ok) throw new Error('Theme could not save');
    }, appearance);
    await page.reload(); await brief.waitFor();
    await page.waitForFunction(appearance => document.documentElement.dataset.appearance === appearance, appearance);
    for (const width of [1440, 900, 390]) {
      await page.setViewportSize({ width, height: 960 });
      await brief.waitFor();
      assert(await brief.locator('dt').allTextContents().then(labels => labels.join('|')) === 'Who and why|Problem|Current idea|What matters|Still to explore', 'Brief field order changed');
      assert(await brief.getByText('Not yet established', { exact: true }).count() === 1, 'Only missing requirements should be unknown');
      assert(await review.evaluate(el => el.scrollWidth <= el.clientWidth), 'Review overflows horizontally');
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Page overflows horizontally');
      await page.getByRole('tab', { name: 'Summary', exact: true }).focus();
      await page.keyboard.press('ArrowLeft');
      await page.keyboard.press('ArrowRight');
      await brief.waitFor();
      const stage = page.getByRole('tabpanel', { name: 'Summary', exact: true }).getByRole('button', { name: 'Problem identification', exact: true });
      const expanded = await stage.getAttribute('aria-expanded');
      await stage.press('Enter');
      assert(await stage.getAttribute('aria-expanded') !== expanded, 'Stage keyboard disclosure failed');
      await stage.press('Space');
      await brief.scrollIntoViewIfNeeded();
      await page.screenshot({ path: `output/playwright/project-brief/brief-${appearance}-${width}.png` });
    }
  }
  await review.getByRole('button', { name: 'Close Review', exact: true }).click();
  await page.setViewportSize({ width: 1440, height: 960 });
  const newChat = await page.evaluate(async () => {
    const response = await fetch('/api/v1/reader/threads', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind: 'chat' }) });
    if (!response.ok) throw new Error('Disposable chat creation failed');
    const { notebook } = await response.json();
    const name = `Empty review ${notebook.id}`;
    const renamed = await fetch(`/api/v1/reader/threads/${notebook.id}/settings`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) });
    if (!renamed.ok) throw new Error('Disposable chat naming failed');
    return { id: notebook.id, name };
  });
  await page.reload();
  await page.getByRole('complementary', { name: 'Your notebooks' }).getByRole('button', { name: newChat.name, exact: true }).click();
  await page.getByRole('heading', { name: newChat.name, exact: true }).waitFor();
  await page.getByRole('button', { name: 'Review', exact: true }).click();
  await page.getByRole('tab', { name: 'Summary', exact: true }).click();
  await brief.getByText('Your brief will take shape as you discuss your project.', { exact: true }).waitFor();
  assert(await brief.getByText('Not yet established', { exact: true }).count() === 5, 'An empty chat must not invent any project details');
  await page.screenshot({ path: 'output/playwright/project-brief/empty.png' });
  await review.getByRole('button', { name: 'Close Review', exact: true }).click();
  await page.getByRole('textbox', { name: /Your (lecture question|project contribution)/ }).fill('Hello');
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  await page.getByRole('textbox', { name: /Your (lecture question|project contribution)/ }).waitFor();
  await page.waitForFunction(() => !document.querySelector('.send-button')?.disabled || document.querySelector('.send-button')?.closest('form')?.querySelector('textarea')?.value === '');
  let failed = 0;
  expectedFailure = true;
  await page.route('**/project/brief', route => { failed++; return route.fulfill({ status: 503, body: '{}' }); });
  await page.getByRole('button', { name: /Review/ }).filter({ hasText: 'Review' }).first().click();
  await page.getByRole('tab', { name: 'Summary', exact: true }).click();
  await brief.getByRole('button', { name: 'Summarise chat', exact: true }).click();
  await brief.getByRole('alert').waitFor();
  assert(await brief.getByText('Not summarised yet', { exact: true }).count() === 5, 'Failure must not claim missing facts have been assessed');
  await page.getByRole('tab', { name: 'My work', exact: true }).click();
  await page.getByRole('tab', { name: 'Summary', exact: true }).click();
  assert(failed === 1, 'Tab switches must not automatically replay a failed summary');
  await page.screenshot({ path: 'output/playwright/project-brief/failure.png' });
  await page.unroute('**/project/brief'); expectedFailure = false;
  const retry = brief.getByRole('button', { name: 'Summarise chat', exact: true });
  await retry.focus(); await page.keyboard.press('Enter');
  await page.waitForFunction(() => document.querySelectorAll('.project-brief-fields [data-missing] dd').length === 5 && [...document.querySelectorAll('.project-brief-fields dd')].every(el => el.textContent === 'Not yet established'));
  assert(!await brief.getByRole('alert').count(), 'Explicit retry should clear the error');
  assert(errors.length === 0, `Unexpected console errors: ${errors.join('; ')}`);
  page.off('pageerror', pageError); page.off('console', consoleError);
  return 'PASS: Light/Dark 1440/900/390, keyboard, gap/wrapping, empty unknowns, failed-summary retention and explicit retry without automatic replay';
}
