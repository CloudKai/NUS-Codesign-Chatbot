/**
 * @vitest-environment jsdom
 */
/** The pending/queued state is wordless progress: bouncing dots only, and the workspace stays unlocked. */
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { useState } from 'react';
import { Conversation } from './Conversation';
import { WorkspaceLayoutContext, useWorkspaceLayout } from './workspaceLayout';
import { createReaderQueryClient } from './api/queryClient';
import { browserClient } from './api/client';
import type { Page, Project } from './api';

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status,
    headers: { 'Content-Type': 'application/json' } }));
}

const notebook = { id: 't1', kind: 'chat' as const, name: 'Recovery chat', parent_notebook_id: null, pinned: false };
const page: Page = { owner_id: 'a', notebook, messages: [], next_cursor: null, total_count: 0, conversation_revision: 1 };
const project: Project = { owner_id: 'a', thread_id: 't1', current_stage: 'framing', stages: [], pending: null };
const session = { owner_id: 'a', kind: 'registered', display_name: 'Student' };
const bookmarks = { owner_id: 'a', thread_id: 't1', conversation_revision: 1, messages: [] };
const savedTurn = { response_text: 'Saved reply.', assessment: { response_mode: 'lecture', citations: [] } };

const done = { event: 'done', turn: savedTurn };

function ndjson(events: unknown[]) {
  const bytes = new TextEncoder().encode(events.map(event => JSON.stringify(event)).join('\n'));
  return new Response(new ReadableStream({ start(controller) {
    controller.enqueue(bytes);
    controller.close();
  } }), { headers: { 'Content-Type': 'application/x-ndjson' } });
}

function LayoutHost({ children }: { children: React.ReactNode }) {
  const layout = useWorkspaceLayout();
  const [queryClient] = useState(createReaderQueryClient);
  return <QueryClientProvider client={queryClient}>
    <WorkspaceLayoutContext.Provider value={layout}>{children}</WorkspaceLayoutContext.Provider>
  </QueryClientProvider>;
}

function mountConversation({ activity = () => {}, saved = savedTurn as unknown, gate = false, gateStream = false, refresh = async () => {}, seedPending = true, failCheck = false }:
  { activity?: (value: boolean) => void; saved?: unknown; gate?: boolean; gateStream?: boolean; refresh?: () => Promise<void>; seedPending?: boolean; failCheck?: boolean } = {}) {
  browserClient.setConfig({ baseUrl: 'https://app.test' });
  let releaseCheck: (() => void) | undefined;
  const gatePromise = new Promise<void>(resolve => { releaseCheck = resolve; });
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof Request ? input.url : String(input);
    if (url.includes('/reader/session')) return jsonResponse(session);
    if (url.includes('/coach-turn')) return (gate ? gatePromise : Promise.resolve()).then(() => failCheck
      ? jsonResponse({ detail: 'Offline' }, 503) : jsonResponse(saved));
    if (url.includes('/bookmarks')) return jsonResponse(bookmarks);
    if (init?.method === 'POST' && url.includes('/stream')) {
      const body = JSON.parse(String(init.body)) as { idempotency_key: string };
      const acknowledged = { event: 'started', thread_id: 't1', idempotency_key: body.idempotency_key, stage: 'framing' };
      if (!gateStream) return Promise.resolve(ndjson([acknowledged, done]));
      const bytes = new TextEncoder();
      const events = [acknowledged, done];
      return Promise.resolve(new Response(new ReadableStream({
        async start(controller) {
          controller.enqueue(bytes.encode(JSON.stringify(acknowledged)));
          await gatePromise;
          controller.enqueue(bytes.encode(JSON.stringify(events[1])));
          controller.close();
        },
      }), { headers: { 'Content-Type': 'application/x-ndjson' } }));
    }
    return jsonResponse({ detail: 'unexpected request' }, 500);
  });
  vi.stubGlobal('fetch', fetchMock);
  // A receipt restored from tab storage: a question is queued and unresolved.
  if (seedPending) {
    sessionStorage.setItem('codesign-lecture:a:t1',
      JSON.stringify({ text: 'Queued question', intent: 'lecture', attachments: [], pending: { key: 'k1', text: 'Queued question' } }));
  }
  render(<LayoutHost><Conversation page={page} project={project} owner="a" refresh={refresh} expired={() => {}}
    onHelp={() => {}} preferredIntent="improve" showStarters={false} externalBlocked={false}
    activity={activity} locateMessage={async () => true} busy={false} loadEarlier={async () => {}}
    onCanvasSelectionConsumed={() => {}} onArtifactSelectionConsumed={() => {}}/></LayoutHost>);
  return { fetchMock, release: () => releaseCheck!(), restoreConnection: () => { failCheck = false; } };
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); sessionStorage.clear(); });

