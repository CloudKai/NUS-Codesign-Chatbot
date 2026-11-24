/** Hold owner A's bootstrap, switch cookies, and reject the old aggregate before render. */
async page => {
  const assert = (condition, message) => { if (!condition) throw Error(message); };
  const nav = page.getByRole('complementary', { name: 'Your notebooks' });
  await nav.waitFor();
  const name = await page.evaluate(async () => {
    const name = `Private bootstrap fixture ${crypto.randomUUID()}`;
    const result = await fetch('/api/v1/reader/threads', { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind: 'chat' }) });
    if (!result.ok) throw Error('Synthetic chat creation failed');
    const { notebook } = await result.json();
    const saved = await fetch(`/api/v1/reader/threads/${notebook.id}/settings`, { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) });
    if (!saved.ok) throw Error('Synthetic fixture rename failed');
    return name;
  });
  let release;
  let ready;
  const held = new Promise(resolve => { release = resolve; });
  const intercepted = new Promise(resolve => { ready = resolve; });
  let calls = 0;
  await page.route('**/api/v1/reader/bootstrap', async route => {
    calls++;
    if (calls !== 1) { await route.continue(); return; }
    const response = await route.fetch();
    assert((await response.text()).includes(name), 'Held bootstrap contains the original owner fixture');
    ready();
    await held;
    await route.fulfill({ response });
  });
  await page.goto(new URL(page.url()).origin, { waitUntil: 'domcontentloaded' });
  await intercepted;
  assert(!await page.getByText(name, { exact: true }).count(), 'Private data stays hidden before owner verification');
  await page.context().clearCookies();
  const started = await page.evaluate(async () => (await fetch('/api/v1/auth/guest/start', { method: 'POST' })).status);
  assert(started === 200, 'New guest session created');
  release();
  const guest = page.getByRole('button', { name: 'Continue as Guest', exact: true });
  await guest.waitFor();
  assert(!await page.getByText(name, { exact: true }).count(), 'Late bootstrap fails closed after owner changes');
  await page.unroute('**/api/v1/reader/bootstrap');
  await guest.click();
  await nav.waitFor();
  assert(!await nav.getByRole('button', { name, exact: true }).count(), 'New owner never receives old sidebar state');
  return 'PASS: pending bootstrap cannot expose another owner after cookie change';
}
