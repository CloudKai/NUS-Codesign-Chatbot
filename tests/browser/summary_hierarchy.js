/** Summary presents a project brief first and keeps supporting feedback compact until requested. */
async page => {
  page.setDefaultTimeout(10000);
  const assert = (value, message) => { if (!value) throw new Error(message); };
  await page.reload();
  const summary = page.getByRole('tabpanel', { name: 'Summary', exact: true });
  await page.getByRole('tab', { name: 'Summary', exact: true }).click();
  await summary.getByRole('heading', { name: 'Your project so far', exact: true }).waitFor();
  const feedback = summary.getByRole('region', { name: 'Stage feedback', exact: true });
  assert(await feedback.count() === 1, 'Consolidate stage feedback into one clearly named section');
  for (const label of ['Problem identification', 'Concept generation', 'Design specification', 'Ethics & Critical Thinking', 'Reflection']) {
    const toggle = feedback.getByRole('button', { name: label, exact: true });
    assert(await toggle.getAttribute('aria-expanded') === 'false', `${label} should start compact`);
    await toggle.focus(); await page.keyboard.press('Enter');
    await feedback.getByRole('region', { name: `Going well in ${label}`, exact: true }).waitFor();
    await toggle.press('Space');
  }
  const skills = summary.getByRole('region', { name: 'How your idea scores', exact: true });
  if (await skills.getByRole('button', { name: 'Practice this', exact: true }).count()) {
    const detail = skills.locator('details').filter({ has: page.getByText('All six skill scores', { exact: true }) });
    assert(!await detail.evaluate(element => element.open), 'Detailed scores start tucked away');
    await detail.locator('summary').press('Enter');
    await detail.getByRole('button', { name: 'Show tips', exact: true }).waitFor();
  }
  return 'PASS: clear overview, one compact stage-feedback section, keyboard disclosures and on-demand skill detail';
}
