/** Verify honest empty Summary states on the same disposable mock stack as stage_review_summary.js. */
async page => {
  page.setDefaultTimeout(10000);
  const assert = (value, message) => { if (!value) throw new Error(message); };
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('http://127.0.0.1:8093/');
  const nav = page.getByRole('complementary', { name: 'Your notebooks' });
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
  await summary.getByText('Your brief will take shape as you discuss your project.', { exact: true }).waitFor();
  assert(await summary.getByText('Not yet established', { exact: true }).count() === 5, 'Empty project brief must not invent facts');
  for (const stage of ['Problem identification', 'Concept generation', 'Design specification', 'Ethics & Critical Thinking', 'Reflection']) {
    await summary.getByRole('button', { name: stage, exact: true }).click();
    await summary.getByRole('region', { name: `Going well in ${stage}`, exact: true })
      .getByText('No saved Going well feedback for this stage yet.', { exact: true }).waitFor();
    await summary.getByRole('region', { name: `To work on in ${stage}`, exact: true })
      .getByText('No saved To work on feedback for this stage yet.', { exact: true }).waitFor();
  }
  await summary.getByText('Your skill scores will appear here as you share your thinking with the coach.', { exact: true }).waitFor();
  assert(await summary.getByRole('button', { name: 'Practice this' }).count() === 0, 'Empty assessments must not imply a score');
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 960 });
    await page.screenshot({ path: `output/playwright/summary-30/empty-${width}.png` });
  }
  return 'PASS: missing project summary, all ten stage-feedback empty states and unassessed Facione remain honest without any stars';
}