if (!('ResizeObserver' in globalThis)) {
  class ResizeObserverStub { observe() {} unobserve() {} disconnect() {} }
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = ResizeObserverStub;
}

it('a pending receipt shows only bouncing dots — no words, no buttons — then frees the composer', async () => {
  const { fetchMock, release } = mountConversation({ gate: true, saved: null });
  await waitFor(() => expect(fetchMock.mock.calls.some(([request]) => String(request).includes('/coach-turn'))).toBe(true));
  // While the check runs: dots only.
  expect(document.querySelector('.recovery-actions .typing-dots')).not.toBeNull();
  expect(screen.queryByText(/Pending question/)).toBeNull();
  expect(screen.queryByRole('button', { name: /retry/i })).toBeNull();
  expect(screen.queryByRole('button', { name: /check saved answer/i })).toBeNull();
  expect(screen.queryByRole('button', { name: /discard/i })).toBeNull();
  expect(document.querySelector('.turn-status')?.textContent).toBe('');
  // The check finds nothing saved: the composer is freed without any control.
  release();
  await waitFor(() => expect(document.querySelector('.recovery-actions')).toBeNull());
  expect((screen.getByPlaceholderText(/Share your design/) as HTMLTextAreaElement).value).toBe('Queued question');
});

it('a failed recovery read is visible and can be retried without resending', async () => {
  const refresh = vi.fn(async () => {});
  const { fetchMock, restoreConnection } = mountConversation({ failCheck: true, refresh });
  await waitFor(() => expect(screen.getByRole('status', { name: 'Checking your answer' }).textContent)
    .toContain('couldn’t check'));
  const receipt = JSON.parse(sessionStorage.getItem('codesign-mode:a:t1') ?? 'null');
  expect(receipt.pending.key).toBe('k1');
  restoreConnection();
  fireEvent.click(screen.getByRole('button', { name: 'Check saved answer' }));
  await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
  expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0);
  expect(JSON.parse(sessionStorage.getItem('codesign-mode:a:t1') ?? 'null').pending).toBeNull();
});

it('a queued turn shows dots without words and never locks the workspace', async () => {
  const refresh = vi.fn(async () => {});
  const activity = vi.fn();
  const { fetchMock, release } = mountConversation({ activity, refresh, gateStream: true, seedPending: false });
  const composer = screen.getByPlaceholderText(/Share your design/);
  fireEvent.change(composer, { target: { value: 'Why do crossings fail here?' } });
  fireEvent.submit(composer.closest('form')!);
  await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) =>
    init?.method === 'POST' && String(init.body ?? '').includes('crossings')).valueOf()).toBe(true));
  // In progress: dots, no words, and the workspace lock stays off.
  expect(document.querySelector('.typing-dots')).not.toBeNull();
  // No progress element below the composer at all.
  expect(document.querySelector('.chat-progress')).toBeNull();
  expect(document.querySelector('.turn-status')?.textContent).toBe('');
  expect(activity.mock.calls.every(([value]) => value === false)).toBe(true);
  release();
  // The saved check adopts the reply through the parent refresh; still no lock.
  await waitFor(() => expect(refresh).toHaveBeenCalled());
  expect(activity.mock.calls.every(([value]) => value === false)).toBe(true);
});

it('migrates an older mode draft and restores the pending receipt before sending again', async () => {
  const { release } = mountConversation({ gate: true, saved: null });
  await waitFor(() => {
    const migrated = JSON.parse(sessionStorage.getItem('codesign-mode:a:t1') ?? 'null');
    expect(migrated?.intent).toBe('improve');
    expect(migrated?.pending?.key).toBe('k1');
    expect(migrated?.pending?.legacyLectureRoute).toBe(true);
  });
  expect(sessionStorage.getItem('codesign-lecture:a:t1')).toBeNull();
  release();
  await waitFor(() => expect(screen.getByPlaceholderText(/Share your design/)).toBeTruthy());
});
