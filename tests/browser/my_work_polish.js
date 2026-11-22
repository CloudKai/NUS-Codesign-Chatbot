/** Saved stars must be visually unmistakable in Chat and grouped clearly in My work. */
async page => {
  page.setDefaultTimeout(10000);
  const assert = (value, message) => { if (!value) throw new Error(message); };
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('http://127.0.0.1:8094/');
  const guest = page.getByRole('button', { name: 'Continue as Guest' });
  const nav = page.getByRole('complementary', { name: 'Your notebooks' });
  await guest.or(nav).waitFor(); if (await guest.isVisible()) await guest.click();
  await nav.waitFor();
  const fixture = await page.evaluate(async () => {
    const post = async (path, body) => {
      const response = await fetch('/api/v1/reader' + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (!response.ok) throw new Error(`${path}: ${response.status}`);
      return response;
    };
    const { notebook } = await (await post('/threads', { kind: 'chat' })).json();
    await post(`/threads/${notebook.id}/settings`, { name: `Star design ${notebook.id}` });
    const events = await (await post(`/threads/${notebook.id}/project/stream`, {
      student_message: 'We are exploring safer crossings for older residents near campus.', idempotency_key: `${notebook.id}-first`,
    })).text();
    if (!events.split('\n').filter(Boolean).some(line => JSON.parse(line).event === 'done')) throw new Error(events);
    return notebook.id;
  });
  await page.reload();
  await nav.getByRole('button', { name: `Star design ${fixture}`, exact: true }).click();
  await page.getByRole('heading', { name: `Star design ${fixture}`, exact: true }).waitFor();
  const message = page.locator('article.message').first();
  await message.getByRole('button', { name: 'Star message', exact: true }).click();
  const star = message.getByRole('button', { name: 'Unstar message', exact: true });
  await star.waitFor();
  assert(await star.getAttribute('aria-pressed') === 'true', 'Saved star must expose pressed state');
  const appearance = await star.evaluate(el => ({ color: getComputedStyle(el).color, fill: getComputedStyle(el.querySelector('svg')).fill, ink: getComputedStyle(el.closest('article')).color }));
  const [red, green, blue] = appearance.color.match(/[\d.]+/g).map(Number);
  assert(red > green && green > blue, 'Saved star must use a recognisable gold/yellow hue');
  assert(appearance.fill === appearance.color && appearance.color !== appearance.ink, `Saved star must be filled gold rather than an indistinct outline: ${JSON.stringify(appearance)}`);
  await page.locator('article.message').nth(1).getByRole('button', { name: 'Star message', exact: true }).click();
  await page.locator('article.message').nth(1).getByRole('button', { name: 'Unstar message', exact: true }).waitFor();
  await page.getByRole('button', { name: /Review/ }).filter({ hasText: 'Review' }).first().click();
  await page.getByRole('tab', { name: 'My work', exact: true }).click();
  const work = page.getByRole('tabpanel', { name: 'My work', exact: true });
  const group = work.getByRole('region', { name: 'Problem identification', exact: true });
  assert(await group.count() === 1, 'Each stage must visibly and accessibly own its saved messages');
  assert(await group.getByRole('listitem').count() === 2, 'Keep both starred authors under the saved stage');
  const heading = group.getByRole('button', { name: 'Problem identification', exact: true });
  const preview = group.getByText('We are exploring safer crossings for older residents near campus.', { exact: true });
  assert(await heading.evaluate(el => getComputedStyle(el).color) !== await preview.evaluate(el => getComputedStyle(el).color), 'Use the stage heading colour to separate hierarchy from message content');
  assert((await preview.boundingBox()).x >= (await heading.boundingBox()).x + 12, 'Inset saved entries below their stage heading');
  for (const button of await group.getByRole('button', { name: 'Remove star', exact: true }).all()) {
    const selected = await button.evaluate(el => ({ color: getComputedStyle(el).color, fill: getComputedStyle(el.querySelector('svg')).fill }));
    assert(selected.fill === selected.color, 'My work saved-star actions must also be filled');
  }
  const errors = [];
  const pageError = error => errors.push(error.message);
  const consoleError = message => { if (message.type() === 'error') errors.push(message.text()); };
  page.on('pageerror', pageError); page.on('console', consoleError);
  const checkGold = async button => button.evaluate(el => {
    const color = getComputedStyle(el).color;
    const [red, green, blue] = color.match(/[\d.]+/g).map(Number);
    return el.getAttribute('aria-pressed') !== 'false' && red > green && green > blue && getComputedStyle(el.querySelector('svg')).fill === color;
  });
  for (const theme of ['Light', 'Dark']) {
    await page.evaluate(async appearance => {
      const response = await fetch('/api/v1/reader/preferences', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ appearance }) });
      if (!response.ok) throw new Error('Appearance did not save');
    }, theme);
    for (const width of [1440, 900, 390]) {
      await page.setViewportSize({ width, height: 960 });
      await page.reload(); await work.waitFor();
      await page.waitForFunction(theme => document.documentElement.dataset.appearance === theme, theme);
      const panel = page.getByRole('dialog', { name: 'Review', exact: true });
      assert(await group.getByRole('listitem').count() === 2, 'Saved stars must survive reload');
      assert(await checkGold(group.getByRole('button', { name: 'Remove star' }).first()), 'My work star lost its filled gold appearance');
      assert(await checkGold(page.locator('article.message').first().locator('.message-star')), 'Chat star lost its saved appearance after reload');
      assert(await panel.evaluate(el => el.scrollWidth <= el.clientWidth), `${theme} ${width}: My work overflow`);
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${theme} ${width}: page overflow`);
      for (const button of await group.getByRole('button').all()) assert((await button.boundingBox()).height >= 44, 'Group/action controls need 44px targets');
      await group.getByRole('button', { name: 'Problem identification', exact: true }).focus();
      await page.keyboard.press('Space');
      assert(!await preview.isVisible(), 'Stage did not collapse with keyboard');
      await page.keyboard.press('Enter'); await preview.waitFor();
      await panel.evaluate(el => el.scrollTo({ top: 0 }));
      await page.screenshot({ path: `output/playwright/mywork-polish/mywork-${theme}-${width}.png` });
      await panel.getByRole('button', { name: 'Close Review', exact: true }).click();
      const chatStar = page.locator('article.message').first().getByRole('button', { name: 'Unstar message', exact: true });
      await chatStar.focus(); await page.keyboard.press('Enter');
      const unselected = page.locator('article.message').first().getByRole('button', { name: 'Star message', exact: true });
      await unselected.waitFor();
      assert(await unselected.evaluate(el => getComputedStyle(el.querySelector('svg')).fill) === 'none', 'Removing a star must restore the outline');
      await unselected.press('Enter'); await chatStar.waitFor();
      assert(await checkGold(chatStar), 'Keyboard starring must immediately restore gold');
      await page.screenshot({ path: `output/playwright/mywork-polish/chat-${theme}-${width}.png` });
      await page.getByRole('button', { name: /Review/ }).filter({ hasText: 'Review' }).first().click();
      await work.waitFor();
    }
  }
  page.off('pageerror', pageError); page.off('console', consoleError);
  assert(errors.length === 0, `Unexpected browser errors: ${errors.join('; ')}`);
  return 'PASS: filled gold stars in Chat/My work, reload and keyboard unstar/re-star, clear stage ownership, contrast hierarchy, 44px controls and Light/Dark 1440/900/390 layout';
}
