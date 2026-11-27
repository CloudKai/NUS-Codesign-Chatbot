/**
 * @vitest-environment jsdom
 */
/**
 * Long-content render-cost measurement harness (ticket 43). Opt-in: run with
 * `PERF_MEASURE=1 npx vitest run src/renderPerf.test.tsx`; under the ordinary
 * `npm test` run every case is skipped so CI timing never gates a pass.
 *
 * Measures component mount cost for representative long content in jsdom:
 * the routed conversation with a bounded long history, the design canvas with a
 * 60-node/80-edge graph and the document editor with a 60-paragraph document.
 * Each case reports the median wall time of five mount/unmount trials plus the
 * number of DOM nodes mounted. jsdom has no layout, so these numbers capture
 * React/prosemirror/react-flow work, not browser paint; they are recorded as
 * offline harness evidence alongside the real-browser route-load numbers from
 * tests/browser/route_load.spec.ts.
 */
declare const process: { env: Record<string, string | undefined> };
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { useState } from 'react';
import { Conversation } from './Conversation';
import { CanvasEditor } from './CanvasEditor';
import { ArtifactEditor } from './ArtifactEditor';
import { WorkspaceLayoutContext, useWorkspaceLayout } from './workspaceLayout';
import { createReaderQueryClient } from './api/queryClient';
import { browserClient } from './api/client';
import type { Artifact, Canvas, Message, Page, Project, Stage } from './api';

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status,
    headers: { 'Content-Type': 'application/json' } }));
}

const notebook = {
  id: 't1', kind: 'chat' as const, name: 'Perf chat', parent_notebook_id: null,
  pinned: false, created_at: '2026-11-25T00:00:00Z', updated_at: '2026-11-25T00:00:00Z',
};

const stage: Stage = {
  id: 'problem_identification', label: 'Problem identification', completed: true, selectable: true,
  artifact_label: 'Working problem statement', student_work: [], feedback: [], coach_summary: '',
  decision: 'confirmed', next_action: 'Keep going', criteria: ['Describe affected people'],
};

const project: Project = {
  owner_id: 'a', thread_id: 't1', current_stage: 'problem_identification', stages: [stage],
  pending: null,
};

function message(index: number): Message {
  return {
    id: `m-${index}`, role: index % 2 === 0 ? 'user' : 'assistant',
    content: `Turn ${index}: ${'Students need safer crossings near the market because older residents '
      + 'wait a long time for the lights to change, and delivery riders use the same space at speed. '.repeat(3)}`,
    citations: [], starred: false, feedback_available: false, rating: null,
  };
}

function longPage(count: number): Page {
  return { owner_id: 'a', notebook, messages: Array.from({ length: count }, (_, index) => message(index)),
    next_cursor: null, total_count: count, conversation_revision: count };
}

function longCanvas(nodes: number, edgesPerNode: number): Canvas {
  const graphNodes = Array.from({ length: nodes }, (_, index) => ({
    id: `n-${index}`, kind: 'problem' as const, title: `Node ${index} crossing concern`,
    description: 'Older residents wait too long for the lights to change near the market.',
    x: (index % 10) * 120, y: Math.floor(index / 10) * 120, stage_id: null,
  }));
  const graphEdges = Array.from({ length: nodes * edgesPerNode }, (_, index) => ({
    id: `e-${index}`, source: `n-${index % nodes}`, target: `n-${(index + 1) % nodes}`,
    relation: 'supports' as const, explanation: '',
  }));
  return { owner_id: 'a', thread_id: 't1', id: 'c1', title: 'Concept map', schema_version: 1,
    revision: 1, origin: 'editor', created_at: '2026-11-25T00:00:00Z', updated_at: '2026-11-25T00:00:00Z',
    graph: { nodes: graphNodes, edges: graphEdges } };
}

function longArtifact(paragraphs: number): Artifact {
  return { owner_id: 'a', thread_id: 't1', id: 'a1', title: 'Field notes', kind: 'notes',
    schema_version: 1, revision: 1, origin: 'editor',
    created_at: '2026-11-25T00:00:00Z', updated_at: '2026-11-25T00:00:00Z', references: [],
    document: { type: 'doc', content: Array.from({ length: paragraphs }, (_, index) => ({
      type: 'paragraph', content: [{ type: 'text', text: `Paragraph ${index}: ${'Observation '
        + 'of the crossing behaviour at the market entrance during the morning peak. '.repeat(2)}` }] })) } };
}

