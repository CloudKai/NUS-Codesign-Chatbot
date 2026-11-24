/** Switch guests while a generation request is pending; never display its late result. */
async page => {
  const assert = (condition, message) => { if (!condition) throw Error(message); };
  const nav = page.getByRole('complementary', { name: 'Your notebooks' });
  await nav.waitFor();
  const created = await page.evaluate(async () => {
    const response = await fetch('/api/v1/reader/threads', { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind: 'chat' }) });
    if (!response.ok) throw Error('Synthetic chat creation failed');
    const notebook = (await response.json()).notebook;
    const name = `Pending identity test ${notebook.id}`;
    const renamed = await fetch(`/api/v1/reader/threads/${notebook.id}/settings`, { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) });
    if (!renamed.ok) throw Error('Synthetic chat rename failed');
    return { ...notebook, name };
  });
  await page.reload();
  await nav.getByRole('button', { name: created.name, exact: true }).first().click();
  await page.getByRole('radio', { name: 'Design coaching', exact: true }).check();
  let accept;
  let sends = 0;
  const intercepted = new Promise(resolve => { accept = resolve; });
  await page.route('**/project/stream', route => { sends++; accept(route); });
  const draft = page.getByRole('textbox', { name: 'Your project contribution', exact: true });
  await draft.fill('Synthetic owner A project prompt.');
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  const route = await intercepted;
  const request = route.request().postDataJSON();
  const aborted = page.waitForEvent('requestfailed', { predicate: req => req.url().endsWith('/project/stream') });
  await page.context().clearCookies();
  await page.evaluate(() => window.dispatchEvent(new StorageEvent('storage', {
    key: 'codesign-signed-out', newValue: String(Date.now()),
  })));
  await aborted;
  await page.getByRole('button', { name: 'Continue as Guest', exact: true }).click();
  await nav.waitFor();
  await route.fulfill({ status: 200, contentType: 'application/x-ndjson', body: [
    { event: 'started', thread_id: created.id, idempotency_key: request.idempotency_key, stage: 'problem_identification' },
    { event: 'reply_delta', text: 'OLD OWNER PRIVATE RESULT' },
    { event: 'done', turn: { response_text: 'OLD OWNER PRIVATE RESULT', assessment: { response_mode: 'coaching', citations: [] } } },
  ].map(event => JSON.stringify(event)).join('\n') + '\n' }).catch(() => {});
  await page.unroute('**/project/stream');
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  assert(!await page.getByText('OLD OWNER PRIVATE RESULT', { exact: true }).count(), 'Late private result never appears');
  assert(!await page.locator('.chat-progress, .message.preview').count(), 'Old generation state is gone');
  assert(!await nav.getByRole('button', { name: created.name, exact: true }).count(), 'New owner cannot see the old chat');
  assert(sends === 1, 'Changing owner never replays generation');
  return 'PASS: account change aborts pending generation, drops late results and never replays';
}
