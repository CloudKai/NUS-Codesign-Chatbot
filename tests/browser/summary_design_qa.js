/** Real rendered Summary hierarchy with substantive brief, populated stage feedback and assessed skills. */
async page => {
  page.setDefaultTimeout(10000);
  const assert = (value, message) => { if (!value) throw new Error(message); };
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('http://127.0.0.1:8095/');
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
    const first = 'Older residents near campus need more time to cross safely. The signal changes before slower pedestrians finish crossing. We might try a button for extra crossing time, but have not selected an idea. We have not tested whether residents can find and use the button.';
    for (const [index, stage] of stages.entries()) {
      for (let turn = 0; turn < 2; turn++) {
        const stream = await (await request(path + '/stream', { student_message: index === 0 && turn === 0 ? first : `Older residents struggle to cross safely, stage ${index} ${turn ? 'detail' : 'first idea'}.`, idempotency_key: `${notebook.id}-${stage.id}-${turn}` })).text();
        if (!stream.split('\n').filter(Boolean).some(line => JSON.parse(line).event === 'done')) throw new Error(stream);
      }
      const view = await (await request(path)).json();
      if (view.pending) await request(path + `/resolve/${view.pending.id}`, { accepted: true });
    }
    await request(`/threads/${notebook.id}/settings`, { name: `Summary design ${notebook.id}` });
    for (let attempt = 0; attempt < 300; attempt++) {
      const project = await (await request(path)).json();
      if (project.review.strengths.some(group => group.stage_id === 'reflection' && group.items.length)) return project;
      await new Promise(resolve => setTimeout(resolve, 10));
    }
    throw new Error('Mock saved feedback did not finish');
  });
  await page.reload();
  await page.getByRole('complementary', { name: 'Your notebooks' }).getByRole('button', { name: `Summary design ${fixture.thread_id}`, exact: true }).click();
  await page.getByRole('button', { name: /Review/ }).filter({ hasText: 'Review' }).first().click();
  await page.getByRole('tab', { name: 'Summary', exact: true }).click();
  const brief = page.getByRole('region', { name: 'Your project so far', exact: true });
  await brief.getByText('Older residents crossing near campus need enough time to cross safely.', { exact: true }).waitFor();
  for (const appearance of ['Light', 'Dark']) {
    await page.evaluate(async appearance => {
      await fetch('/api/v1/reader/preferences', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ appearance }) });
    }, appearance);
    await page.reload(); await brief.waitFor();
    await page.waitForFunction(appearance => document.documentElement.dataset.appearance === appearance, appearance);
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 960 });
      const feedback = page.getByRole('region', { name: 'Stage feedback', exact: true });
      for (const stage of fixture.stages) {
        const button = feedback.getByRole('button', { name: stage.label, exact: true });
        assert(await button.getAttribute('aria-expanded') === 'false', 'Supporting stage detail should start compact');
        const good = fixture.review.strengths.find(group => group.stage_id === stage.id)?.items.length ?? 0;
        const improve = fixture.review.improvements.find(group => group.stage_id === stage.id)?.items.length ?? 0;
        assert((await button.innerText()).includes(`${good} going well · ${improve} to work on`), 'Saved feedback counts changed');
        assert((await button.boundingBox()).height >= 44, 'Compact rows retain 44px targets');
      }
      await page.getByRole('tab', { name: 'Summary', exact: true }).click();
      await page.getByRole('dialog', { name: 'Review', exact: true }).evaluate(el => el.scrollTo({ top: 0 }));
      await page.screenshot({ path: `output/playwright/project-brief/summary-overview-${appearance}-${width}.png` });
      const skills = page.getByRole('region', { name: 'How your idea scores', exact: true });
      await skills.getByRole('button', { name: 'Practice this', exact: true }).scrollIntoViewIfNeeded();
      const detail = skills.locator('details');
      assert(!await detail.evaluate(el => el.open), 'Scores start condensed');
      await page.screenshot({ path: `output/playwright/project-brief/summary-feedback-${appearance}-${width}.png` });
      await detail.locator('summary').press('Enter');
      assert(await detail.getByRole('listitem').count() === 6, 'All six saved skill rows remain available');
      await detail.getByRole('button', { name: 'Show tips', exact: true }).click();
      await detail.getByRole('button', { name: 'Hide tips', exact: true }).click();
      await detail.locator('summary').press('Space');
    }
  }
  return 'PASS: populated brief, exact stage counts, clean defaults, 44px rows and all skill scores/tips in desktop/phone Light/Dark';
}