/** Provide the shared layout and reader query client through the real hooks, as main.tsx and App do. */
function LayoutHost({ children }: { children: React.ReactNode }) {
  const layout = useWorkspaceLayout();
  const [queryClient] = useState(createReaderQueryClient);
  return <QueryClientProvider client={queryClient}>
    <WorkspaceLayoutContext.Provider value={layout}>{children}</WorkspaceLayoutContext.Provider>
  </QueryClientProvider>;
}

/** Median of five mount/ready/unmount trials plus the DOM nodes the loaded tree left behind. */
async function measureMount(name: string, element: React.ReactElement, ready: () => Promise<unknown>) {
  const times: number[] = [];
  let nodes = 0;
  for (let trial = 0; trial < 5; trial += 1) {
    const start = performance.now();
    const view = render(element);
    await ready();
    times.push(performance.now() - start);
    nodes = document.querySelectorAll('*').length;
    view.unmount();
  }
  times.sort((a, b) => a - b);
  console.log(`render-perf ${JSON.stringify({ component: name, median_ms: Math.round(times[2] * 100) / 100,
    min_ms: Math.round(times[0] * 100) / 100, max_ms: Math.round(times[4] * 100) / 100, dom_nodes: nodes })}`);
  return times[2];
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); sessionStorage.clear(); });

if (!('ResizeObserver' in globalThis)) {
  class ResizeObserverStub { observe() {} unobserve() {} disconnect() {} }
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = ResizeObserverStub;
}

describe.skipIf(process.env.PERF_MEASURE !== '1')('long-content render cost (offline jsdom harness)', () => {
  it('mounts a bounded long chat history', async () => {
    const median = await measureMount('conversation-80-messages', <LayoutHost><Conversation
      page={longPage(80)} project={project} owner="a" refresh={async () => {}} expired={() => {}}
      onHelp={() => {}} preferredIntent="improve" showStarters={false} externalBlocked={false}
      activity={() => {}} locateMessage={async () => true} busy={false} loadEarlier={async () => {}}
      onCanvasSelectionConsumed={() => {}} onArtifactSelectionConsumed={() => {}}/></LayoutHost>,
      () => screen.findAllByText(/safer crossings near the market/));
    expect(median).toBeGreaterThan(0);
  });

  it('mounts a 60-node design canvas', async () => {
    const canvas = longCanvas(60, 1);
    browserClient.setConfig({ baseUrl: 'https://app.test' });
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = input instanceof Request ? input.url : String(input);
      if (url.includes('/reader/session')) return jsonResponse({ owner_id: 'a' });
      return jsonResponse(canvas);
    }));
    if (!('ResizeObserver' in globalThis)) {
      class ResizeObserverStub { observe() {} unobserve() {} disconnect() {} }
      (globalThis as { ResizeObserver?: unknown }).ResizeObserver = ResizeObserverStub;
    }
    const median = await measureMount('canvas-60-nodes',
      <CanvasEditor owner="a" threadId="t1" canvasId="c1" expired={() => {}} onClose={() => {}}/>,
      () => screen.findAllByText(/Node 59 crossing concern/));
    expect(median).toBeGreaterThan(0);
  });

  it('mounts a 60-paragraph document', async () => {
    const artifact = longArtifact(60);
    browserClient.setConfig({ baseUrl: 'https://app.test' });
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = input instanceof Request ? input.url : String(input);
      if (url.includes('/reader/session')) return jsonResponse({ owner_id: 'a' });
      return jsonResponse(artifact);
    }));
    const median = await measureMount('artifact-60-paragraphs',
      <ArtifactEditor owner="a" threadId="t1" artifactId="a1" expired={() => {}} onClose={() => {}}/>,
      () => screen.findAllByText(/Paragraph 59:/));
    expect(median).toBeGreaterThan(0);
  });
});
