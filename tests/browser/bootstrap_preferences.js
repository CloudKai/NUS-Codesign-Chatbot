/** Verify bootstrap preference handoff, normal mutation reconciliation and responsive layout. */
async page => {
  const assert = (condition, message) => { if (!condition) throw Error(message); };
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.evaluate(async () => {
    const response = await fetch('/api/v1/reader/preferences', { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ appearance: 'Dark', display_name: 'Synthetic CDE2300 Student', default_mode: 'project' }) });
    if (!response.ok) throw Error('Synthetic preferences setup failed');
  });
  await page.reload();
  const nav = page.getByRole('complementary', { name: 'Your notebooks' });
  await nav.waitFor();
  await page.waitForFunction(() => document.documentElement.dataset.appearance === 'Dark');
  await page.getByText('Synthetic CDE2300 Student', { exact: true }).waitFor();
  await page.getByRole('button', { name: 'Switch to day mode', exact: true }).click();
  await page.waitForFunction(() => document.documentElement.dataset.appearance === 'Light');
  await page.reload();
  await nav.waitFor();
  await page.waitForFunction(() => document.documentElement.dataset.appearance === 'Light');
  for (const [width, height] of [[1440, 960], [390, 844]]) {
    await page.setViewportSize({ width, height });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'No horizontal overflow');
    await page.screenshot({ path: `/private/tmp/cde2300-bootstrap-${width}.png` });
  }
  await page.setViewportSize({ width: 1440, height: 960 });
  assert(!errors.length, `Unexpected JS exceptions: ${errors.join(', ')}`);
  return 'PASS: bootstrap theme/name, theme mutation/reload, desktop/mobile and no JS exceptions';
}
