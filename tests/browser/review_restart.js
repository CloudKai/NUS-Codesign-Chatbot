/** Run twice around a real disposable API restart, without navigating between calls. */
async page => {
  page.setDefaultTimeout(10000);
  const assert = (value, message) => { if (!value) throw new Error(message); };
  const baseline = await page.evaluate(() => window.__reviewRestart ?? null);
  const review = page.getByRole('dialog', { name: 'Review', exact: true });
  if (!baseline) {
    await page.setViewportSize({ width: 1440, height: 960 });
    const name = await page.getByRole('region', { name: 'Saved conversation' }).getByRole('heading', { level: 2 }).first().innerText();
    if (!await review.isVisible()) await page.getByRole('button', { name: /Review/ }).filter({ hasText: 'Review' }).first().click();
    await page.getByRole('tab', { name: 'Summary', exact: true }).click();
    await page.evaluate(async name => {
      const list = await (await fetch('/api/v1/reader/threads')).json();
      const id = list.notebooks.find(item => item.name === name).id;
      const path = `/api/v1/reader/threads/${id}`;
      const read = async suffix => {
        const response = await fetch(path + suffix);
        if (!response.ok) throw new Error(`Restart baseline ${suffix}: ${response.status}`);
        return response.json();
      };
      window.__reviewRestart = { name, path, project: await read('/project'), messages: await read('/messages/page?limit=100'), bookmarks: await read('/bookmarks') };
    }, name);
    return 'Baseline captured. Restart disposable API, then run this script again.';
  }
  const same = await page.evaluate(async baseline => {
    for (const [field, suffix] of [['project', '/project'], ['messages', '/messages/page?limit=100'], ['bookmarks', '/bookmarks']]) {
      const response = await fetch(baseline.path + suffix);
      if (!response.ok || JSON.stringify(await response.json()) !== JSON.stringify(baseline[field])) return false;
    }
    return true;
  }, baseline);
  assert(same, 'Public saved data changed across restart');
  await page.reload();
  await review.waitFor();
  assert(await page.getByRole('tab', { name: 'Summary', exact: true }).getAttribute('aria-selected') === 'true', 'Restart reload lost selected Summary');
  await review.getByRole('heading', { name: 'Your project so far', exact: true }).waitFor();
  return 'PASS: Review and selected Summary restored after real API restart; public project/transcript/bookmarks unchanged';
}
