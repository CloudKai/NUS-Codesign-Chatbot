/** Exercise actual activity states and saved recovery against the disposable fixture. */
async page => {
  const assert = (condition, message) => { if (!condition) throw Error(message); };
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const origin = new URL(page.url()).origin;
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto(origin);
  const guest = page.getByRole('button', { name: 'Continue as Guest' });
  const nav = page.getByRole('complementary', { name: 'Your notebooks' });
  await guest.or(nav).waitFor();
  if (await guest.isVisible()) await guest.click();
  await nav.waitFor();
  const name = await page.evaluate(async () => {
    const response = await fetch('/api/v1/reader/threads', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind: 'chat' }) });
    if (!response.ok) throw Error(`Create failed: ${response.status}`);
    const { notebook } = await response.json();
    const name = `Progress feedback ${notebook.id}`;
    const saved = await fetch(`/api/v1/reader/threads/${notebook.id}/settings`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) });
    if (!saved.ok) throw Error('Rename failed');
    return name;
  });
  await page.reload();
  await nav.getByRole('button', { name, exact: true }).click();
  await page.getByRole('radio', { name: 'Design coaching', exact: true }).check();
  const draft = page.getByRole('textbox', { name: 'Your project contribution', exact: true });
  await draft.fill('Older residents need safer crossings near the market. What should we investigate?');
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  const progress = page.locator('.chat-progress');
  await progress.waitFor();
  assert(!await progress.locator('.chat-progress-explanation, .chat-progress-percent').count(), 'Do not invent percentages or infer AWS startup');
  assert(!/\d+%|estimated/i.test(await progress.innerText()), 'Activity makes no fabricated completion claim');
  assert(!await progress.getByRole('progressbar').getAttribute('aria-valuenow'), 'Unknown real progress has no numeric accessibility claim');
  await page.screenshot({ path: '/private/tmp/chat-progress-desktop.png' });
  for (const theme of ['Light', 'Dark']) {
    await page.evaluate(value => { document.documentElement.dataset.appearance = value; }, theme);
    await page.setViewportSize({ width: 390, height: 844 });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Mobile has no horizontal overflow');
    await page.screenshot({ path: `/private/tmp/chat-progress-mobile-${theme}.png` });
  }
  await page.emulateMedia({ reducedMotion: 'reduce' });
  assert(await progress.locator('.chat-progress-fill').evaluate(element => getComputedStyle(element).transitionDuration) === '0s', 'Reduced motion disables the fill transition');
  await page.locator('.chat-progress[data-phase="writing"]').waitFor({ timeout: 15000 });
  assert(!await progress.getByRole('progressbar').getAttribute('aria-valuenow'), 'Writing remains indeterminate');
  await page.locator('.chat-progress[data-phase="saving"]').waitFor({ timeout: 20000 });
  assert(!await progress.getByRole('progressbar').getAttribute('aria-valuenow'), 'Saving does not imply completion');
  await page.locator('.chat-progress[data-phase="saved"]').waitFor({ timeout: 10000 });
  assert(await progress.getByRole('progressbar').getAttribute('aria-valuenow') === '100', 'Only a saved reply completes');
  await progress.waitFor({ state: 'hidden' });
  await page.getByRole('button', { name: 'Send message', exact: true }).waitFor();
  await page.reload();
  await page.locator('.message.coach').waitFor();
  assert(await page.locator('.message.coach').count() === 1, 'Saved reply survives reload exactly once');

  // A failed send must preserve its receipt without completing the progress bar or replaying it.
  let sends = 0;
  await page.route('**/project/stream', async route => { sends++; await route.fulfill({ status: 503, body: '' }); });
  await draft.fill('Keep this question after a failed send.');
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  await page.getByRole('button', { name: 'Retry same question', exact: true }).waitFor();
  assert(!await page.locator('.chat-progress[data-phase="saved"]').count(), 'Failure never completes');
  assert(await draft.inputValue() === 'Keep this question after a failed send.', 'Failure retains the draft');
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  assert(sends === 1, 'Focus does not replay generation');
  await page.getByRole('button', { name: 'Discard and edit', exact: true }).click();
  await page.unroute('**/project/stream');

  // Withdrawn text and confirmed cancellation must never appear as saved success.
  await page.route('**/project/stream', async route => {
    const request = route.request().postDataJSON();
    const thread = new URL(route.request().url()).pathname.split('/')[5];
    await route.fulfill({ status: 200, contentType: 'application/x-ndjson', body: [
      { event: 'started', thread_id: thread, idempotency_key: request.idempotency_key, stage: 'problem_identification' },
      { event: 'reply_delta', text: 'A provisional reply' },
      { event: 'reply_discard' },
      { event: 'error', status: 409, category: 'cancelled', detail: 'Cancelled' },
    ].map(event => JSON.stringify(event)).join('\n') + '\n' });
  });
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  await page.getByText('Generation stopped. Your prompt is kept.', { exact: true }).waitFor();
  assert(!await progress.count(), 'Cancelled progress disappears');
  assert(!await page.locator('.message.preview').count(), 'Discard removes provisional content');
  await page.unroute('**/project/stream');

  await page.setViewportSize({ width: 1440, height: 960 });
  await page.context().clearCookies();
  await page.evaluate(() => window.dispatchEvent(new StorageEvent('storage', {
    key: 'codesign-signed-out', newValue: String(Date.now()),
  })));
  await guest.waitFor();
  await guest.click();
  await nav.waitFor();
  assert(!await nav.getByRole('button', { name, exact: true }).count(), 'A new guest cannot see the previous owner’s cached notebook');
  assert(!errors.length, `Browser errors: ${errors.join(', ')}`);
  return 'PASS: actual activity, streaming, saving, durable recovery, failure, cancellation, discard, owner isolation, no replay, themes, mobile, and reduced motion';
}
