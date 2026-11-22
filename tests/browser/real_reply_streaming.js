/** Render real mock partial replies through the delayed NDJSON fixture on 8096. */
async page => {
  page.setDefaultTimeout(10000);
  const assert = (value, message) => { if (!value) throw new Error(message); };
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('http://127.0.0.1:8096/');
  const guest = page.getByRole('button', { name: 'Continue as Guest' });
  const nav = page.getByRole('complementary', { name: 'Your notebooks' });
  await guest.or(nav).waitFor();
  if (await guest.isVisible()) await guest.click();
  await nav.waitFor();
  const name = await page.evaluate(async () => {
    const response = await fetch('/api/v1/reader/threads', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind: 'chat' }) });
    if (!response.ok) throw Error('Create failed');
    const { notebook } = await response.json();
    const name = 'Streaming ' + notebook.id;
    await fetch(`/api/v1/reader/threads/${notebook.id}/settings`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) });
    return name;
  });
  await page.reload();
  await nav.getByRole('button', { name, exact: true }).click();
  await page.getByRole('radio', { name: 'Design coaching', exact: true }).check();
  const draft = page.getByRole('textbox', { name: 'Your project contribution', exact: true });
  const preview = page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'Coach · unsaved preview', exact: true }) });
  async function observeGrowingReply() {
    await preview.waitFor();
    const first = await preview.locator('.message-content').innerText();
    assert(first.length > 0, 'Show actual partial reply text');
    await page.waitForFunction(length => (document.querySelector('.message.preview .message-content')?.textContent?.length ?? 0) > length, first.length);
    await page.getByRole('button', { name: 'Stop generating', exact: true }).waitFor({ state: 'hidden' });
    await preview.waitFor({ state: 'hidden' });
    await page.getByRole('button', { name: 'Jump to latest message, coach is working', exact: true }).waitFor({ state: 'hidden' });
  }
  await draft.fill('Older residents need safer crossings near the market.');
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  await observeGrowingReply();
  await draft.fill('Keep my separate next question.');
  const original = page.locator('.message.student').first();
  await original.getByRole('button', { name: 'Edit message', exact: true }).click();
  await original.getByRole('textbox', { name: 'Revise your message', exact: true }).fill('Older residents need longer crossing times near the market.');
  await original.getByRole('button', { name: 'Confirm edit & ask again', exact: true }).click();
  await observeGrowingReply();
  assert(await draft.inputValue() === 'Keep my separate next question.', 'Streaming revisions preserve the separate draft');
  assert(await page.locator('.message.student').count() === 1 && await page.locator('.message.coach').count() === 1, 'Only the final revised exchange is active');
  await page.reload();
  await page.getByText('Older residents need longer crossing times near the market.', { exact: true }).waitFor();
  return 'PASS: visible incremental normal and edited replies, validated save/reload and separate draft preservation';
}
