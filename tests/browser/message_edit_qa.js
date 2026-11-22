/** Run after message_edit.js on its disposable mock chat. */
async page => {
  page.setDefaultTimeout(10000);
  const assert = (value, message) => { if (!value) throw new Error(message); };
  const errors = []; let revisions = 0; let expectedFailure = false;
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error' && !expectedFailure) errors.push(message.text()); });
  page.on('request', request => { if (request.method() === 'POST' && request.url().endsWith('/revise/stream')) revisions++; });
  const original = page.locator('.message.student').first();
  const text = await original.locator('.message-content').innerText();
  for (const appearance of ['Light', 'Dark']) {
    await page.evaluate(async appearance => {
      const response = await fetch('/api/v1/reader/preferences', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ appearance }) });
      if (!response.ok) throw new Error('Theme update failed');
    }, appearance);
    await page.reload();
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 960 });
      const edit = original.getByRole('button', { name: 'Edit message', exact: true });
      await page.mouse.move(0, 0);
      const before = await edit.evaluate(el => ({ color: getComputedStyle(el).color, bg: getComputedStyle(el).backgroundColor }));
      await edit.hover();
      const after = await edit.evaluate(el => ({ color: getComputedStyle(el).color, bg: getComputedStyle(el).backgroundColor }));
      assert(before.color !== after.color && before.bg !== after.bg, 'Chat symbols need a clear hover colour/background change');
      await edit.click();
      const field = original.getByRole('textbox', { name: 'Revise your message', exact: true });
      const send = original.getByRole('button', { name: 'Confirm edit & ask again', exact: true });
      const cancel = original.getByRole('button', { name: 'Cancel edit', exact: true });
      assert(await field.inputValue() === text, 'Editing starts with the full saved message');
      await field.fill('   ');
      assert(await send.isDisabled(), 'Disable empty edited submissions');
      await field.fill('First line');
      const shortSize = await field.evaluate(el => ({ height: el.getBoundingClientRect().height, width: el.getBoundingClientRect().width }));
      assert(shortSize.height <= 80 && await field.evaluate(el => getComputedStyle(el).resize) === 'none', 'Keep short edits compact without manual resize controls');
      await original.scrollIntoViewIfNeeded();
      await page.screenshot({ path: `output/playwright/latest-control/edit-compact-${appearance}-${width}.png` });
      await field.press('Enter'); await field.press('End'); await field.press('x');
      assert((await field.inputValue()).includes('\n'), 'Enter remains a newline inside the editor');
      await field.fill(text);
      const { area, bounds, editor } = await original.evaluate(el => ({
        area: el.querySelector('textarea').getBoundingClientRect().toJSON(),
        bounds: el.querySelector('.edit-submit').getBoundingClientRect().toJSON(),
        editor: el.querySelector('.message-edit-box').getBoundingClientRect().toJSON(),
      }));
      assert(area.width > shortSize.width + 30, 'Widen automatically when short text is replaced by longer lines');
      assert(area.height >= 160 && area.height <= 361, 'Long edits have a generous bounded scrolling field');
      assert(bounds.y + bounds.height <= editor.y + editor.height && bounds.x + bounds.width < editor.x + editor.width, 'Keep actions inside the shared edit textbox');
      assert(bounds.y >= area.y + area.height, 'Reserve text space above the buttons so long text remains readable');
      assert(bounds.width === 44 && bounds.height === 44 && bounds.x + bounds.width <= width, 'Keep icon actions usable on phone');
      await page.mouse.move(0, 0);
      const normal = await send.evaluate(el => getComputedStyle(el).backgroundColor);
      await send.hover();
      assert(normal !== await send.evaluate(el => getComputedStyle(el).backgroundColor), 'Submit hover changes colour');
      await original.scrollIntoViewIfNeeded();
      await page.screenshot({ path: `output/playwright/latest-control/edit-${appearance}-${width}.png` });
      await cancel.focus(); await page.keyboard.press('Escape');
      await field.waitFor({ state: 'hidden' });
      await page.waitForFunction(() => document.activeElement?.getAttribute('aria-label') === 'Edit message');
      assert(await original.locator('.message-content').innerText() === text, 'Escape preserves the original');
      assert(await page.getByRole('textbox', { name: 'Your lecture question', exact: true }).inputValue() === 'Keep my next question in the composer.', 'Keep the composer draft through cancel/reload/theme/width changes');
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'No horizontal overflow');
    }
  }
  assert(revisions === 0, 'Opening, typing, hovering and cancelling never submit edits');
  await original.getByRole('button', { name: 'Edit message', exact: true }).click();
  const field = original.getByRole('textbox', { name: 'Revise your message', exact: true });
  const revised = 'Residents need safer crossings near the market. We will explore longer crossing times.';
  await field.fill(revised);
  const response = page.waitForResponse(response => response.url().endsWith('/revise/stream') && response.request().method() === 'POST');
  await original.getByRole('button', { name: 'Confirm edit & ask again', exact: true }).click();
  assert((await response).ok(), 'The up arrow must use the existing save-and-ask-again operation');
  await page.waitForFunction(revised => document.querySelector('.message.student .message-content')?.textContent === revised, revised);
  await page.getByRole('button', { name: 'Stop generating', exact: true }).waitFor({ state: 'hidden' });
  assert(revisions === 1, 'Submit exactly one edit request');
  assert(await page.locator('.message').count() === 2, 'Revised message and coach reply replace later active replies');
  await page.reload();
  await page.waitForFunction(revised => document.querySelector('.message.student .message-content')?.textContent === revised, revised);
  assert(await page.getByRole('textbox', { name: 'Your lecture question', exact: true }).inputValue() === 'Keep my next question in the composer.', 'Successful edit preserves the separate draft after reload');
  await original.getByRole('button', { name: 'Edit message', exact: true }).click();
  await original.getByRole('textbox', { name: 'Revise your message', exact: true }).fill('Keep this attempted edit if the connection fails.');
  expectedFailure = true;
  await page.route('**/messages/*/revise/stream', route => route.fulfill({ status: 500, contentType: 'application/json', body: '{}' }));
  try {
    await original.getByRole('button', { name: 'Confirm edit & ask again', exact: true }).click();
    await page.getByRole('button', { name: 'Check saved answer', exact: true }).waitFor();
    await page.getByText('Keep this attempted edit if the connection fails.', { exact: false }).first().waitFor();
    await page.reload();
    await page.getByRole('button', { name: 'Check saved answer', exact: true }).waitFor();
    assert(revisions === 2, 'Failure/reload must reconcile through reads without replaying the edit');
    await page.getByRole('button', { name: 'Discard and edit', exact: true }).click();
    assert(await page.getByRole('textbox', { name: 'Your lecture question', exact: true }).inputValue() === 'Keep my next question in the composer.\n\nKeep this attempted edit if the connection fails.', 'Recovery preserves both the separate draft and attempted edit for correction');
  } finally { await page.unrouteAll({ behavior: 'wait' }); expectedFailure = false; }
  assert(errors.length === 0, `Unexpected browser errors: ${errors.join('; ')}`);
  return 'PASS: Light/Dark desktop/390 in-place editing, large bounded field, icon hover/keyboard, exact save/reload, draft preservation and failed-edit recovery without replay';
}
