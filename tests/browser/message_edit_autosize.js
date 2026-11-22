/** Run after chat_latest_control.js on a disposable mock chat. */
async page => {
  page.setDefaultTimeout(10000);
  const assert = (value, message) => { if (!value) throw new Error(message); };
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  for (const appearance of ['Light', 'Dark']) {
    await page.evaluate(async appearance => {
      const response = await fetch('/api/v1/reader/preferences', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ appearance }) });
      if (!response.ok) throw new Error('Theme update failed');
    }, appearance);
    await page.reload();
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 960 });
      const message = page.locator('.message.student').nth(1);
      const saved = await message.locator('.message-content').innerText();
      await message.getByRole('button', { name: 'Edit message', exact: true }).click();
      const field = message.getByRole('textbox', { name: 'Revise your message', exact: true });
      assert(await field.inputValue() === saved, 'Open the exact saved short text');
      const measure = () => message.evaluate(el => {
        const field = el.querySelector('textarea').getBoundingClientRect();
        const box = el.querySelector('.message-edit-box').getBoundingClientRect();
        const buttons = [...el.querySelectorAll('.message-edit-actions button')].map(button => button.getBoundingClientRect());
        return { height: field.height, total: box.height, inside: buttons.every(button => button.y >= field.bottom && button.right < box.right && button.bottom < box.bottom) };
      });
      const short = await measure();
      assert(short.height <= 80 && short.total < 160, 'Short saved messages must open in a compact textbox');
      assert(short.inside, 'Keep both icons inside at the bottom right without covering text');
      await message.scrollIntoViewIfNeeded();
      await page.screenshot({ path: `output/playwright/latest-control/edit-short-${appearance}-${width}.png` });
      await field.fill(Array.from({ length: 30 }, (_, index) => `Line ${index}: keep the original design reasoning readable.`).join('\n'));
      const long = await measure();
      assert(long.height >= 300 && long.height <= 361 && long.inside, 'Grow long text to a bounded reading area while retaining inset controls');
      await message.scrollIntoViewIfNeeded();
      await page.screenshot({ path: `output/playwright/latest-control/edit-grown-${appearance}-${width}.png` });
      await field.fill('Short again.');
      const shrunk = await measure();
      assert(shrunk.height <= 80 && shrunk.inside, 'Shrink automatically when text becomes short again');
      await field.press('Escape');
      await field.waitFor({ state: 'hidden' });
      assert(await message.locator('.message-content').innerText() === saved, 'Cancel preserves the saved message');
    }
  }
  assert(errors.length === 0, `Browser errors: ${errors.join('; ')}`);
  return 'PASS: short opening, automatic growth/shrink, bounded long text, inset icons, Escape and clean console at Light/Dark desktop/390';
}
