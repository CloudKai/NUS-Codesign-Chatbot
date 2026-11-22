/** Responsive NDJSON previews; run after real_reply_streaming.js on the delayed mock fixture. */
async page => {
  page.setDefaultTimeout(10000);
  const assert = (ok, message) => { if (!ok) throw Error(message); };
  const errors = []; let sends = 0;
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  page.on('request', request => {
    if (request.method() === 'POST' && /\/(project|revise)\/stream$/.test(request.url())) {
      sends++;
      assert(request.headers()['x-coach-reply-deltas'] === '1', 'Both normal and edited sends request partial reply text');
    }
  });
  let cases = 0;
  const preview = page.locator('.message.preview');
  async function observe(tag) {
    await preview.waitFor();
    const first = await preview.locator('.message-content').innerText();
    assert(first.length > 0 && await preview.getByRole('button').count() === 0, 'Provisional text has no saved-message actions');
    await page.waitForFunction(n => (document.querySelector('.message.preview .message-content')?.textContent?.length ?? 0) > n, first.length);
    await preview.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `output/playwright/reply-streaming/${tag}.png` });
    await page.getByRole('button', { name: 'Stop generating', exact: true }).waitFor({ state: 'hidden' });
    await preview.waitFor({ state: 'hidden' });
    await page.getByRole('button', { name: 'Jump to latest message, coach is working', exact: true }).waitFor({ state: 'hidden' });
  }
  for (const appearance of ['Light', 'Dark']) {
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 960 });
      await page.evaluate(async ({ appearance, reduce_motion }) => {
        const response = await fetch('/api/v1/reader/preferences', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ appearance, reduce_motion }) });
        if (!response.ok) throw Error('Preference update failed');
      }, { appearance, reduce_motion: width === 390 });
      await page.emulateMedia({ reducedMotion: width === 390 ? 'reduce' : 'no-preference' });
      await page.reload();
      const draft = page.getByRole('textbox', { name: 'Your project contribution', exact: true });
      await draft.fill(`The design should account for crossing time, ${appearance} ${width}.`);
      await page.getByRole('button', { name: 'Send message', exact: true }).click();
      await observe(`normal-${appearance}-${width}`);
      await draft.fill('Keep the next question separate.');
      const id = await page.locator('.message.student').last().getAttribute('data-message-id');
      const message = page.locator(`[data-message-id="${id}"]`);
      await message.getByRole('button', { name: 'Edit message', exact: true }).click();
      await message.getByRole('textbox', { name: 'Revise your message', exact: true }).fill(`The design should account for older residents and crossing time, ${appearance} ${width}.`);
      await message.getByRole('button', { name: 'Confirm edit & ask again', exact: true }).click();
      await observe(`edited-${appearance}-${width}`);
      assert(await draft.inputValue() === 'Keep the next question separate.', 'Keep the separate draft after a streamed edit');
      cases++;
      assert(sends === cases * 2, 'No automatic generation replay');
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'No horizontal overflow');
    }
  }
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  assert(errors.length === 0, `Unexpected browser errors: ${errors.join('; ')}`);
  return 'PASS: normal/edit incremental previews, Light/Dark desktop/390, app and OS reduced motion, no replay, no provisional save actions, retained draft and clean console';
}
