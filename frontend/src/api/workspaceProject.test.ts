/** Owner-fenced, revision-aware project resource with confirmed-write reconciliation. */
import { afterEach, expect, it, vi } from 'vitest';
import { createReaderQueryClient } from './queryClient';
import { queryKeys } from './queryKeys';
import { fetchConfirmedProject, projectPolicies, reconcileProject, seedProject } from './workspaceProject';
import { browserClient } from './client';
import { ApiError } from './errors';
import type { Project } from '../api';

const project: Project = { owner_id: 'a', thread_id: 't1', current_stage: 'framing', stages: [],
  pending: null, review: { summary: '', strengths: [], improvements: [], facione_scores: [],
    project_brief: { status: 'missing', version: '', brief: null } } };

afterEach(() => vi.unstubAllGlobals());

it('keeps project reads immediately stale while retaining the last confirmed projection', () => {
  expect(projectPolicies.staleTime).toBe(0);
  expect(projectPolicies.gcTime).toBeGreaterThan(0);
});

it('rejects a project answer for another owner or notebook', async () => {
  browserClient.setConfig({ baseUrl: 'https://app.test' });
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(Response.json({ ...project, owner_id: 'foreign' }))));
  await expect(fetchConfirmedProject('a', 't1', new AbortController().signal)).rejects.toEqual(new ApiError(401));
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(Response.json({ ...project, thread_id: 't2' }))));
  await expect(fetchConfirmedProject('a', 't1', new AbortController().signal)).rejects.toEqual(new ApiError(401));
});

it('reconciles a confirmed project and cancels superseded reads', async () => {
  const client = createReaderQueryClient();
  seedProject(client, 'a', 't1', project);
  let resolve!: (value: Project) => void;
  const pending = client.fetchQuery({ queryKey: queryKeys.project('a', 't1'),
    queryFn: () => new Promise<Project>(done => { resolve = done; }) }).catch(() => undefined);
  const confirmed: Project = { ...project, current_stage: 'ideation' };
  await reconcileProject(client, 'a', 't1', () => confirmed);
  resolve(project); // A pre-write read finishing late must not roll back the confirmed decision.
  await pending;
  expect(client.getQueryData(queryKeys.project('a', 't1'))).toEqual(confirmed);
  client.clear();
});

it('never writes a confirmed decision into another owner resource', async () => {
  const client = createReaderQueryClient();
  seedProject(client, 'b', 't1', project);
  await reconcileProject(client, 'a', 't1', () => ({ ...project, current_stage: 'ideation' }));
  expect(client.getQueryData(queryKeys.project('b', 't1'))).toEqual(project);
  expect(client.getQueryData(queryKeys.project('a', 't1'))).toBeUndefined();
  client.clear();
});
