/**
 * @vitest-environment jsdom
 */
/** Wordless pending recovery at the lifecycle level: a check that finds no saved
 * reply frees the composer automatically, so no recovery buttons are needed.
 */
import { afterEach, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { useChatLifecycle, type Receipt } from './chatLifecycle';
import { browserClient } from './api/client';

const session = { owner_id: 'a', kind: 'registered', display_name: 'Student' };
const savedTurn = { response_text: 'Saved reply.', assessment: { response_mode: 'lecture', citations: [] } };
const started = { event: 'started', thread_id: 't1', idempotency_key: 'k1', stage: 'framing' };
const done = { event: 'done', turn: savedTurn };

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status,
    headers: { 'Content-Type': 'application/json' } }));
}

function ndjson(events: unknown[]) {
  const bytes = new TextEncoder().encode(events.map(event => JSON.stringify(event)).join('\n'));
  return Promise.resolve(new Response(new ReadableStream({ start(controller) {
    controller.enqueue(bytes);
    controller.close();
  } }), { headers: { 'Content-Type': 'application/x-ndjson' } }));
}

function mountLifecycle(initialPending: Receipt | null, options: { saved?: unknown; failCheck?: boolean; draftText?: string } = {}) {
  browserClient.setConfig({ baseUrl: 'https://app.test' });
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof Request ? input.url : String(input);
    if (url.includes('/reader/session')) return jsonResponse(session);
    if (url.includes('/coach-turn')) return options.failCheck ? jsonResponse({ detail: 'down' }, 500) : jsonResponse(options.saved ?? null);
    if (init?.method === 'POST' && url.includes('/stream')) return ndjson([started, done]);
    return jsonResponse({ detail: 'unexpected request' }, 500);
  });
  vi.stubGlobal('fetch', fetchMock);
  const text = { current: options.draftText ?? 'Queued question' };
  const intent = { current: 'improve' as const };
  const remember = vi.fn((nextText: string) => { text.current = nextText; });
  const refresh = vi.fn(async () => {});
  const hook = renderHook(() => useChatLifecycle({
    threadId: 't1', owner: 'a', expired: () => {}, refresh,
    composer: { current: null }, busy: false, moving: false, externalBlocked: false,
    feedbackBusy: false, projectUncertain: false, stickToLatest: { current: true },
    draft: { text, intent, attachments: [], remember }, initialPending,
  }));
  return { ...hook, fetchMock, text, remember, refresh };
}

afterEach(() => vi.unstubAllGlobals());

it('a check that finds no saved reply frees the composer automatically', async () => {
  const view = mountLifecycle({ key: 'k1', text: 'Queued question' });
  await waitFor(() => expect(view.remember).toHaveBeenLastCalledWith('Queued question', null));
  expect(view.text.current).toBe('Queued question');
});

it('an unsaved question survives recovery alongside a newer composer draft', async () => {
  const view = mountLifecycle({ key: 'k1', text: 'Queued question' }, { draftText: 'Follow-up draft' });
  await waitFor(() => expect(view.remember).toHaveBeenLastCalledWith('Follow-up draft\n\nQueued question', null));
  expect(view.text.current).toContain('Follow-up draft');
  expect(view.text.current).toContain('Queued question');
  expect(view.fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0);
});

it('a saved reply is adopted, clears the receipt and clears the composer', async () => {
  const view = mountLifecycle({ key: 'k1', text: 'Queued question' }, { saved: savedTurn });
  await waitFor(() => expect(view.refresh).toHaveBeenCalled());
  expect(view.remember).toHaveBeenLastCalledWith('', null, []);
  expect(view.text.current).toBe('');
});

it('a failed check keeps the question pending so progress can continue', async () => {
  const view = mountLifecycle({ key: 'k1', text: 'Queued question' }, { failCheck: true });
  await waitFor(() => expect(view.fetchMock.mock.calls.some(([request]) =>
    String(request).includes('/coach-turn')).valueOf()).toBe(true));
  expect(view.result.current.pending?.key).toBe('k1');
  expect(view.fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0);
});

it('a terminal failure announces the outcome and returns the text to the composer', async () => {
  browserClient.setConfig({ baseUrl: 'https://app.test' });
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof Request ? input.url : String(input);
    if (url.includes('/reader/session')) return jsonResponse(session);
    if (url.includes('/coach-turn')) return jsonResponse(null);
    if (init?.method === 'POST' && url.includes('/stream')) {
      const body = JSON.parse(String(init.body)) as { idempotency_key: string };
      const acknowledged = { event: 'started', thread_id: 't1', idempotency_key: body.idempotency_key, stage: 'framing' };
      return ndjson([acknowledged, { event: 'error', status: 503, detail: 'Provider unavailable', category: 'unavailable' }]);
    }
    return jsonResponse({ detail: 'unexpected request' }, 500);
  });
  vi.stubGlobal('fetch', fetchMock);
  const text = { current: 'Why does this fail?' };
  const intent = { current: 'improve' as const };
  const remember = vi.fn((nextText: string) => { text.current = nextText; });
  const hook = renderHook(() => useChatLifecycle({
    threadId: 't1', owner: 'a', expired: () => {}, refresh: async () => {},
    composer: { current: null }, busy: false, moving: false, externalBlocked: false,
    feedbackBusy: false, projectUncertain: false, stickToLatest: { current: true },
    draft: { text, intent, attachments: [], remember }, initialPending: null,
  }));
  await hook.result.current.send();
  await waitFor(() => expect(remember).toHaveBeenLastCalledWith('Why does this fail?', null));
  await waitFor(() => expect(hook.result.current.status).toContain('coach'));
  expect(hook.result.current.pending).toBeNull();
});

it('a new send stays blocked while a receipt is unresolved', async () => {
  const view = mountLifecycle({ key: 'k1', text: 'Queued question' }, { failCheck: true });
  await waitFor(() => expect(view.result.current.pending?.key).toBe('k1'));
  view.text.current = 'Another question';
  await view.result.current.send();
  expect(view.fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0);
});
