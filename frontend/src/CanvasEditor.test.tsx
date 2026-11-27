/**
 * @vitest-environment jsdom
 */
/** The canvas outline adds, edits and connects nodes; saving is explicit and conflicts are honest. */
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { CanvasEditor } from './CanvasEditor';
import { browserClient } from './api/client';
import type { Canvas } from './api';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); sessionStorage.clear(); });

if (!('ResizeObserver' in globalThis)) {
  class ResizeObserverStub { observe() {} unobserve() {} disconnect() {} }
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = ResizeObserverStub;
}

const savedCanvas: Canvas = {
  owner_id: 'a', thread_id: 't1', id: 'c1', title: 'Concept map', schema_version: 1,
  revision: 1, origin: 'editor', created_at: '2026-11-24T00:00:00Z', updated_at: '2026-11-24T00:00:00Z',
  graph: { nodes: [], edges: [] },
};

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status,
    headers: { 'Content-Type': 'application/json' } }));
}

function stubBackend(handlers: {
  session?: number; put?: { status: number; body: Canvas } | null;
  getCanvas?: Canvas; capturePut?: (url: string, body: unknown) => void;
}) {
  browserClient.setConfig({ baseUrl: 'https://app.test' });
  /** The generated client passes Request objects; resolve their URL and method for routing. */
  const urlOf = (input: RequestInfo | URL) => (input instanceof Request ? input.url : String(input));
  const methodOf = (input: RequestInfo | URL, init?: RequestInit) =>
    input instanceof Request ? input.method : (init?.method ?? 'GET');
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = urlOf(input);
    const method = methodOf(input, init);
    const bodyText = typeof init?.body === 'string' ? init.body
      : input instanceof Request ? await input.text() : undefined;
    const putBody = () => bodyText ? JSON.parse(bodyText) as unknown : undefined;
    if (url.includes('/reader/session')) return jsonResponse({ owner_id: 'a' }, handlers.session ?? 200);
    if (method === 'PUT' && url.includes('/canvases/c1')) {
      handlers.capturePut?.(url, putBody());
      const put = handlers.put ?? { status: 200, body: savedCanvas };
      return jsonResponse(put.body, put.status);
    }
    if (url.includes('/canvases/c1')) {
      if (handlers.getCanvas) return jsonResponse(handlers.getCanvas);
      return jsonResponse(savedCanvas);
    }
    return jsonResponse({ detail: 'not found' }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function renderEditor() {
  return render(<CanvasEditor owner="a" threadId="t1" canvasId="c1" expired={vi.fn()} onClose={vi.fn()}/>);
}

it('adds a node from the outline and saves exactly once with the confirmed revision', async () => {
  const capturePut = vi.fn();
  const saved: Canvas = { ...savedCanvas, revision: 2, title: 'Concept map',
    graph: { nodes: [{ id: 'n-x', kind: 'problem', title: 'Crossing problem', description: '', x: 60, y: 60 }],
      edges: [] } };
  stubBackend({ capturePut, put: { status: 200, body: saved } });
  renderEditor();
  await screen.findByLabelText('Canvas title');
  fireEvent.change(screen.getByLabelText('Node type', { selector: '#canvas-node-kind' }),
    { target: { value: 'problem' } });
  fireEvent.change(screen.getByLabelText('Title', { selector: '#canvas-node-title' }),
    { target: { value: 'Crossing problem' } });
  fireEvent.click(screen.getByText('Add node'));
  expect(await screen.findByText(/save automatically as you write/)).toBeTruthy();
  expect(screen.getByLabelText('Title', { selector: '#canvas-node-title' }).closest('form')).toBeTruthy();
  // The outline lists the new node next to the visual map.
  expect(screen.getAllByText(/Crossing problem/).length).toBeGreaterThan(0);
  fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  await waitFor(() => expect(screen.getByText('All changes saved.')).toBeTruthy());
  expect(capturePut).toHaveBeenCalledTimes(1);
  const body = capturePut.mock.calls[0][1] as { revision: number; graph: { nodes: { title: string }[] } };
  expect(body.revision).toBe(1);
  expect(body.graph.nodes).toHaveLength(1);
  expect(body.graph.nodes[0].title).toBe('Crossing problem');
});

it('connects two nodes with a labeled relationship before saving', async () => {
  const open: Canvas = { ...savedCanvas, graph: { nodes: [
    { id: 'n1', kind: 'problem', title: 'Problem', description: '', x: 0, y: 0 },
    { id: 'n2', kind: 'stakeholder', title: 'Students', description: '', x: 100, y: 100 },
  ], edges: [] } };
  stubBackend({ getCanvas: open, put: { status: 200, body: open } });
  renderEditor();
  await screen.findByLabelText('From');
  fireEvent.change(screen.getByLabelText('From'), { target: { value: 'n1' } });
  fireEvent.change(screen.getByLabelText('Relationship', { selector: '#canvas-edge-relation' }),
    { target: { value: 'addresses' } });
  fireEvent.change(screen.getByLabelText('To'), { target: { value: 'n2' } });
  fireEvent.click(screen.getByText('Connect'));
  expect(await screen.findByText('Problem — addresses — Students')).toBeTruthy();
});

it('reports a stale save as a conflict without discarding the local edits', async () => {
  const capturePut = vi.fn();
  stubBackend({ capturePut, put: { status: 409, body: savedCanvas } });
  renderEditor();
  await screen.findByLabelText('Canvas title');
  fireEvent.change(screen.getByLabelText('Title', { selector: '#canvas-node-title' }),
    { target: { value: 'My node' } });
  fireEvent.click(screen.getByText('Add node'));
  await screen.findByText(/save automatically as you write/);
  fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  expect(await screen.findByText(/changed in another tab/)).toBeTruthy();
  // The losing draft is still shown in the outline instead of being discarded.
  expect(screen.getAllByText(/My node/).length).toBeGreaterThan(0);
});

it('duplicates a node, associates a Thinking Path stage and saves both exactly', async () => {
  const capturePut = vi.fn();
  const open: Canvas = { ...savedCanvas, graph: { nodes: [
    { id: 'n1', kind: 'problem', title: 'Crossing problem', description: '', stage: 'problem_identification', x: 0, y: 0 },
  ], edges: [] } };
  const saved: Canvas = { ...open, revision: 2 };
  stubBackend({ getCanvas: open, capturePut, put: { status: 200, body: saved } });
  renderEditor();
  const summary = await screen.findByText('Problem: Crossing problem');
  expect((screen.getByLabelText(/Thinking Path stage/, { selector: '#canvas-stage-n1' }) as HTMLSelectElement).value)
    .toBe('problem_identification');
  fireEvent.click(summary);
  fireEvent.click(await screen.findByRole('button', { name: 'Duplicate node' }));
  await waitFor(() => expect(document.querySelectorAll('[data-testid^="rf__node-"]')).toHaveLength(2));
  fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  await waitFor(() => expect(capturePut).toHaveBeenCalledTimes(1));
  const body = capturePut.mock.calls[0][1] as { graph: { nodes: { stage?: string }[] } };
  expect(body.graph.nodes).toHaveLength(2);
  expect(body.graph.nodes[0].stage).toBe('problem_identification');
  expect(body.graph.nodes[1].stage).toBe('problem_identification');
});

it('undoes a local removal and restores the node content before saving', async () => {
  const capturePut = vi.fn();
  const open: Canvas = { ...savedCanvas, graph: { nodes: [
    { id: 'n1', kind: 'concept', title: 'Bridge idea', description: 'long span', x: 0, y: 0 },
    { id: 'n2', kind: 'note', title: 'Other note', description: '', x: 100, y: 100 },
  ], edges: [] } };
  stubBackend({ getCanvas: open, capturePut, put: { status: 200, body: open } });
  renderEditor();
  fireEvent.click(await screen.findByText('Concept: Bridge idea'));
  // Both nodes have a remove action; pick the one inside the removed node's details.
  const removeButton = (await screen.findAllByRole('button', { name: 'Remove node and its connections' }))
    .find(button => button.closest('details')?.textContent?.includes('Bridge idea')) as HTMLButtonElement;
  fireEvent.click(removeButton);
  const nodeList = await screen.findByLabelText('Node list');
  await waitFor(() => expect(within(nodeList).getByText(/Other note/)).toBeTruthy());
  expect(within(nodeList).queryByText(/Bridge idea/)).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Undo last local edit' }));
  await waitFor(() => expect(within(nodeList).getByText(/Bridge idea/)).toBeTruthy());
  // The restored content is still shown; the autosave carries it like any other edit.
  expect(screen.getByText(/save automatically as you write/)).toBeTruthy();
});


it('previews a saved version from the history panel and restores it as a new revision', async () => {
  const capturePut = vi.fn();
  const open: Canvas = { ...savedCanvas, revision: 3, graph: { nodes: [
    { id: 'n0', kind: 'concept', title: 'v3 current', description: '', x: 0, y: 0 },
  ], edges: [] } };
  const restored: Canvas = { ...open, revision: 4, origin: 'restore',
    graph: { nodes: [{ id: 'n0', kind: 'note', title: 'v1 original', description: '', x: 0, y: 0 }], edges: [] } };
  const fetchMock = stubBackend({ getCanvas: open, capturePut, put: { status: 200, body: restored } });
  // Route the version endpoints beside the canvas GET/PUT.
  fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = input instanceof Request ? input.url : String(input);
    const method = input instanceof Request ? input.method : (init?.method ?? 'GET');
    if (url.includes('/reader/session')) return jsonResponse({ owner_id: 'a' });
    if (url.includes('/versions/1/restore')) {
      capturePut(url, JSON.parse(typeof init?.body === 'string' ? init.body : await (input as Request).text()));
      return jsonResponse(restored);
    }
    if (url.includes('/versions/1')) return jsonResponse({ owner_id: 'a', thread_id: 't1', canvas_id: 'c1',
      revision: 1, title: 'Map', graph: { nodes: [{ id: 'n0', kind: 'note', title: 'v1 original', description: '', x: 0, y: 0 }],
        edges: [] }, origin: 'editor', restored_from: null, created_at: '2026-11-24T00:00:00Z' });
    if (url.includes('/versions')) return jsonResponse({ owner_id: 'a', thread_id: 't1', canvas_id: 'c1',
      versions: [{ revision: 1, title: 'Map', origin: 'editor', restored_from: null,
        created_at: '2026-11-24T00:00:00Z' }] });
    if (method === 'PUT') {
      capturePut(url, JSON.parse(typeof init?.body === 'string' ? init.body : await (input as Request).text()));
      return jsonResponse(restored);
    }
    return jsonResponse(open);
  });
  renderEditor();
  await screen.findByLabelText('Node list');
  fireEvent.click(screen.getByRole('button', { name: 'History' }));
  fireEvent.click(await screen.findByRole('button', { name: /Version 1/ }));
  expect(await screen.findByText(/v1 original/)).toBeTruthy();
  expect(screen.getByText(/nothing changes until you restore/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Restore version 1' }));
  expect(await screen.findByText(/Restored version 1/)).toBeTruthy();
  const [restoreCall] = capturePut.mock.calls;
  expect(String(restoreCall?.[0])).toContain('/versions/1/restore');
  expect(restoreCall?.[1]).toEqual({ revision: 3 });
});

it('downloads the canvas export through the inert attachment endpoint', async () => {
  const open: Canvas = { ...savedCanvas, graph: { nodes: [
    { id: 'n1', kind: 'note', title: 'First', description: '', x: 0, y: 0 },
  ], edges: [] } };
  const exportCalls: string[] = [];
  const fetchMock = stubBackend({ getCanvas: open });
  fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = input instanceof Request ? input.url : String(input);
    const method = input instanceof Request ? input.method : (init?.method ?? 'GET');
    if (url.includes('/reader/session')) return jsonResponse({ owner_id: 'a' });
    if (url.includes('/export')) {
      exportCalls.push(`${method} ${url}`);
      return new Response('{"title":"Concept map"}', { status: 200,
        headers: { 'Content-Type': 'application/json' } });
    }
    return jsonResponse(open);
  });
  renderEditor();
  await screen.findByLabelText('Node list');
  fireEvent.click(screen.getByRole('button', { name: 'Export JSON' }));
  await waitFor(() => expect(screen.getByText(/Exported as json/)).toBeTruthy());
  const exportCall = fetchMock.mock.calls
    .map(([request]) => request as Request)
    .find(request => String(request).includes('/export'));
  expect(String(exportCall)).toContain('/export?format=json');
});

