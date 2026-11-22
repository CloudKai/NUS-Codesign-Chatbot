/** Run once before, then again after restarting the disposable backend on 8094. */
async page => {
  const assert = (value, text) => { if (!value) throw new Error(text); };
  const baseline = await page.evaluate(() => window.__bookmarkRestart ?? null);
  if (!baseline) {
    await page.setViewportSize({ width: 1440, height: 960 });
    const fixture = await page.evaluate(async () => {
      const list = await (await fetch('/api/v1/reader/threads')).json();
      const notebook = list.notebooks.find(item => item.name.startsWith('Bookmarks '));
      if (!notebook) throw new Error('Run starred_messages.js first');
      return { path: `/api/v1/reader/threads/${notebook.id}`, notebook };
    });
    await page.reload();
    await page.getByRole('complementary', { name: 'Your notebooks' }).getByRole('button', { name: fixture.notebook.name, exact: true }).click();
    await page.getByRole('heading', { name: fixture.notebook.name, exact: true }).waitFor();
    await page.evaluate(async fixture => {
      const read = async suffix => {
        const response = await fetch(fixture.path + suffix);
        if (!response.ok) throw new Error(`${suffix}: ${response.status}`);
        return response.json();
      };
      window.__bookmarkRestart = { ...fixture, bookmarks: await read('/bookmarks'), transcript: await read('/messages/page?limit=100'), project: await read('/project') };
    }, fixture);
    return 'Saved public bookmark, transcript and project baseline; restart the disposable API, then run again.';
  }
  const unchanged = await page.evaluate(async baseline => {
    for (const [field, suffix] of [['bookmarks', '/bookmarks'], ['transcript', '/messages/page?limit=100'], ['project', '/project']]) {
      const response = await fetch(baseline.path + suffix);
      if (!response.ok || JSON.stringify(await response.json()) !== JSON.stringify(baseline[field])) return false;
    }
    return true;
  }, baseline);
  assert(unchanged, 'Restart must preserve identical public transcript, bookmarks and learning state');
  await page.reload();
  await page.getByRole('heading', { name: baseline.notebook.name, exact: true }).waitFor();
  await page.getByRole('button', { name: /Review/ }).filter({ hasText: 'Review' }).first().click();
  await page.getByRole('tab', { name: 'My work', exact: true }).click();
  await page.waitForFunction(count => document.querySelectorAll('#review-panel-my-work .bookmark-entry').length === count, baseline.bookmarks.messages.length);
  return 'PASS: identical public bookmark, transcript and project data after process restart; reloaded My work renders saved stars.';
}
