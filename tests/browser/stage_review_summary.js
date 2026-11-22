/** Run with playwright-cli run-code --filename against a disposable mock stack at 8093. */
async page => {
  page.setDefaultTimeout(10000);
  await page.setViewportSize({ width: 1440, height: 960 });
  const assert = (value, message) => { if (!value) throw new Error(message); };
  await page.goto('http://127.0.0.1:8093/');
  const guest = page.getByRole('button', { name: 'Continue as Guest' });
  const nav = page.getByRole('complementary', { name: 'Your notebooks' });
  await guest.or(nav).waitFor();
  if (await guest.isVisible()) await guest.click();
  await nav.waitFor();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  const fixture = await page.evaluate(async () => {
    const request = async (path, body) => {
      const response = await fetch('/api/v1/reader' + path, body === undefined ? {} : {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error(`${path}: ${response.status} ${await response.text()}`);
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
        const events = stream.trim().split('\n').map(line => JSON.parse(line));
        if (!events.some(event => event.event === 'done')) throw new Error(`Fixture turn failed: ${stream}`);
      }
      const view = await (await request(path)).json();
      if (view.pending) await request(path + `/resolve/${view.pending.id}`, { accepted: true });
    }
    await request(`/threads/${notebook.id}/settings`, { name: `Summary ${notebook.id}` });
    // The final checkpoint is saved asynchronously, just as in the HTTP student journey.
    let project;
    for (let attempt = 0; attempt < 300; attempt++) {
      project = await (await request(path)).json();
      if (project.review.strengths.some(group => group.stage_id === 'reflection' && group.items.length)) break;
      await new Promise(resolve => setTimeout(resolve, 10));
    }
    return project;
  });
  await page.reload();
  await nav.getByRole('button', { name: `Summary ${fixture.thread_id}`, exact: true }).click();
  await page.getByRole('heading', { name: `Summary ${fixture.thread_id}`, exact: true }).waitFor();
  await page.getByRole('button', { name: /Review/, exact: false }).filter({ hasText: 'Review' }).first().click();
  await page.getByRole('tab', { name: 'Summary', exact: true }).click();
  const summary = page.getByRole('tabpanel', { name: 'Summary', exact: true });
  const headings = await summary.getByRole('heading').allTextContents();
  assert(fixture.current_stage === 'reflection' && fixture.stages.every(stage => stage.student_work.length), 'Fixture must contain work in all five stages');
  assert(headings.findIndex(text => text.startsWith('Problem identification')) > 0, 'Summary must show ordered stage feedback after its project summary');
  let last = 0;
  for (const stage of fixture.stages) {
    const position = headings.findIndex((text, index) => index > last && text.startsWith(stage.label));
    assert(position > last, `Missing or unordered ${stage.label} feedback`);
    last = position;
    const toggle = summary.getByRole('button', { name: stage.label, exact: true });
    if (await toggle.getAttribute('aria-expanded') === 'false') await toggle.click();
    for (const [field, label] of [['strengths', 'Going well'], ['improvements', 'To work on']]) {
      const items = fixture.review[field].find(group => group.stage_id === stage.id)?.items ?? [];
      const section = summary.getByRole('region', { name: `${label} in ${stage.label}`, exact: true });
      await section.waitFor();
      for (const text of items) assert((await section.innerText()).includes(text), `Saved feedback changed: ${text}`);
    }
  }
  assert(headings.indexOf('How your idea scores') > last, 'Facione must follow all stage feedback');
  const summaryText = summary.getByRole('heading', { name: 'Your project so far', exact: true });
  await summaryText.waitFor();
  const writes = [];
  const watchWrites = request => { if (request.method() === 'POST') writes.push(request.url()); };
  page.on('request', watchWrites);
  const review = page.getByRole('dialog', { name: 'Review', exact: true });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 960 });
    await page.getByRole('tab', { name: 'Summary', exact: true }).click();
    const hero = summary.getByRole('region', { name: 'Your project so far', exact: true }).first();
    const heroBox = await hero.boundingBox();
    const panelBox = await summary.boundingBox();
    assert(Math.abs(heroBox.width - panelBox.width) < 2, 'Project summary must span the panel width');
    assert(await review.evaluate(element => element.scrollWidth <= element.clientWidth), `${width}px Review overflows horizontally`);
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${width}px page overflows`);
    const positiveBox = await summary.getByRole('region', { name: 'Going well in Problem identification', exact: true }).boundingBox();
    const nextBox = await summary.getByRole('region', { name: 'To work on in Problem identification', exact: true }).boundingBox();
    assert(nextBox.y - positiveBox.y - positiveBox.height >= 12, 'Separate strengths and next steps so wrapped feedback stays readable');
    const scoreSection = summary.getByRole('region', { name: 'How your idea scores' });
    const detail = scoreSection.locator('details').filter({ has: page.getByText('All six skill scores', { exact: true }) });
    if (!await detail.evaluate(element => element.open)) await detail.locator('summary').click();
    for (const score of fixture.review.facione_scores.filter(item => item.score !== null)) {
      const row = scoreSection.getByRole('listitem').filter({ has: page.getByText(score.dimension, { exact: true }) });
      assert((await row.innerText()).includes(`${score.score}/4`), `Changed ${score.dimension} score`);
    }
    await scoreSection.getByRole('button', { name: 'Show tips', exact: true }).click();
    assert(await scoreSection.getByRole('button', { name: 'Hide tips' }).getAttribute('aria-pressed') === 'true', 'Tips did not open');
    await scoreSection.getByRole('button', { name: 'Hide tips' }).click();
    await summaryText.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `output/playwright/summary-30/summary-${width}.png` });
  }
  // Existing Facione practice inserts an editable draft without sending a turn.
  await summary.getByRole('button', { name: 'Practice this', exact: true }).click();
  const close = review.getByRole('button', { name: 'Close Review' });
  if (await close.isVisible()) await close.click();
  const draft = page.getByRole('textbox', { name: /Your (lecture question|project contribution)/ });
  assert((await draft.inputValue()).includes('practise'), 'Practice did not insert an editable draft');
  await page.reload();
  await page.getByRole('button', { name: /Review/, exact: false }).filter({ hasText: 'Review' }).first().click();
  await page.getByRole('tab', { name: 'Summary', exact: true }).click();
  await summaryText.waitFor();
  const summaryTab = page.getByRole('tab', { name: 'Summary', exact: true });
  await summaryTab.focus();
  await page.keyboard.press('ArrowLeft');
  assert(await page.getByRole('tab', { name: 'Progression' }).getAttribute('aria-selected') === 'true', 'Keyboard tabs stopped working');
  await page.keyboard.press('ArrowRight');
  await summaryText.waitFor();
  assert(await summaryTab.evaluate(element => element === document.activeElement), 'Summary tab lost keyboard focus');
  await summary.getByRole('button', { name: 'Problem identification', exact: true }).click();
  await summary.getByRole('region', { name: 'Going well in Problem identification' }).getByText(fixture.review.strengths[0].items[0], { exact: true }).waitFor();
  page.off('request', watchWrites);
  assert(writes.length === 0, `Review generated a write: ${writes.join(', ')}`);
  assert(errors.length === 0, `Browser errors: ${errors.join('; ')}`);
  return 'PASS: saved stage order and wording, full-width summary, Facione scores/tips/practice, keyboard tabs, reload, no Review writes, desktop/390px layout and clean console';
}
