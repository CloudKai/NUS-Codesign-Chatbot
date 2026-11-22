/** Whole-chat brief rendering through a disposable API with the scripted external model fixture. */
async page => {
  page.setDefaultTimeout(10000);
  const assert = (value, message) => { if (!value) throw new Error(message); };
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('http://127.0.0.1:8095/');
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
    const first = 'Older residents near campus need more time to cross safely. The signal changes before slower pedestrians finish crossing. We might try a button for extra crossing time, but have not selected an idea. We have not tested whether residents can find and use the button.';
    for (let index = 0; index < 12; index++) {
      const events = await (await post(`/threads/${notebook.id}/lecture/stream`, { student_message: index ? `Hello again ${index}` : first, idempotency_key: `${notebook.id}-${index}` })).text();
      if (!events.split('\n').filter(Boolean).some(line => JSON.parse(line).event === 'done')) throw new Error(events);
    }
    await post(`/threads/${notebook.id}/settings`, { name: `Brief ${notebook.id}` });
    return notebook.id;
  });
  await page.reload();
  await nav.getByRole('button', { name: `Brief ${fixture}`, exact: true }).click();
  await page.getByRole('button', { name: 'Review', exact: true }).click();
  let summaryRequests = 0;
  page.on('request', request => { if (request.url().endsWith('/project/brief')) summaryRequests++; });
  await page.getByRole('tab', { name: 'Summary', exact: true }).click();
  const heading = page.getByRole('heading', { name: 'Your project so far', exact: true });
  assert(await heading.count() === 1, 'Replace recent prompts/recap with Your project so far');
  const brief = page.getByRole('region', { name: 'Your project so far', exact: true });
  const action = brief.getByRole('button', { name: 'Summarise chat', exact: true });
  await action.waitFor();
  assert(summaryRequests === 0, 'Opening Summary must not run synthesis');
  await action.hover();
  await brief.getByRole('tooltip', { name: 'Summarises your whole chat.' }).waitFor();
  await action.focus();
  await page.keyboard.press('Enter');
  await brief.getByText('Older residents crossing near campus need enough time to cross safely.', { exact: true }).waitFor();
  await brief.getByText('Considering a button that requests extra crossing time; no option is selected yet.', { exact: true }).waitFor();
  await brief.getByText('Not yet established', { exact: true }).waitFor();
  assert(!/Your recent prompts|Saved coach recap|Hello again/.test(await brief.innerText()), 'Summary must synthesize the project instead of listing recent prompts');
  const topGap = await heading.evaluate(el => el.getBoundingClientRect().top - el.closest('section').getBoundingClientRect().top);
  assert(topGap <= 18, 'Reduce the heading gap above the project brief');
  const downloadReady = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download project summary', exact: true }).click();
  const download = await downloadReady;
  const stream = await download.createReadStream();
  let markdown = ''; for await (const chunk of stream) markdown += chunk.toString();
  assert(markdown.includes('## Your project so far') && markdown.includes('Considering a button'), 'Download must include the newly generated brief immediately');
  return 'PASS: whole-chat brief from early context, tentative idea, explicit unknowns, no recent-prompt/recap containers and compact heading gap';
}
