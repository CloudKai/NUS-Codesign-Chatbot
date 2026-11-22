/** Working/latest control through real mock streaming, held at the public HTTP boundary. */
async page => {
  page.setDefaultTimeout(10000);
  const assert = (value, message) => { if (!value) throw new Error(message); };
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('http://127.0.0.1:8094/');
  const guest = page.getByRole('button', { name: 'Continue as Guest' });
  const nav = page.getByRole('complementary', { name: 'Your notebooks' });
  await guest.or(nav).waitFor(); if (await guest.isVisible()) await guest.click();
  await nav.waitFor();
  await page.evaluate(async () => {
    const response = await fetch('/api/v1/reader/preferences', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reduce_motion: false }) });
    if (!response.ok) throw new Error('Reset disposable motion preference failed');
  });
  const fixture = await page.evaluate(async () => {
    const post = async (path, body) => {
      const response = await fetch('/api/v1/reader' + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (!response.ok) throw new Error(`${path}: ${response.status}`);
      return response;
    };
    const { notebook } = await (await post('/threads', { kind: 'chat' })).json();
    await post(`/threads/${notebook.id}/settings`, { name: `Latest control ${notebook.id}` });
    const long = Array.from({ length: 60 }, (_, index) => `Design note ${index}: residents need safe and accessible crossings.`).join('\n');
    for (let index = 0; index < 3; index++) {
      const stream = await (await post(`/threads/${notebook.id}/lecture/stream`, { student_message: index ? `Explain analogy, example ${index}` : long, idempotency_key: `${notebook.id}-${index}` })).text();
      if (!stream.split('\n').filter(Boolean).some(line => JSON.parse(line).event === 'done')) throw new Error(stream);
    }
    const messages = await (await fetch(`/api/v1/reader/threads/${notebook.id}/messages/page`)).json();
    await post(`/threads/${notebook.id}/messages/${messages.messages[0].id}/star`, { starred: true });
    const bookmarks = await (await fetch(`/api/v1/reader/threads/${notebook.id}/bookmarks`)).json();
    if (bookmarks.messages[0].preview.length !== 320 || messages.messages[0].content !== long) throw new Error('Existing 320-character preview must preserve the full original');
    const project = await (await fetch(`/api/v1/reader/threads/${notebook.id}/project`)).json();
    return { id: notebook.id, message: messages.messages[0].id, group: project.stages.find(stage => stage.id === bookmarks.messages[0].stage_id)?.label ?? 'No stage' };
  });
  await page.reload();
  await nav.getByRole('button', { name: `Latest control ${fixture.id}`, exact: true }).click();
  await page.getByRole('heading', { name: `Latest control ${fixture.id}`, exact: true }).waitFor();
  let release; const gate = new Promise(resolve => { release = resolve; });
  await page.route('**/lecture/stream', async route => { await gate; await route.continue(); });
  try {
    await page.getByRole('textbox', { name: 'Your lecture question', exact: true }).fill('Explain the next part.');
    await page.getByRole('button', { name: 'Send message', exact: true }).click();
    const working = page.getByRole('button', { name: 'Jump to latest message, coach is working', exact: true });
    assert(await working.count() === 1, 'Show a circular working control above the textbox while the reply runs');
    const size = await working.boundingBox();
    assert(size.width === size.height && size.width >= 44, 'Working control must be circular with a 44px target');
    const circle = await working.evaluate(el => { const style = getComputedStyle(el, '::before'); return { width: style.width, height: style.height }; });
    assert(circle.width === '32px' && circle.height === '32px', 'Use a smaller 32px visible circle inside the touch target');
    const textbox = await page.getByRole('textbox', { name: 'Your lecture question', exact: true }).boundingBox();
    assert(size.y + size.height <= textbox.y, 'Place the circle above the textbox');
    await page.locator('.transcript').evaluate(el => { el.scrollTop = 0; });
    await working.click();
    await page.waitForFunction(() => document.querySelector('.transcript').scrollTop > 0);
    assert(await page.locator('.transcript').evaluate(el => el.scrollHeight - el.scrollTop - el.clientHeight > 3), 'Scroll through intermediate chat content instead of instantly jumping');
    await page.waitForFunction(() => { const el = document.querySelector('.transcript'); return el.scrollHeight - el.scrollTop - el.clientHeight < 3; });
    release();
    await working.waitFor({ state: 'hidden' });
    const latest = page.getByRole('button', { name: 'Jump to latest message', exact: true });
    await latest.waitFor({ state: 'hidden' });
    assert(await latest.count() === 0, 'Hide the finished arrow when already at the latest message');
    await page.locator('.transcript').evaluate(el => { el.scrollTop = 0; });
    await latest.waitFor();
    await latest.focus(); await page.keyboard.press('Enter');
    await page.waitForFunction(() => { const el = document.querySelector('.transcript'); return el.scrollHeight - el.scrollTop - el.clientHeight < 3; });
    await latest.waitFor({ state: 'hidden' });
    await page.locator('.transcript').evaluate(el => { el.scrollTop = 0; });
    await latest.waitFor();
    await page.locator('.transcript').evaluate(el => { el.scrollTop = el.scrollHeight; });
    await latest.waitFor({ state: 'hidden' });
    assert(await working.count() === 0, 'Working dots must disappear after completion');
  } finally { release(); await page.unrouteAll({ behavior: 'wait' }); }
  const saved = await page.evaluate(async id => (await (await fetch(`/api/v1/reader/threads/${id}/messages/page`)).json()).messages, fixture.id);
  assert(saved.length === 8 && saved[saved.length - 1].role === 'assistant', 'The circle must not interrupt saving the coach reply');
  await page.getByRole('button', { name: /Review/ }).filter({ hasText: 'Review' }).first().click();
  await page.getByRole('tab', { name: 'My work', exact: true }).click();
  const work = page.getByRole('tabpanel', { name: 'My work', exact: true });
  const stage = work.getByRole('region', { name: fixture.group, exact: true });
  const group = stage.getByRole('button', { name: fixture.group, exact: true });
  if (await group.getAttribute('aria-expanded') === 'false') await group.click();
  const preview = stage.locator('.bookmark-preview').first();
  await preview.waitFor();
  const dimensions = await preview.evaluate(el => ({ height: el.getBoundingClientRect().height, line: parseFloat(getComputedStyle(el).lineHeight), text: el.textContent.length }));
  assert(dimensions.text <= 320, 'Rendered bookmark preview must remain character-bounded');
  assert(dimensions.height <= dimensions.line * 6 + 1, `Bound newline-heavy previews to six visible lines: ${JSON.stringify(dimensions)}`);
  await stage.getByRole('button', { name: 'Jump to message', exact: true }).click();
  await page.getByRole('dialog', { name: 'Review', exact: true }).waitFor({ state: 'hidden' });
  const original = page.locator(`[data-message-id="${fixture.message}"]`);
  await original.waitFor();
  assert((await original.innerText()).length > 320, 'Jump must retain the complete saved text');
  return 'PASS: circle above composer, working dots and scroll-aware arrow, 44px target, keyboard and live/latest scrolling; saved preview remains 320 characters';
}
