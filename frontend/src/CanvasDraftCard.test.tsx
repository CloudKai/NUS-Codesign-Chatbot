/**
 * @vitest-environment jsdom
 */
/** Canvas draft cards create a NEW artifact only on explicit confirmation, keeping node provenance. */
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { CanvasDraftCard } from './CanvasDraftCard';
import { browserClient } from './api/client';
import type { Canvas, CanvasDraft } from './api';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); sessionStorage.clear(); });

const savedCanvas: Canvas = {
  owner_id: 'a', thread_id: 'nb1', id: 'c1', title: 'Concept map', schema_version: 1,
  revision: 6, origin: 'editor', created_at: '', updated_at: '',
  graph: { nodes: [
    { id: 'n0', kind: 'problem', title: 'Unsafe crossing', description: 'left turns', x: 0, y: 0,
      references: [{ kind: 'source', id: 'src-1' }] },
    { id: 'n1', kind: 'stakeholder', title: 'Students', description: '', x: 200, y: 100 },
  ], edges: [] },
};

const draft: CanvasDraft = {
  id: 'cd-mock-abc12345', title: 'Draft brief: Unsafe crossing',
  draft_text: 'Older pedestrians need a crossing that never rushes them.',
  rationale: 'Synthesized from the selected canvas nodes for your review.',
  base_canvas_id: 'c1', base_canvas_revision: 6, node_ids: ['n0', 'n1'],
  provenance: 'coach',
};

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status,
    headers: { 'Content-Type': 'application/json' } }));
}

