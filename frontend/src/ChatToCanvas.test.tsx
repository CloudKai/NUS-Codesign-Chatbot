/**
 * @vitest-environment jsdom
 */
/** The chat-to-canvas proposal edits freely and saves only on confirmation, keeping the message reference. */
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ChatToCanvasProposal } from './ChatToCanvas';
import { browserClient } from './api/client';
import type { Canvas } from './api';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

const savedCanvas: Canvas = {
  owner_id: 'a', thread_id: 'nb1', id: 'c1', title: 'Concept map', schema_version: 1,
  revision: 1, origin: 'editor', created_at: '', updated_at: '',
  graph: { nodes: [], edges: [] },
};

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status,
    headers: { 'Content-Type': 'application/json' } }));
}

function stubBackend(handlers: { put?: { status: number; body: Canvas };
  capturePut?: (url: string, body: unknown) => void }) {
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
    if (method === 'PUT' && url.includes('/canvases/c1')) {
      handlers.capturePut?.(url, bodyText ? JSON.parse(bodyText) as unknown : undefined);
      return jsonResponse(handlers.put?.body ?? savedCanvas, handlers.put?.status ?? 200);
    }
    if (url.includes('/canvases/c1')) return jsonResponse(savedCanvas);
    if (url.includes('/canvases')) return jsonResponse({ owner_id: 'a', thread_id: 'nb1',
      node_kinds: ['note'], relations: ['supports'], stages: [], canvases: [
        { id: 'c1', title: 'Concept map', thread_id: 'nb1', schema_version: 1, revision: 1,
          origin: 'editor', created_at: '', updated_at: [] as unknown as string }] });
    return jsonResponse({ detail: 'not found' }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function renderProposal(onCreated = vi.fn(), onClose = vi.fn()) {
  return render(<ChatToCanvasProposal threadId="nb1" messageId="msg-9"
    content="The crossing feels unsafe after dark" onClose={onClose} onCreated={onCreated}/>);
}

it('confirms an edited node onto the chosen canvas with the message reference', async () => {
  const capturePut = vi.fn();
  const saved: Canvas = { ...savedCanvas, revision: 2, graph: { nodes: [
    { id: 'n-new', kind: 'problem', title: 'The crossing feels unsafe after dark',
      description: 'The crossing feels unsafe after dark', x: 60, y: 60,
      references: [{ kind: 'message', id: 'msg-9' }] }], edges: [] } };
  stubBackend({ capturePut, put: { status: 200, body: saved } });
  const onCreated = vi.fn();
  renderProposal(onCreated);
  expect(await screen.findByText('The crossing feels unsafe after dark')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Node type'), { target: { value: 'problem' } });
  fireEvent.click(screen.getByRole('button', { name: 'Add node' }));
  await waitFor(() => expect(onCreated).toHaveBeenCalledWith('c1'));
  expect(capturePut).toHaveBeenCalledTimes(1);
  const body = capturePut.mock.calls[0][1] as { revision: number;
    graph: { nodes: { kind: string; references: { kind: string; id: string }[] }[] } };
  expect(body.revision).toBe(1); // The proposal re-read the canvas and saved over the fresh revision.
  expect(body.graph.nodes[0].kind).toBe('problem');
  expect(body.graph.nodes[0].references).toEqual([{ kind: 'message', id: 'msg-9' }]);
});

it('saves nothing on cancel and reports a stale canvas without losing the proposal', async () => {
  const capturePut = vi.fn();
  const onCreated = vi.fn();
  const onClose = vi.fn();
  stubBackend({ capturePut, put: { status: 409, body: savedCanvas } });
  renderProposal(onCreated, onClose);
  await screen.findByText('Choose a canvas…');
  fireEvent.change(await screen.findByLabelText('Destination canvas'), { target: { value: 'c1' } });
  fireEvent.click(screen.getByRole('button', { name: 'Add node' }));
  expect(await screen.findByText(/canvas just changed/)).toBeTruthy();
  expect(onCreated).not.toHaveBeenCalled();
  // Cancel closes the proposal; no second write happened.
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(onClose).toHaveBeenCalled();
  expect(capturePut).toHaveBeenCalledTimes(1);
});