it('narrows the outline to the search match and offers locate', async () => {
  const open: Canvas = { ...savedCanvas, graph: { nodes: [
    { id: 'n1', kind: 'problem', title: 'Crossing problem', description: '', x: 0, y: 0 },
    { id: 'n2', kind: 'note', title: 'Unrelated', description: '', x: 100, y: 100 },
  ], edges: [] } };
  stubBackend({ getCanvas: open });
  renderEditor();
  const outline = await screen.findByLabelText('Node list');
  fireEvent.change(screen.getByLabelText('Search nodes'), { target: { value: 'crossing' } });
  await waitFor(() => expect(within(outline).getByText(/Crossing problem/)).toBeTruthy());
  expect(within(outline).queryByText(/Unrelated/)).toBeNull();
  expect(screen.getByRole('button', { name: /Locate/ })).toBeTruthy();
});

it('filters the outline and dims the map by node type', async () => {
  const open: Canvas = { ...savedCanvas, graph: { nodes: [
    { id: 'n1', kind: 'problem', title: 'Crossing problem', description: '', x: 0, y: 0 },
    { id: 'n2', kind: 'note', title: 'Unrelated', description: '', x: 100, y: 100 },
  ], edges: [] } };
  stubBackend({ getCanvas: open });
  renderEditor();
  const outline = await screen.findByLabelText('Node list');
  fireEvent.change(screen.getByLabelText('Type', { selector: '#canvas-kind-filter' }),
    { target: { value: 'problem' } });
  await waitFor(() => expect(within(outline).getByText(/Crossing problem/)).toBeTruthy());
  expect(within(outline).queryByText(/Unrelated/)).toBeNull();
});

