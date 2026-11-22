/** Verify owner/chat isolation, responsive modes, intentional closes and visual/accessibility states. */
async page => {
  page.setDefaultTimeout(10000);
  const assert = (value, message) => { if (!value) throw new Error(message); };
  const errors = [];
  let changingOwner = false;
  const onError = error => errors.push(error.message);
  const onConsole = message => { if (message.type() === 'error' && !(changingOwner && message.text().includes('401') && /\/api\/v1\/(reader\/session|auth\/me)$/.test(message.location().url))) errors.push(message.text()); };
  page.on('pageerror', onError); page.on('console', onConsole);
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('http://127.0.0.1:8093/');
  const review = page.getByRole('dialog', { name: 'Review', exact: true });
  const open = page.getByRole('button', { name: /Review/ }).filter({ hasText: 'Review' }).first();
  await open.waitFor();
  const original = await page.getByRole('region', { name: 'Saved conversation' }).getByRole('heading', { level: 2 }).first().innerText();
  if (!await review.isVisible()) await open.click();
  await page.getByRole('tab', { name: 'Summary', exact: true }).click();
  const writes = [];
  const onRequest = request => { if (request.method() === 'POST' && !request.url().endsWith('/preferences') && !request.url().endsWith('/project/brief')) writes.push(request.url()); };
  page.on('request', onRequest);
  for (const appearance of ['Light', 'Dark']) {
    await page.evaluate(async appearance => {
      const response = await fetch('/api/v1/reader/preferences', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ appearance }) });
      if (!response.ok) throw new Error('Could not set appearance');
    }, appearance);
    await page.reload();
    await review.waitFor();
    await page.waitForFunction(appearance => document.documentElement.dataset.appearance === appearance, appearance);
    for (const width of [1440, 900, 390]) {
      await page.setViewportSize({ width, height: 960 });
      await page.getByRole('tab', { name: 'Summary', exact: true }).waitFor();
      assert(await review.isVisible(), 'Resizing must preserve Review');
      assert(await page.getByRole('tab', { name: 'Summary', exact: true }).getAttribute('aria-selected') === 'true', 'Resizing changed the selected tab');
      assert(await review.evaluate(element => element.scrollWidth <= element.clientWidth), `${appearance} ${width}: Review overflow`);
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${appearance} ${width}: page overflow`);
      const summary = page.getByRole('tabpanel', { name: 'Summary', exact: true });
      const stage = summary.getByRole('button', { name: 'Problem identification', exact: true });
      await stage.scrollIntoViewIfNeeded();
      const box = await stage.boundingBox();
      assert(box.height >= 44, 'Stage disclosure needs a 44px touch target');
      const wasOpen = await stage.getAttribute('aria-expanded') === 'true';
      await stage.focus(); await page.keyboard.press('Space');
      assert(await stage.getAttribute('aria-expanded') === String(!wasOpen), 'Keyboard did not toggle stage');
      await page.keyboard.press('Enter');
      if (!wasOpen) await stage.click();
      const good = summary.getByRole('region', { name: 'Problem identification', exact: true }).getByRole('button', { name: 'Going well', exact: true });
      assert((await good.boundingBox()).height >= 44, 'Feedback disclosure needs a 44px touch target');
      await good.focus(); await page.keyboard.press('Enter');
      await page.getByRole('tab', { name: 'My work', exact: true }).click();
      await page.getByRole('tab', { name: 'Summary', exact: true }).click();
      assert(await good.getAttribute('aria-expanded') === 'false', 'Review tabs discarded disclosure state');
      await good.click();
      await summary.getByRole('heading', { name: 'Your project so far', exact: true }).scrollIntoViewIfNeeded();
      await page.screenshot({ path: `output/playwright/review/summary-${appearance}-${width}.png` });
    }
  }
  page.off('request', onRequest);
  assert(writes.length === 0, `Review caused a write: ${writes.join(', ')}`);
  // Escape and the drawer backdrop remain explicit close actions and persist across reload.
  await page.keyboard.press('Escape');
  await page.reload(); await open.waitFor();
  assert(!await review.isVisible(), 'Escape close was forgotten');
  await page.setViewportSize({ width: 900, height: 960 });
  await open.click();
  await review.waitFor();
  await page.mouse.click(10, 400);
  assert(!await review.isVisible(), 'Backdrop close was ignored');
  await page.reload(); await open.waitFor();
  assert(!await review.isVisible(), 'Backdrop close was forgotten');
  await page.setViewportSize({ width: 1440, height: 960 });
  await open.click();
  await page.getByRole('tab', { name: 'Summary', exact: true }).click();
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
  assert(!await review.isVisible(), 'A new chat inherited another chat’s open Review');
  await nav.getByRole('button', { name: original, exact: true }).click();
  await review.waitFor();
  assert(await page.getByRole('tab', { name: 'Summary', exact: true }).getAttribute('aria-selected') === 'true', 'Returning chat lost its Review view');
  const cookies = await page.context().cookies();
  changingOwner = true;
  try {
    await page.context().clearCookies();
    await page.evaluate(async () => {
      const response = await fetch('/api/v1/auth/guest/start', { method: 'POST' });
      if (!response.ok) throw new Error('Second disposable guest unavailable');
    });
    await page.reload();
    await nav.waitFor();
    assert(!await review.isVisible(), 'Another owner inherited Review');
    assert(await page.getByRole('heading', { name: original, exact: true }).count() === 0, 'Previous owner’s content leaked');
    assert(await nav.getByRole('button', { name: original, exact: true }).count() === 0, 'Previous owner’s chat leaked');
  } finally {
    await page.context().clearCookies();
    await page.context().addCookies(cookies);
    await page.reload();
  }
  await review.waitFor();
  page.off('pageerror', onError); page.off('console', onConsole);
  assert(errors.length === 0, `Browser errors: ${errors.join('; ')}`);
  return 'PASS: Light/Dark 1440/900/390, keyboard/touch/overflow, no Review writes, explicit closes, chat/owner isolation and clean console';
}
