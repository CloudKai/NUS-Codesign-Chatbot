import { chromium } from '@playwright/test';
const browser = await chromium.launch();
const page = await browser.newPage();
await page.setContent(`<button id="outside">Outside</button>
<dialog id="d"><input id="a"><input id="b"><button id="c">Close</button></dialog>
<script>document.getElementById('d').showModal();</script>`);
await page.waitForTimeout(100);
for (let i = 0; i < 5; i++) {
  await page.keyboard.press('Tab');
  console.log(i, await page.evaluate(() => document.activeElement?.id));
}
await browser.close();
