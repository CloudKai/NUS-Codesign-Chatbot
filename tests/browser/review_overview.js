/** Basic replacement/empty brief contract on the disposable mock app at 8093. */
async page => {
  page.setDefaultTimeout(10000);
  const assert = (value, message) => { if (!value) throw new Error(message); };
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('http://127.0.0.1:8093/');
  const nav = page.getByRole('complementary', { name: 'Your notebooks' });
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
  const brief = page.getByRole('region', { name: 'Your project so far', exact: true });
  await brief.waitFor();
  assert(await brief.getByText('Not yet established', { exact: true }).count() === 5, 'An empty chat has no established project facts');
  assert(!/Your recent prompts|Saved coach recap|Stage \d of 5/i.test(await brief.innerText()), 'Old recap/progress UI must be absent');
  return 'PASS: compact project brief replaces the recent-prompt/recap UI without inventing empty-chat details';
}
