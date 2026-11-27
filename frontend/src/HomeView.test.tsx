/**
 * @vitest-environment jsdom
 */
/** The resume card reuses persisted projections: recent work, saved feedback and truthful empty states. */
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { HomeView } from './HomeView';
import { browserClient } from './api/client';
import type { ChatSummary, Notebook, Project } from './api';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

const notebook: Notebook = {
  id: 'nb1', name: 'Design project', kind: 'notebook',
  parent_notebook_id: null, pinned: false,
};
const chat: Notebook = {
  id: 'ch1', name: 'Original chat', kind: 'chat',
  parent_notebook_id: 'nb1', pinned: false,
};
const summaries: Record<string, ChatSummary> = {
  ch1: { preview: 'We discussed the crossing problem.', activity_at: '2026-11-24T09:00:00Z' },
};

const project: Project = {
  owner_id: 'a', thread_id: 'ch1', current_stage: 'problem_identification',
  stages: [{
    id: 'problem_identification', label: 'Problem identification', completed: false,
    selectable: true, artifact_label: 'Working problem statement',
    student_work: [{ message_id: 'm1', text: 'Students cross unsafely at peak hours.' }],
    feedback: [], coach_summary: '', decision: '', next_action: 'Describe the affected people.', criteria: [],
  }],
  pending: null,
  review: {
    project_brief: { status: 'missing', version: '', brief: null },
    summary: '',
    strengths: [],
    improvements: [{ stage_id: 'problem_identification',
      items: ['Name who is affected by the crossing.'] }],
    facione_scores: [],
  },
};

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status,
    headers: { 'Content-Type': 'application/json' } }));
}

function stubBackend(handlers?: { project?: Project; artifacts?: unknown[]; canvases?: unknown[] }) {
  browserClient.setConfig({ baseUrl: 'https://app.test' });
  const urlOf = (input: RequestInfo | URL) => (input instanceof Request ? input.url : String(input));
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = urlOf(input);
    if (url.includes('/reader/session')) return jsonResponse({ owner_id: 'a' });
    if (url.includes('/project') && !url.includes('brief')) {
      return jsonResponse(handlers?.project ?? project);
    }
    if (url.endsWith('/artifacts')) return jsonResponse({ owner_id: 'a', thread_id: 'nb1',
      kinds: [], artifacts: handlers?.artifacts ?? [] });
    if (url.endsWith('/canvases')) return jsonResponse({ owner_id: 'a', thread_id: 'nb1',
      node_kinds: [], relations: [], stages: [], canvases: handlers?.canvases ?? [] });
    return jsonResponse({ detail: 'not found' }, 404);
  }));
}

function renderHome(overrides?: { openArtifact?: (folderId: string, artifactId: string) => void;
  openCanvas?: (folderId: string, canvasId: string) => void }) {
  return render(<HomeView owner="a" name="Kai" entries={[notebook, chat]} summaries={summaries}
    locked={false} openChat={vi.fn()} startChat={vi.fn()} expired={vi.fn()}
    openArtifact={overrides?.openArtifact} openCanvas={overrides?.openCanvas}/>);
}

it('shows recently edited document and canvas work that opens the owned resource', async () => {
  stubBackend({
    artifacts: [{ id: 'a1', thread_id: 'nb1', title: 'Field notes', kind: 'notes',
      schema_version: 1, revision: 2, origin: 'editor',
      created_at: '', updated_at: '2026-11-24T10:00:00Z' }],
    canvases: [{ id: 'c1', thread_id: 'nb1', title: 'Concept map', schema_version: 1,
      revision: 3, origin: 'editor', created_at: '', updated_at: '2026-11-23T10:00:00Z' }],
  });
  const openArtifact = vi.fn();
  renderHome({ openArtifact });
  const work = await screen.findByRole('region', { name: 'Recent work' });
  expect(work.textContent).toContain('Field notes');
  expect(work.textContent).toContain('Concept map');
  fireEvent.click(screen.getByRole('button', { name: /Field notes/ }));
  await waitFor(() => expect(openArtifact).toHaveBeenCalledWith('nb1', 'a1'));
});

it('shows the saved coach feedback bound to the current stage', async () => {
  stubBackend();
  renderHome();
  expect(await screen.findByText(/Name who is affected by the crossing/)).toBeTruthy();
});

