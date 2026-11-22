/** Rendered bookmark regression; use a disposable mock backend on port 8094. */
async page => {
  page.setDefaultTimeout(10000);
  await page.unrouteAll({ behavior: 'wait' });
  const assert = (value, text) => { if (!value) throw new Error(text); };
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('http://127.0.0.1:8094/');
  const guest = page.getByRole('button', { name: 'Continue as Guest' });
  const nav = page.getByRole('complementary', { name: 'Your notebooks' });
  await guest.or(nav).waitFor();
  if (await guest.isVisible()) await guest.click();
  await nav.waitFor();
  const errors = [];
  let expectedFailure = false;
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error' && !expectedFailure) errors.push(message.text()); });
  const fixture = await page.evaluate(async () => {
    const post = async (url, body) => {
      const response = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (!response.ok) throw new Error(`${url}: ${response.status}`);
      return response;
    };
    const { notebook } = await (await post('/api/v1/reader/threads', { kind: 'chat' })).json();
    const path = `/api/v1/reader/threads/${notebook.id}`;
    await post(`${path}/settings`, { name: `Bookmarks ${notebook.id}` });
    const stream = await (await post(`${path}/project/stream`, { student_message: 'Residents need more time to cross safely.', idempotency_key: `${notebook.id}-first` })).text();
    if (!stream.split('\n').filter(Boolean).map(JSON.parse).some(event => event.event === 'done')) throw new Error(stream);
    return { path, notebook, messages: (await (await fetch(`${path}/messages/page`)).json()).messages };
  });
  await page.reload();
  await nav.getByRole('button', { name: `Bookmarks ${fixture.notebook.id}`, exact: true }).click();
  await page.getByRole('heading', { name: `Bookmarks ${fixture.notebook.id}`, exact: true }).waitFor();
  const messages = page.locator('article.message');
  await messages.first().getByRole('button', { name: 'Star message', exact: true }).waitFor();
  await messages.first().getByRole('button', { name: 'Star message', exact: true }).click();
  await messages.first().getByRole('button', { name: 'Unstar message', exact: true }).waitFor();
  assert(await messages.first().getByRole('button', { name: 'Unstar message' }).getAttribute('aria-pressed') === 'true', 'Saved star must be pressed');
  await messages.nth(1).getByRole('button', { name: 'Star message', exact: true }).click();
  await messages.nth(1).getByRole('button', { name: 'Unstar message', exact: true }).waitFor();
  await page.getByRole('button', { name: /Review/ }).filter({ hasText: 'Review' }).first().click();
  await page.getByRole('tab', { name: 'My work', exact: true }).click();
  const work = page.getByRole('tabpanel', { name: 'My work', exact: true });
  await work.getByText('Star messages in Chat to keep useful ideas and coach replies here.', { exact: true }).waitFor();
  assert(!(await work.innerText()).includes('**Problem identification**'), 'Bookmark previews must read without Markdown markers');
  assert(await work.getByRole('button', { name: 'Jump to message', exact: true }).count() === 2, 'My work must show only the two selected messages');
  assert(!(await work.innerText()).includes('What you shared'), 'Automatic transcript must be replaced');
  await work.getByRole('button', { name: 'Remove star', exact: true }).first().click();
  await page.waitForFunction(() => document.querySelectorAll('#review-panel-my-work .bookmark-entry').length === 1);
  await page.getByRole('button', { name: 'Close Review', exact: true }).click();
  await messages.first().getByRole('button', { name: 'Star message', exact: true }).waitFor();
  // A refused save must be visible inside My work and keep the saved bookmark.
  await page.getByRole('button', { name: /Review/ }).filter({ hasText: 'Review' }).first().click();
  await page.getByRole('tab', { name: 'My work', exact: true }).click();
  expectedFailure = true;
  await page.route('**/messages/*/star', route => route.fulfill({ status: 503, body: '{}' }));
  await work.getByRole('button', { name: 'Remove star', exact: true }).click();
  await work.getByRole('alert').filter({ hasText: 'Star was not saved. Try again.' }).waitFor();
  assert(await work.getByRole('button', { name: 'Jump to message' }).count() === 1, 'Failed remove must keep its bookmark');
  await page.unroute('**/messages/*/star');
  expectedFailure = false;
  await page.getByRole('button', { name: 'Close Review', exact: true }).click();
  // Force the original starred coach reply beyond the newest 20-message page.
  await page.evaluate(async ({ path, notebook }) => {
    for (let index = 0; index < 11; index++) {
      const response = await fetch(`${path}/lecture/stream`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ student_message: `Explain analogy, example ${index}`, idempotency_key: `${notebook.id}-older-${index}` }) });
      const stream = await response.text();
      if (!stream.split('\n').filter(Boolean).map(JSON.parse).some(event => event.event === 'done')) throw new Error(stream);
    }
  }, fixture);
  await page.reload();
  await page.getByRole('heading', { name: `Bookmarks ${fixture.notebook.id}`, exact: true }).waitFor();
  assert(await page.locator(`[data-message-id="${fixture.messages[1].id}"]`).count() === 0, 'Target must begin outside the loaded page');
  await page.getByRole('button', { name: /Review/ }).filter({ hasText: 'Review' }).first().click();
  await page.getByRole('tab', { name: 'My work', exact: true }).click();
  await work.getByRole('button', { name: 'Jump to message', exact: true }).click();
  const target = page.locator(`[data-message-id="${fixture.messages[1].id}"]`);
  await target.waitFor();
  assert(await target.getAttribute('data-highlighted') === 'true', 'Jump must highlight the exact original');
  assert(await target.evaluate(element => document.activeElement === element), 'Jump must focus the original for keyboard readers');
  const box = await target.boundingBox();
  const transcriptBox = await page.locator('.transcript').boundingBox();
  assert(box.y >= transcriptBox.y && box.y < transcriptBox.y + transcriptBox.height, 'Jump target must be inside the transcript viewport');
  await page.screenshot({ path: 'output/playwright/stars-31/desktop-highlight.png' });
  const savedStar = target.getByRole('button', { name: 'Unstar message', exact: true });
  await savedStar.focus();
  await page.keyboard.press('Enter');
  await target.getByRole('button', { name: 'Star message', exact: true }).waitFor();
  await target.getByRole('button', { name: 'Star message', exact: true }).press('Enter');
  await target.getByRole('button', { name: 'Unstar message', exact: true }).waitFor();
  await messages.last().getByRole('button', { name: 'Star message', exact: true }).click();
  await messages.last().getByRole('button', { name: 'Unstar message', exact: true }).waitFor();
  for (const appearance of ['Light', 'Dark']) {
    await page.evaluate(async appearance => {
      const response = await fetch('/api/v1/reader/preferences', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ appearance }) });
      if (!response.ok) throw new Error('Could not set appearance');
    }, appearance);
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 960 });
      await page.reload();
      await page.getByRole('heading', { name: `Bookmarks ${fixture.notebook.id}`, exact: true }).waitFor();
      await page.getByRole('button', { name: /Review/ }).filter({ hasText: 'Review' }).first().click();
      const progression = page.getByRole('tab', { name: 'Progression', exact: true });
      await progression.focus();
      await page.keyboard.press('End');
      await work.waitFor();
      assert(await page.getByRole('tab', { name: 'My work' }).getAttribute('aria-selected') === 'true', 'Keyboard End must open My work');
      assert((await work.locator('.bookmark-heading span').allTextContents()).slice(0, 5).join('|') === 'Problem identification|Concept generation|Design specification|Ethics & Critical Thinking|Reflection', 'Canonical bookmark group order');
      assert(await work.locator('.bookmark-mode').count() === 1 && await work.locator('.bookmark-mode').innerText() === 'Lecture Help', 'Only the lecture reply gets a mode tag');
      assert(await work.locator('.bookmark-entry').count() === 2, 'Only two saved stars survive reload');
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth || [...document.querySelectorAll('.project-panel, .bookmark-entry')].some(element => element.scrollWidth > element.clientWidth + 1));
      assert(!overflow, `${appearance} ${width} horizontal overflow`);
      for (const button of await work.getByRole('button', { name: /Jump to message|Remove star/ }).all()) {
        const size = await button.boundingBox();
        assert(width > 767 || size.height >= 44 && size.width >= 44, 'Phone bookmark actions need 44px targets');
      }
      await page.screenshot({ path: `output/playwright/stars-31/my-work-${appearance}-${width}.png` });
      const jump = work.getByRole('button', { name: 'Jump to message', exact: true }).first();
      await jump.focus();
      await page.keyboard.press('Enter');
      await target.waitFor();
      await page.waitForFunction(id => document.activeElement?.getAttribute('data-message-id') === id, fixture.messages[1].id);
      assert(await target.getAttribute('data-highlighted') === 'true', 'Keyboard jump highlights target');
      await page.screenshot({ path: `output/playwright/stars-31/jump-${appearance}-${width}.png` });
    }
  }
  assert(errors.length === 0, `Browser errors: ${errors.join('; ')}`);
  return fixture;
}
