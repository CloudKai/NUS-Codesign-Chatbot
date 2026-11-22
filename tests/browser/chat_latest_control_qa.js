/** Responsive Light/Dark working/finished control, motion preference and bounded My work previews. */
async page => {
  page.setDefaultTimeout(10000);
  const assert = (value, message) => { if (!value) throw new Error(message); };
  const title = await page.getByRole('region', { name: 'Saved conversation' }).getByRole('heading', { level: 2 }).first().innerText();
  const fixture = await page.evaluate(async title => {
    const list = await (await fetch('/api/v1/reader/threads')).json();
    const id = list.notebooks.find(item => item.name === title).id;
    const bookmarks = await (await fetch(`/api/v1/reader/threads/${id}/bookmarks`)).json();
    const project = await (await fetch(`/api/v1/reader/threads/${id}/project`)).json();
    return { id, message: bookmarks.messages[0].id, group: project.stages.find(stage => stage.id === bookmarks.messages[0].stage_id)?.label ?? 'No stage' };
  }, title);
  const errors = []; let sends = 0;
  const onError = error => errors.push(error.message);
  const onConsole = message => { if (message.type() === 'error') errors.push(message.text()); };
  const onRequest = request => { if (request.method() === 'POST' && request.url().endsWith('/lecture/stream')) sends++; };
  page.on('pageerror', onError); page.on('console', onConsole); page.on('request', onRequest);
  let cases = 0;
  for (const appearance of ['Light', 'Dark']) {
    await page.evaluate(async appearance => {
      const response = await fetch('/api/v1/reader/preferences', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ appearance }) });
      if (!response.ok) throw new Error('Theme change failed');
    }, appearance);
    for (const width of [1440, 900, 390]) {
      await page.setViewportSize({ width, height: 960 });
      await page.reload();
      const latest = page.getByRole('button', { name: 'Jump to latest message', exact: true });
      await page.getByRole('region', { name: 'Saved conversation' }).waitFor();
      const review = page.getByRole('dialog', { name: 'Review', exact: true });
      if (await review.isVisible()) await review.getByRole('button', { name: 'Close Review', exact: true }).click();
      await page.waitForFunction(appearance => document.documentElement.dataset.appearance === appearance, appearance);
      let release; const gate = new Promise(resolve => { release = resolve; });
      await page.route('**/lecture/stream', async route => { await gate; await route.continue(); });
      try {
        if (appearance === 'Dark' && width === 390) await page.emulateMedia({ reducedMotion: 'reduce' });
        await page.getByRole('textbox', { name: 'Your lecture question', exact: true }).fill(`Explain another concept, ${appearance} ${width}.`);
        await page.getByRole('button', { name: 'Send message', exact: true }).click();
        const working = page.getByRole('button', { name: 'Jump to latest message, coach is working', exact: true });
        await working.waitFor();
        assert(await working.locator('.typing-dots i').count() === 3, 'Working state needs three dots');
        const box = await working.boundingBox();
        const textbox = await page.getByRole('textbox', { name: 'Your lecture question', exact: true }).boundingBox();
        assert(box.width === 44 && box.height === 44 && box.y + box.height <= textbox.y, 'Keep the circular target above the textbox');
        if (appearance === 'Dark' && width === 390) assert(await working.locator('i').first().evaluate(el => getComputedStyle(el).animationName) === 'none', 'Respect reduced motion');
        await page.locator('.transcript').evaluate(el => { el.scrollTop = 0; });
        await working.click();
        if (appearance === 'Dark' && width === 390) assert(await page.locator('.transcript').evaluate(el => el.scrollHeight - el.scrollTop - el.clientHeight < 3), 'Reduced motion skips smooth scrolling');
        await page.screenshot({ path: `output/playwright/latest-control/working-${appearance}-${width}.png` });
        release(); await working.waitFor({ state: 'hidden' });
        await latest.waitFor({ state: 'hidden' });
        await page.locator('.transcript').evaluate(el => { el.scrollTop = 0; });
        await latest.waitFor();
        await page.screenshot({ path: `output/playwright/latest-control/scrolled-${appearance}-${width}.png` });
        await latest.focus(); await page.keyboard.press('Space');
        await latest.waitFor({ state: 'hidden' });
        await page.locator('.transcript').evaluate(el => { el.scrollTop -= 25; });
        await latest.waitFor();
        await page.locator('.transcript').evaluate(el => { el.scrollTop = el.scrollHeight; });
        await latest.waitFor({ state: 'hidden' });
        assert(await page.locator('.transcript').evaluate(el => el.scrollHeight - el.scrollTop - el.clientHeight < 3), 'Keyboard arrow should return to the latest reply');
        cases++; assert(sends === cases, 'Scroll controls must not send or replay requests');
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'No page overflow');
        await page.screenshot({ path: `output/playwright/latest-control/complete-${appearance}-${width}.png` });
      } finally { release(); await page.unroute('**/lecture/stream'); await page.emulateMedia({ reducedMotion: 'no-preference' }); }
      await page.getByRole('button', { name: /Review/ }).filter({ hasText: 'Review' }).first().click();
      await page.getByRole('tab', { name: 'My work', exact: true }).click();
      const work = page.getByRole('tabpanel', { name: 'My work', exact: true });
      const group = work.getByRole('region', { name: fixture.group, exact: true });
      const toggle = group.getByRole('button', { name: fixture.group, exact: true });
      if (await toggle.getAttribute('aria-expanded') === 'false') await toggle.click();
      const preview = group.locator('.bookmark-preview').first();
      const capped = await preview.evaluate(el => el.getBoundingClientRect().height <= parseFloat(getComputedStyle(el).lineHeight) * 6 + 1);
      assert(capped, 'My work preview must stay within six lines');
      await page.getByRole('dialog', { name: 'Review', exact: true }).evaluate(el => el.scrollTo({ top: 0 }));
      await page.screenshot({ path: `output/playwright/latest-control/preview-${appearance}-${width}.png` });
      await group.getByRole('button', { name: 'Jump to message', exact: true }).click();
      await page.getByRole('dialog', { name: 'Review', exact: true }).waitFor({ state: 'hidden' });
      assert((await page.locator(`[data-message-id="${fixture.message}"]`).innerText()).length > 320, 'Full original remains intact');
    }
  }
  page.off('pageerror', onError); page.off('console', onConsole); page.off('request', onRequest);
  assert(errors.length === 0, `Unexpected errors: ${errors.join('; ')}`);
  return 'PASS: working dots and scroll-aware arrow at 1440/900/390 Light/Dark, reduced motion, keyboard scrolling, no request replay, six-line previews and intact originals';
}
