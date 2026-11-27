/**
 * @vitest-environment jsdom
 */
/** Reading cached brief state never generates; the explicit button does, with honest failures. */
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ProjectBriefCard } from './ProjectBrief';
import { browserClient } from './api/client';
import type { Project, ProjectBriefResult } from './api';

const project: Project = { owner_id: 'a', thread_id: 't1', current_stage: 'framing', stages: [],
  pending: null, review: { summary: '', strengths: [], improvements: [], facione_scores: [],
    project_brief: { status: 'missing', version: '', brief: null } } };
const brief: ProjectBriefResult = { status: 'current', version: '', brief: {
  who_and_why: { text: 'Students', evidence: [] }, problem: { text: null, evidence: [] },
  current_idea: { text: null, evidence: [] }, what_matters: { text: null, evidence: [] },
  still_to_explore: { text: null, evidence: [] } } };

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function renderCard(fetch: ReturnType<typeof vi.fn>, saved = vi.fn()) {
  browserClient.setConfig({ baseUrl: 'https://app.test' });
  vi.stubGlobal('fetch', fetch);
  render(<ProjectBriefCard project={project} disabled={false} onSaved={saved}/>);
  return { fetch, saved };
}

it('never starts generation when reading cached state', async () => {
  const { fetch } = renderCard(vi.fn());
  await new Promise(done => window.setTimeout(done, 50));
  expect(fetch).not.toHaveBeenCalled();
});

it('summarises only on the explicit action through the generated contract', async () => {
  const session = { owner_id: 'a', kind: 'registered', display_name: 'Student' };
  const fetch = vi.fn((request: Request) => Promise.resolve(Response.json(
    new URL(request.url).pathname === '/api/v1/reader/session' ? session : brief)));
  const { saved } = renderCard(fetch);
  fireEvent.click(await screen.findByRole('button', { name: /Summarise chat/ }));
  await waitFor(() => expect(saved).toHaveBeenCalledWith(brief));
  const posts = fetch.mock.calls.filter(([sent]) => (sent as Request).method === 'POST');
  expect(posts).toHaveLength(1);
  const request = posts[0][0] as Request;
  expect(new URL(request.url).pathname).toBe('/api/v1/reader/threads/t1/project/brief');
  expect(await request.text()).toBe(JSON.stringify({ retry: false }));
});

it('keeps failures honest and retries explicitly', async () => {
  const fetch = vi.fn((_request: Request) => Promise.resolve(Response.json({}, { status: 503 })));
  renderCard(fetch);
  fireEvent.click(await screen.findByRole('button', { name: /Summarise chat/ }));
  await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('Could not summarise this chat. Try again.'));
  fireEvent.click(screen.getByRole('button', { name: /Summarise chat/ }));
  await waitFor(() => expect(fetch.mock.calls.filter(([sent]) => (sent as Request).method === 'POST')).toHaveLength(2));
  const retryRequest = fetch.mock.calls.filter(([sent]) => (sent as Request).method === 'POST')[1][0] as Request;
  expect(await retryRequest.text()).toBe(JSON.stringify({ retry: true }));
});