function stubBackend(handlers: { canvas?: Canvas; capturePost?: (body: unknown) => void }) {
  browserClient.setConfig({ baseUrl: 'https://app.test' });
  const urlOf = (input: RequestInfo | URL) => (input instanceof Request ? input.url : String(input));
  const methodOf = (input: RequestInfo | URL, init?: RequestInit) =>
    input instanceof Request ? input.method : (init?.method ?? 'GET');
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = urlOf(input);
    const method = methodOf(input, init);
    const bodyText = typeof init?.body === 'string' ? init.body
      : input instanceof Request ? await input.text() : undefined;
    if (url.includes('/reader/session')) return jsonResponse({ owner_id: 'a' });
    if (method === 'POST' && url.endsWith('/artifacts')) {
      handlers.capturePost?.(bodyText ? JSON.parse(bodyText) as unknown : undefined);
      return jsonResponse({ owner_id: 'a', thread_id: 'nb1', id: 'art-new',
        title: 'Draft brief', kind: 'notes', schema_version: 1, revision: 1,
        origin: 'editor', created_at: '', updated_at: '', references: [],
        document: { type: 'doc', content: [] } });
    }
    if (url.includes('/canvases/c1')) {
      if (handlers.canvas === undefined) return jsonResponse({ detail: 'not found' }, 404);
      return jsonResponse(handlers.canvas);
    }
    return jsonResponse({ detail: 'not found' }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

it('creates a new artifact with node and evidence provenance on explicit confirmation', async () => {
  const capturePost = vi.fn();
  stubBackend({ canvas: savedCanvas, capturePost });
  render(<CanvasDraftCard threadId="nb1" draft={draft}/>);
  fireEvent.click(await screen.findByRole('button', { name: /Review draft/ }));
  const text = screen.getByLabelText('Draft text') as HTMLTextAreaElement;
  fireEvent.change(text, { target: { value: 'Edited draft body.' } });
  fireEvent.click(screen.getByRole('button', { name: 'Create new artifact' }));
  await waitFor(() => expect(capturePost).toHaveBeenCalledTimes(1));
  const body = capturePost.mock.calls[0][0] as { title: string; kind: string;
    references: { kind: string; id: string; canvas_id?: string }[];
    document: { content: { content?: { text?: string }[] }[] } };
  expect(body.title).toBe('Draft brief: Unsafe crossing');
  expect(body.kind).toBe('notes');
  const nodeRefs = body.references.filter(reference => reference.kind === 'canvas_node');
  expect(nodeRefs.map(reference => reference.id).sort()).toEqual(['n0', 'n1']);
  expect(nodeRefs.every(reference => reference.canvas_id === 'c1')).toBe(true);
  // Evidence linked on the contributing nodes stays attached to the artifact.
  expect(body.references.some(reference => reference.kind === 'source' && reference.id === 'src-1')).toBe(true);
  expect(JSON.stringify(body.document)).toContain('Edited draft body.');
});

it('warns when the canvas changed but still lets the student confirm explicitly', async () => {
  const capturePost = vi.fn();
  stubBackend({ canvas: { ...savedCanvas, revision: 9 }, capturePost });
  render(<CanvasDraftCard threadId="nb1" draft={draft}/>);
  fireEvent.click(await screen.findByRole('button', { name: /Review draft/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Create new artifact' }));
  expect(await screen.findByRole('alert')).toBeTruthy();
  expect(capturePost).not.toHaveBeenCalled();
  // The explicit second confirmation goes through.
  fireEvent.click(screen.getByRole('button', { name: 'Create new artifact' }));
  await waitFor(() => expect(capturePost).toHaveBeenCalledTimes(1));
});

it('retries an ambiguous create with the same deterministic draft request id', async () => {
  browserClient.setConfig({ baseUrl: 'https://app.test' });
  const posted: {
    request_id?: string; origin?: string;
    references: { kind: string; id: string; canvas_id?: string; revision?: number }[];
  }[] = [];
  let createAttempts = 0;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = input instanceof Request ? input : null;
    const url = request ? request.url : String(input);
    const method = request ? request.method : (init?.method ?? 'GET');
    if (url.includes('/reader/session')) return jsonResponse({ owner_id: 'a' });
    if (url.includes('/canvases/c1')) return jsonResponse(savedCanvas);
    if (method === 'POST' && url.endsWith('/artifacts')) {
      const bodyText = request ? await request.text() : String(init?.body ?? '');
      posted.push(JSON.parse(bodyText));
      createAttempts += 1;
      if (createAttempts === 1) throw new TypeError('network down');
      return jsonResponse({ owner_id: 'a', thread_id: 'nb1', id: 'art-new',
        title: 'Draft brief', kind: 'notes', schema_version: 1, revision: 1,
        origin: 'coach_draft', created_at: '', updated_at: '', references: [],
        document: { type: 'doc', content: [] } });
    }
    return jsonResponse({ detail: 'not found' }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
  render(<CanvasDraftCard threadId="nb1" draft={draft}/>);
  fireEvent.click(await screen.findByRole('button', { name: /Review draft/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Create new artifact' }));

  await waitFor(() => expect(posted).toHaveLength(1));
  const alert = await screen.findByRole('alert');
  expect(alert.textContent).toMatch(/couldn't confirm whether the artifact was created/i);
  expect(alert.textContent).toMatch(/a retry is safe and will not duplicate it/i);
  expect(alert.textContent).not.toMatch(/Nothing was saved/i);

  // The retry inside the same review reuses the deterministic id, and the
  // editable payload is frozen so the retry is provably the same request.
  expect((screen.getByLabelText('Artifact title') as HTMLInputElement).disabled).toBe(true);
  expect((screen.getByLabelText('Draft text') as HTMLTextAreaElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Create new artifact' }));
  await waitFor(() => expect(posted).toHaveLength(2));
  expect(posted[0].request_id).toBe('draft:cd-mock-abc12345');
  expect(posted[1].request_id).toBe('draft:cd-mock-abc12345');
  expect(posted[1].origin).toBe('coach_draft');
  const nodeRefs = posted[1].references.filter(reference => reference.kind === 'canvas_node');
  expect(nodeRefs.every(reference => reference.revision === 6)).toBe(true);
  await waitFor(() => expect(screen.queryByText(/Suggested draft/)).toBeNull());
});

it('reports an unavailable canvas and creates nothing', async () => {
  const capturePost = vi.fn();
  stubBackend({ capturePost });
  render(<CanvasDraftCard threadId="nb1" draft={draft}/>);
  fireEvent.click(await screen.findByRole('button', { name: /Review draft/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Create new artifact' }));
  expect(await screen.findByRole('alert')).toBeTruthy();
  expect(capturePost).not.toHaveBeenCalled();
});

it('rejects a draft without creating anything and never offers it twice', async () => {
  const fetchMock = stubBackend({ canvas: savedCanvas });
  render(<CanvasDraftCard threadId="nb1" owner="a" draft={draft}/>);
  fireEvent.click(await screen.findByRole('button', { name: 'Reject draft' }));
  await waitFor(() => expect(screen.queryByText(/Draft brief: Unsafe crossing/)).toBeNull());
  expect(fetchMock.mock.calls.every(call => !String(call[0]).endsWith('/artifacts'))).toBe(true);
  render(<CanvasDraftCard threadId="nb1" owner="a" draft={draft}/>);
  expect(screen.queryByText(/Draft brief: Unsafe crossing/)).toBeNull();
});
