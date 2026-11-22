/** Review disclosure behavior through the rendered workspace and disposable mock API. */
async page => {
  page.setDefaultTimeout(10000);
  const assert = (value, message) => { if (!value) throw new Error(message); };
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('http://127.0.0.1:8093/');
  const nav = page.getByRole('complementary', { name: 'Your notebooks' });
  const guest = page.getByRole('button', { name: 'Continue as Guest' });
  await guest.or(nav).waitFor();
  if (await guest.isVisible()) await guest.click();
  await nav.waitFor();
  const newChat = await page.evaluate(async () => {
    const response = await fetch('/api/v1/reader/threads', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind: 'chat' }) });
    if (!response.ok) throw new Error('Disposable chat creation failed');
    const { notebook } = await response.json();
    const name = `Empty review ${notebook.id}`;
    const renamed = await fetch(`/api/v1/reader/threads/${notebook.id}/settings`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) });
    if (!renamed.ok) throw new Error('Disposable chat naming failed');
    return { id: notebook.id, name };
  });
  await page.reload();
  await page.getByRole('complementary', { name: 'Your notebooks' }).getByRole('button', { name: newChat.name, exact: true }).click();
  await page.getByRole('heading', { name: newChat.name, exact: true }).waitFor();
  await page.getByRole('button', { name: 'Review', exact: true }).click();
  await page.getByRole('tab', { name: 'Summary', exact: true }).click();
  const summary = page.getByRole('tabpanel', { name: 'Summary', exact: true });
  for (const stage of ['Problem identification', 'Concept generation', 'Design specification', 'Ethics & Critical Thinking', 'Reflection']) {
    const toggle = summary.getByRole('button', { name: stage, exact: true });
    assert(await toggle.count() === 1, `${stage} must have its own disclosure`);
    assert(await toggle.getAttribute('aria-expanded') === 'false', 'Stage starts compact');
    await toggle.focus(); await page.keyboard.press('Enter');
    const positive = summary.getByRole('region', { name: `Going well in ${stage}`, exact: true });
    await positive.waitFor();
    await page.keyboard.press('Space');
    assert(!await positive.isVisible(), `${stage} did not collapse`);
    await page.keyboard.press('Enter');
    await positive.waitFor();
    const heading = summary.getByRole('region', { name: stage, exact: true });
    const good = heading.getByRole('button', { name: 'Going well', exact: true });
    await good.click();
    assert(!await positive.isVisible(), 'Going well did not collapse');
    await heading.getByRole('region', { name: `To work on in ${stage}`, exact: true }).waitFor();
    const improve = heading.getByRole('button', { name: 'To work on', exact: true });
    await improve.click();
    await good.click();
    await positive.waitFor();
    assert(!await heading.getByRole('region', { name: `To work on in ${stage}`, exact: true }).isVisible(), 'Feedback groups must collapse independently');
    await improve.click();
  }
  return 'PASS: every stage and both feedback groups collapse independently with keyboard support';
}