it('states truthfully when there is no saved work yet', async () => {
  stubBackend({ project: { ...project, review: { project_brief: { status: 'missing', version: '', brief: null },
    summary: '', strengths: [], improvements: [], facione_scores: [] } } });
  renderHome();
  expect(await screen.findByText(/No documents yet/)).toBeTruthy();
  expect(await screen.findByText(/No canvases yet/)).toBeTruthy();
  expect(screen.queryByText(/Name who is affected/)).toBeNull();
});

it('shows the persisted recap of the most recently confirmed milestone', async () => {
  stubBackend({ project: { ...project, recaps: [
    { id: 'recap-1', stage_id: 'problem_identification', stage_label: 'Problem identification',
      transition_id: 'tr-1', next_stage_id: 'concept_generation',
      next_stage_label: 'Concept generation',
      next_action: 'Describe two different concepts.',
      accomplishments: 'Named the unsafe peak-hour crossing.',
      changes: 'Moved from a vague complaint to a specific need.',
      gaps: ['Who else is affected?'], relevant_work: [],
      confirmed_at: '2026-11-25T01:00:00Z' },
  ] } });
  renderHome();
  const recap = await screen.findByRole('region', { name: 'Milestone recap' });
  expect(recap.textContent).toContain('Problem identification');
  expect(recap.textContent).toContain('Named the unsafe peak-hour crossing.');
  expect(recap.textContent).toContain('Moved from a vague complaint to a specific need.');
  expect(recap.textContent).toContain('Who else is affected?');
  expect(recap.textContent).toContain('Describe two different concepts.');
});

it('shows To Work on with the AI rationale and a single Continue, without stage buttons on Home', async () => {
  const pendingProject: Project = {
    ...project,
    pending: { id: 'tr-1', from_stage: 'problem_identification',
      to_stage: 'concept_generation',
      rationale: 'Your problem statement is clear — generate concepts next.' },
  };
  const openChat = vi.fn();
  const calls: string[] = [];
  stubBackend();
  browserClient.setConfig({ baseUrl: 'https://app.test' });
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = input instanceof Request ? input.url : String(input);
    calls.push(url);
    if (url.includes('/reader/session')) return jsonResponse({ owner_id: 'a' });
    if (url.includes('/project') && !url.includes('brief')) return jsonResponse(pendingProject);
    if (url.endsWith('/artifacts')) return jsonResponse({ owner_id: 'a', thread_id: 'nb1',
      kinds: [], artifacts: [] });
    if (url.endsWith('/canvases')) return jsonResponse({ owner_id: 'a', thread_id: 'nb1',
      node_kinds: [], relations: [], stages: [], canvases: [] });
    return jsonResponse({ detail: 'not found' }, 404);
  }));
  render(<HomeView owner="a" name="Kai" entries={[notebook, chat]} summaries={summaries}
    locked={false} openChat={openChat} startChat={vi.fn()} expired={vi.fn()}/>);
  await screen.findByText(/Your problem statement is clear/);
  expect(screen.getByText(/To work on/i)).toBeTruthy();
  expect(screen.getByRole('button', { name: /Continue/ })).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Move on' })).toBeNull();
  expect(screen.queryByRole('button', { name: 'Stay here' })).toBeNull();
  // Continue opens the project chat; Home itself never writes a stage decision.
  fireEvent.click(screen.getByRole('button', { name: /Continue/ }));
  expect(openChat).toHaveBeenCalledWith('ch1');
  expect(calls.some(url => url.includes('/resolve'))).toBe(false);
});

it('shows To Work on with the saved next action when no stage decision is pending', async () => {
  stubBackend();
  render(<HomeView owner="a" name="Kai" entries={[notebook, chat]} summaries={summaries}
    locked={false} openChat={vi.fn()} startChat={vi.fn()} expired={vi.fn()}/>);
  await screen.findByText(/Describe the affected people./);
  expect(screen.queryByRole('button', { name: 'Move on' })).toBeNull();
  expect(screen.queryByRole('button', { name: 'Stay here' })).toBeNull();
});

it('starts an Improve my design chat from Home', () => {
  const startChat = vi.fn();
  render(<HomeView owner="a" name="Kai" entries={[]} summaries={{}}
    locked={false} openChat={vi.fn()} startChat={startChat} expired={vi.fn()}/>);
  fireEvent.click(screen.getByRole('button', { name: 'Improve my design' }));
  expect(startChat).toHaveBeenCalledWith('improve');
  expect(screen.getByRole('button', { name: 'Start my design project' })).toBeTruthy();
});
