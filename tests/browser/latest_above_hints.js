/** Run after chat_latest_control.js on the disposable mock app. */
async page => {
  page.setDefaultTimeout(10000);
  const assert = (value, message) => { if (!value) throw new Error(message); };
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  await page.reload();
  await page.getByRole('radio', { name: 'Design coaching', exact: true }).check();
  const latest = page.getByRole('button', { name: 'Jump to latest message', exact: true });
  const scrollUp = async () => {
    await page.locator('.transcript').evaluate(el => { el.scrollTop = 0; });
    await latest.waitFor();
  };
  const above = async target => {
    await scrollUp();
    const circle = await latest.boundingBox();
    const hint = await target.boundingBox();
    assert(circle.y + circle.height <= hint.y, 'Place the whole circular control above hints, expanded suggestions and the collapsed toggle');
    const appearance = await latest.evaluate(el => {
      const style = getComputedStyle(el, '::before');
      const size = parseFloat(style.height) + (style.boxSizing === 'border-box' ? 0 : parseFloat(style.borderTopWidth) + parseFloat(style.borderBottomWidth));
      return { size, background: style.backgroundColor };
    });
    const gap = hint.y - (circle.y + (circle.height + appearance.size) / 2);
    assert(Math.abs(gap - 8) <= 1, `Keep an 8px visible gap above hints/suggestions, got ${gap}`);
    const panel = await page.locator('.transcript').boundingBox();
    assert(circle.y + circle.height <= panel.y + panel.height + 6, 'Float over chat content instead of reserving an opaque row');
    const outside = await page.evaluate(({ x, y }) => {
      const hit = document.elementFromPoint(x, y);
      return !!hit?.closest('.transcript');
    }, { x: circle.x - 24, y: circle.y + circle.height / 2 });
    assert(outside, 'The area beside the circle must reveal and allow interaction with the transcript');
    assert(appearance.background !== 'transparent' && !appearance.background.endsWith(', 0)'), 'Only the circle keeps an opaque surface');
  };
  const checkIn = page.getByRole('region', { name: 'Coach check-in', exact: true });
  await checkIn.waitFor();
  await above(checkIn);
  await page.getByRole('button', { name: 'Dismiss check-in', exact: true }).click();
  for (const appearance of ['Light', 'Dark']) {
    await page.evaluate(async appearance => {
      const response = await fetch('/api/v1/reader/preferences', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ appearance }) });
      if (!response.ok) throw new Error('Theme change failed');
    }, appearance);
    await page.reload();
    await page.getByRole('radio', { name: 'Design coaching', exact: true }).check();
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 960 });
      const suggestions = page.getByRole('region', { name: 'Suggestions for this stage', exact: true });
      const show = page.getByRole('button', { name: 'Show suggestions', exact: true });
      if (await show.isVisible()) await show.click();
      await suggestions.waitFor();
      await above(suggestions);
      const visible = await latest.evaluate(el => {
        const style = getComputedStyle(el, '::before');
        return { width: style.width, height: style.height };
      });
      assert(visible.width === '32px' && visible.height === '32px', 'Keep the visible circle compact');
      await page.screenshot({ path: `output/playwright/latest-control/above-expanded-${appearance}-${width}.png` });
      await suggestions.getByRole('button', { name: 'Hide', exact: true }).click();
      await above(show);
      await page.screenshot({ path: `output/playwright/latest-control/above-collapsed-${appearance}-${width}.png` });
      await latest.focus(); await page.keyboard.press('Enter');
      await latest.waitFor({ state: 'hidden' });
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'No horizontal overflow');
    }
  }
  assert(errors.length === 0, `Unexpected browser errors: ${errors.join('; ')}`);
  return 'PASS: 32px circle above coach hints and expanded/collapsed suggestions, 44px target, Light/Dark desktop/390, keyboard jump and clean console';
}
