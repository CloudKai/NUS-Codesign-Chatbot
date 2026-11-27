/**
 * @vitest-environment jsdom
 */
/** Artifact-to-canvas: create an editable node or link an existing one, keeping artifact/revision origin. */
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ArtifactToCanvasDialog } from './ArtifactToCanvasDialog';
import { browserClient } from './api/client';
import type { Artifact, Canvas } from './api';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

const artifact: Artifact = {
  owner_id: 'a', thread_id: 't1', id: 'art1', title: 'Field notes', kind: 'notes',
  document: { type: 'doc', content: [
    { type: 'paragraph', content: [{ type: 'text', text: 'Students cross the road unsafely at peak hours.' }] },
    { type: 'paragraph', content: [{ type: 'text', text: 'Stakeholders asked for a safer signal timing.' }] },
  ] },
  schema_version: 1, revision: 4, origin: 'editor',
  created_at: '2026-11-25T00:00:00Z', updated_at: '2026-11-25T00:00:00Z', references: [],
};

const canvas: Canvas = {
  owner_id: 'a', thread_id: 't1', id: 'c1', title: 'Concept map', schema_version: 1,
  revision: 6, origin: 'editor', created_at: '', updated_at: '',
  graph: { nodes: [
    { id: 'n0', kind: 'problem', title: 'Unsafe crossing', description: 'existing note', x: 0, y: 0,
      references: [{ kind: 'message', id: 'm-1' }] },
  ], edges: [] },
};

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status,
    headers: { 'Content-Type': 'application/json' } }));
}

function stubBackend(handlers?: { canvas?: Canvas; capturePut?: (body: unknown) => void;
  canvases?: { id: string; title: string }[]; readCanvas?: () => Canvas }) {
  browserClient.setConfig({ baseUrl: 'https://app.test' });
  const urlOf = (input: RequestInfo | URL) => (input instanceof Request ? input.url : String(input));
  const methodOf = (input: RequestInfo | URL, init?: RequestInit) =>
    input instanceof Request ? input.method : (init?.method ?? 'GET');
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = urlOf(input);
    if (methodOf(input, init) === 'PUT' && url.includes('/canvases/c1')) {
      const bodyText = typeof init?.body === 'string' ? init.body
        : input instanceof Request ? await input.text() : undefined;
      handlers?.capturePut?.(bodyText ? JSON.parse(bodyText) as unknown : undefined);
      return jsonResponse(handlers?.canvas ?? canvas);
    }
    if (url.endsWith('/canvases')) {
      return jsonResponse({ owner_id: 'a', thread_id: 't1', node_kinds: [], relations: [],
        stages: [], canvases: handlers?.canvases ?? [{ ...canvas, graph: undefined }] });
    }
    if (url.includes('/canvases/c1')) return jsonResponse(handlers?.readCanvas?.() ?? handlers?.canvas ?? canvas);
    if (url.includes('/reader/session')) return jsonResponse({ owner_id: 'a' });
    return jsonResponse({ detail: 'not found' }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

it('creates an editable node from the saved paragraph with artifact/revision provenance', async () => {
  const capturePut = vi.fn();
  stubBackend({ capturePut });
  const onOpenCanvas = vi.fn();
  render(<ArtifactToCanvasDialog threadId="t1" artifact={artifact} initialParagraph={0}
    onClose={() => {}} onOpenCanvas={onOpenCanvas}/>);
  fireEvent.click(await screen.findByRole('button', { name: 'Propose a new node' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Create new node' }));
  await waitFor(() => expect(capturePut).toHaveBeenCalledTimes(1));
  const body = capturePut.mock.calls[0][0] as {
    revision: number; graph: { nodes: { references?: { kind: string; id: string; revision?: number }[];
      description: string }[] } };
  const node = body.graph.nodes.at(-1);
  expect(node?.references).toEqual([{ kind: 'artifact', id: 'art1', revision: 4 }]);
  expect(node?.description).toContain('Students cross the road unsafely at peak hours.');
  expect(body.revision).toBe(6);
  expect(onOpenCanvas).toHaveBeenCalledWith('c1');
});

it('links an existing node without changing its other fields', async () => {
  const capturePut = vi.fn();
  stubBackend({ capturePut });
  render(<ArtifactToCanvasDialog threadId="t1" artifact={artifact} initialParagraph={null}
    onClose={() => {}} onOpenCanvas={() => {}}/>);
  const picker = await screen.findByLabelText('Link an existing node instead');
  // The node list appears once the chosen canvas's graph loads.
  await screen.findByRole('option', { name: /Unsafe crossing/ });
  fireEvent.change(picker, { target: { value: 'n0' } });
  fireEvent.click(screen.getByRole('button', { name: 'Link to this node' }));
  await waitFor(() => expect(capturePut).toHaveBeenCalledTimes(1));
  const body = capturePut.mock.calls[0][0] as {
    graph: { nodes: { id: string; title: string; description: string;
      references?: { kind: string; id: string; revision?: number }[] }[] } };
  expect(body.graph.nodes).toHaveLength(1);
  const node = body.graph.nodes[0];
  expect(node.id).toBe('n0');
  expect(node.title).toBe('Unsafe crossing');
  expect(node.description).toBe('existing note');
  expect(node.references).toEqual([
    { kind: 'message', id: 'm-1' },
    { kind: 'artifact', id: 'art1', revision: 4 },
  ]);
});

it('states truthfully that there is no canvas yet and saves nothing', async () => {
  const capturePut = vi.fn();
  stubBackend({ capturePut, canvases: [] });
  render(<ArtifactToCanvasDialog threadId="t1" artifact={artifact} initialParagraph={null}
    onClose={() => {}} onOpenCanvas={() => {}}/>);
  expect(await screen.findByText(/No canvases yet/)).toBeTruthy();
  expect(capturePut).not.toHaveBeenCalled();
});

it('links to the latest saved node without replacing changes made after opening the dialog', async () => {
  let current = canvas;
  const saved: Canvas[] = [];
  stubBackend({
    readCanvas: () => current,
    capturePut: body => {
      const payload = body as { revision: number; graph: Canvas['graph'] };
      expect(payload.revision).toBe(7);
      saved.push({ ...current, graph: payload.graph });
    },
  });
  render(<ArtifactToCanvasDialog threadId="t1" artifact={artifact} initialParagraph={null}
    onClose={() => {}}/>);
  await screen.findByRole('option', { name: /Unsafe crossing/ });
  fireEvent.change(screen.getByLabelText('Link an existing node instead'), { target: { value: 'n0' } });
  current = { ...canvas, revision: 7, graph: {
    ...canvas.graph,
    nodes: [{ ...canvas.graph.nodes[0], title: 'Updated crossing', description: 'New observations' },
      { id: 'n1', kind: 'note', title: 'Another tab added this', description: '', x: 30, y: 40 }],
  } };
  fireEvent.click(screen.getByRole('button', { name: 'Link to this node' }));
  await waitFor(() => expect(saved[0]?.graph.nodes).toHaveLength(2));
  expect(saved[0].graph.nodes[0].title).toBe('Updated crossing');
  expect(saved[0].graph.nodes[0].description).toBe('New observations');
  expect(saved[0].graph.nodes[0].references).toContainEqual({ kind: 'artifact', id: 'art1', revision: 4 });
});