it('exposes stale artifact linkage and updates the node only on explicit request', async () => {
  const capturePut = vi.fn();
  browserClient.setConfig({ baseUrl: 'https://app.test' });
  const open: Canvas = { ...savedCanvas, graph: { nodes: [
    { id: 'n1', kind: 'problem', title: 'Crossing problem', description: 'old saved note', x: 0, y: 0,
      references: [{ kind: 'artifact', id: 'art1', revision: 2 }] },
  ], edges: [] } };
  const artifactSummary = { id: 'art1', thread_id: 't1', title: 'Field notes', kind: 'notes',
    schema_version: 1, revision: 5, origin: 'editor', created_at: '', updated_at: '' };
  const fullArtifact = { ...artifactSummary, owner_id: 'a',
    document: { type: 'doc', content: [
      { type: 'paragraph', content: [{ type: 'text', text: 'Revised crossing findings.' }] }] },
    references: [] };
  const urlOf = (input: RequestInfo | URL) => (input instanceof Request ? input.url : String(input));
  const methodOf = (input: RequestInfo | URL, init?: RequestInit) =>
    input instanceof Request ? input.method : (init?.method ?? 'GET');
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = urlOf(input);
    const method = methodOf(input, init);
    if (url.includes('/reader/session')) return jsonResponse({ owner_id: 'a' });
    if (method === 'PUT' && url.includes('/canvases/c1')) {
      const bodyText = typeof init?.body === 'string' ? init.body : await (input as Request).text();
      capturePut(JSON.parse(bodyText));
      return jsonResponse({ ...open, revision: 2 });
    }
    if (url.endsWith('/canvases/c1')) return jsonResponse(open);
    if (url.endsWith('/artifacts')) return jsonResponse({ owner_id: 'a', thread_id: 't1',
      kinds: [], artifacts: [artifactSummary] });
    if (url.includes('/artifacts/art1')) return jsonResponse(fullArtifact);
    return jsonResponse({ detail: 'not found' }, 404);
  }));
  renderEditor();
  const summary = await screen.findByText('Problem: Crossing problem');
  fireEvent.click(summary);
  // The link states the artifact moved on instead of silently staying silent.
  expect(await screen.findByText(/saved version 2/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Update from artifact' }));
  // The refreshed text lands in the editable outline for review before any save.
  expect(await (async () => {
    const description = await screen.findByLabelText('Description', { selector: '#canvas-description-n1' }) as HTMLInputElement;
    await waitFor(() => expect(description.value).toBe('Revised crossing findings.'));
  })());
  fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  await waitFor(() => expect(capturePut).toHaveBeenCalledTimes(1));
  const body = capturePut.mock.calls[0][0] as { graph: { nodes: {
    description: string; references: { kind: string; id: string; revision?: number }[] }[] } };
  expect(body.graph.nodes[0].description).toBe('Revised crossing findings.');
  expect(body.graph.nodes[0].references).toEqual([{ kind: 'artifact', id: 'art1', revision: 5 }]);
});
