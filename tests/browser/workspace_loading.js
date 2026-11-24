/** Measure synthetic startup/navigation requests with zero or injected transport delay. */
async page => {
  const origin = new URL(page.url()).origin;
  const nav = page.getByRole('complementary', { name: 'Your notebooks' });
  const guest = page.getByRole('button', { name: 'Continue as Guest', exact: true });
  await guest.or(nav).waitFor();
  if (await guest.isVisible()) await guest.click();
  await nav.waitFor();
  const created = await page.evaluate(async () => {
    const response = await fetch('/api/v1/reader/threads', { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind: 'chat' }) });
    if (!response.ok) throw Error('Synthetic fixture create failed');
    const notebook = (await response.json()).notebook;
    const name = `Loading measurement ${notebook.id}`;
    await fetch(`/api/v1/reader/threads/${notebook.id}/settings`, { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) });
    return { ...notebook, name };
  });
  const rows = [];
  for (const delayMs of [0, 100]) {
    const delayed = async route => {
      if (delayMs) await new Promise(resolve => setTimeout(resolve, delayMs));
      await route.continue().catch(() => {}); // Reload can cancel an already paused request.
    };
    await page.route('**/api/v1/reader/**', delayed);
    for (let trial = 0; trial < 3; trial++) {
      await page.waitForTimeout(800); // Let the prior SPA navigation's trailing reads drain.
      await page.evaluate(() => {
        for (const key of Object.keys(sessionStorage)) if (key.startsWith('codesign-selected:')) sessionStorage.removeItem(key);
      });
      await page.goto('about:blank');
      let requests = [];
      const observe = request => {
        const url = new URL(request.url());
        if (url.pathname.startsWith('/api/')) requests.push(url.pathname.replace(/\/threads\/[^/]+\//, '/threads/{id}/'));
      };
      page.on('request', observe);
      let started = Date.now();
      await page.goto(origin);
      await nav.getByRole('button', { name: created.name, exact: true }).waitFor();
      const visibleMs = Date.now() - started;
      await page.waitForLoadState('networkidle');
      rows.push({ scenario: 'startup', delayMs, trial, visibleMs, settledMs: Date.now() - started, requests });
      requests = [];
      started = Date.now();
      await nav.getByRole('button', { name: created.name, exact: true }).click();
      await page.locator('#lecture-question').waitFor();
      const openMs = Date.now() - started;
      await page.waitForTimeout(800); // SPA navigation does not reset document networkidle state.
      rows.push({ scenario: 'open-chat', delayMs, trial, visibleMs: openMs, settledMs: Date.now() - started, requests });
      page.off('request', observe);
    }
    await page.unroute('**/api/v1/reader/**', delayed);
  }
  return { scope: 'local browser, synthetic guest/empty chat, no model call; injected delay is not measured network RTT', rows };
}
