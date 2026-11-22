/** Browser visibility must not discard the owner's Review choice or selected view. */
async page => {
  page.setDefaultTimeout(10000);
  const assert = (value, message) => { if (!value) throw new Error(message); };
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('http://127.0.0.1:8093/');
  const fixture = await page.evaluate(async () => {
    const request = async (path, body) => {
      const response = await fetch('/api/v1/reader' + path, body === undefined ? {} : {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error(`${path}: ${response.status}`);
      return response;
    };
    const { notebook } = await (await request('/threads', { kind: 'chat' })).json();
    const path = `/threads/${notebook.id}/project`;
    const stages = (await (await request(path)).json()).stages;
    for (const [index, stage] of stages.entries()) {
      for (let turn = 0; turn < 2; turn++) {
        const stream = await (await request(path + '/stream', {
          student_message: `Older residents struggle to cross safely, stage ${index} ${turn ? 'detail' : 'first idea'}.`,
          idempotency_key: `${notebook.id}-${stage.id}-${turn}`,
        })).text();
        if (!stream.split('\n').filter(Boolean).some(line => JSON.parse(line).event === 'done')) throw new Error(stream);
      }
      const view = await (await request(path)).json();
      if (view.pending) await request(path + `/resolve/${view.pending.id}`, { accepted: true });
    }
    for (let attempt = 0; attempt < 300; attempt++) {
      const view = await (await request(path)).json();
      if (view.review.facione_scores.some(score => score.score !== null)) break;
      await new Promise(resolve => setTimeout(resolve, 10));
    }
    await request(`/threads/${notebook.id}/settings`, { name: `Persistence ${notebook.id}` });
    return notebook.id;
  });
  await page.reload();
  await page.getByRole('button', { name: `Persistence ${fixture}`, exact: true }).click();
  const review = page.getByRole('dialog', { name: 'Review', exact: true });
  const open = page.getByRole('button', { name: /Review/ }).filter({ hasText: 'Review' }).first();
  await open.waitFor();
  if (!await review.isVisible()) await open.click();
  await page.getByRole('tab', { name: 'Summary', exact: true }).click();
  // This CLI keeps native tabs visible, so deliver the browser's visibility events explicitly.
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, value: true });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await page.getByText('Checking your session…', { exact: true }).waitFor();
  await page.evaluate(() => {
    delete document.hidden;
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await open.waitFor();
  assert(await review.isVisible(), 'Review must reopen after the tab returns and owner is reverified');
  assert(await page.getByRole('tab', { name: 'Summary', exact: true }).getAttribute('aria-selected') === 'true', 'Returning must preserve the selected Review tab');
  await page.goto('about:blank');
  await page.goBack();
  await review.waitFor();
  await page.reload();
  await review.waitFor();
  await review.getByRole('button', { name: 'Close Review', exact: true }).click();
  await page.reload();
  await open.waitFor();
  assert(!await review.isVisible(), 'Explicit close must survive reload');
  await page.setViewportSize({ width: 390, height: 960 });
  await open.click();
  await page.getByRole('tab', { name: 'Summary', exact: true }).click();
  await review.getByRole('button', { name: 'Practice this', exact: true }).click();
  assert(await review.isVisible(), 'Adding a practice draft must keep mobile Review open until explicit close');
  await review.getByText('Prompt added to your draft. Close Review to edit it.', { exact: true }).waitFor();
  await review.getByRole('button', { name: 'Close Review', exact: true }).click();
  assert((await page.getByRole('textbox', { name: /Your (lecture question|project contribution)/ }).inputValue()).includes('practise'), 'Practice draft was lost');
  return 'PASS: visibility, navigation and reload restore Review; explicit close persists; mobile practice stays open';
}
