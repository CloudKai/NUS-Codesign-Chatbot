/**
 * @vitest-environment jsdom
 */
/** Typed URL parsing, hosting-alias handling and exact back/forward history. */
import { afterEach, expect, it, vi } from 'vitest';
import { currentWorkspaceRoute, openWorkspaceRoute, parseWorkspaceRoute, workspacePath,
  workspaceRouter, type WorkspaceRoute } from './workspaceRoute';

afterEach(() => {
  if (workspaceRouter.history.location.pathname !== '/') workspaceRouter.history.replace('/');
});

it('parses every recognized view and the pilot hosting alias', () => {
  expect(parseWorkspaceRoute('/')).toEqual({ view: 'home' });
  expect(parseWorkspaceRoute('/library')).toEqual({ view: 'library' });
  expect(parseWorkspaceRoute('/search')).toEqual({ view: 'search' });
  expect(parseWorkspaceRoute('/settings')).toEqual({ view: 'settings' });
  expect(parseWorkspaceRoute('/chats/abc')).toEqual({ view: 'chat', threadId: 'abc' });
  expect(parseWorkspaceRoute('/notebooks/folder-1')).toEqual({ view: 'notebook', folderId: 'folder-1' });
  expect(parseWorkspaceRoute('/notebooks/folder-1/artifacts/a-1')).toEqual(
    { view: 'artifact', folderId: 'folder-1', artifactId: 'a-1' });
  expect(parseWorkspaceRoute('/notebooks/folder-1/canvases/c-1')).toEqual(
    { view: 'canvas', folderId: 'folder-1', canvasId: 'c-1' });
  expect(parseWorkspaceRoute('/pilot/')).toEqual({ view: 'home' });
  expect(parseWorkspaceRoute('/pilot/chats/abc')).toEqual({ view: 'chat', threadId: 'abc' });
  expect(parseWorkspaceRoute('/pilot/notebooks/folder-1')).toEqual({ view: 'notebook', folderId: 'folder-1' });
  expect(parseWorkspaceRoute('/pilot/notebooks/folder-1/artifacts/a-1')).toEqual(
    { view: 'artifact', folderId: 'folder-1', artifactId: 'a-1' });
  expect(parseWorkspaceRoute('/pilot/notebooks/folder-1/canvases/c-1')).toEqual(
    { view: 'canvas', folderId: 'folder-1', canvasId: 'c-1' });
  expect(parseWorkspaceRoute('/pilot/library')).toEqual({ view: 'library' });
});

it('renders unknown or malformed paths as the public default without private data', () => {
  for (const path of ['/unknown', '/chats', '/chats/a/b', '/notebooks/', '/artifacts/a-1',
    '/notebooks/f-1/artifacts/', '/api/v1/reader/session',
    '/streamlit/', '/chats/%2F..%2Fescape', '/pilot/unknown']) {
    expect(parseWorkspaceRoute(path)).toEqual({ view: 'home' });
  }
});

it('round-trips thread and folder identities exactly once', () => {
  const route: WorkspaceRoute = { view: 'chat', threadId: 'id with spaces' };
  const path = workspacePath(route);
  expect(path).toBe('/chats/id%20with%20spaces');
  expect(parseWorkspaceRoute(path)).toEqual(route);
  expect(workspacePath({ view: 'notebook', folderId: 'folder-1' })).toBe('/notebooks/folder-1');
  const canvasRoute: WorkspaceRoute = { view: 'canvas', folderId: 'folder-1', canvasId: 'c 1' };
  const canvasPath = workspacePath(canvasRoute);
  expect(canvasPath).toBe('/notebooks/folder-1/canvases/c%201');
  expect(parseWorkspaceRoute(canvasPath)).toEqual(canvasRoute);
});

it('pushes navigation, keeps history exact and ignores same-path repeats', () => {
  expect(currentWorkspaceRoute()).toEqual({ view: 'home' });
  openWorkspaceRoute({ view: 'library' });
  openWorkspaceRoute({ view: 'chat', threadId: 't1' });
  openWorkspaceRoute({ view: 'chat', threadId: 't1' }); // Same path: no duplicate history entry.
  expect(workspaceRouter.history.location.pathname).toBe('/chats/t1');
});

it('follows browser back/forward traversals through popstate', () => {
  openWorkspaceRoute({ view: 'library' });
  openWorkspaceRoute({ view: 'chat', threadId: 't1' });
  // jsdom cannot traverse natively; simulate the traversal the browser performs.
  window.history.replaceState(null, '', '/notebooks/f1');
  window.dispatchEvent(new PopStateEvent('popstate'));
  expect(currentWorkspaceRoute()).toEqual({ view: 'notebook', folderId: 'f1' });
  window.history.replaceState(null, '', '/chats/t1');
  window.dispatchEvent(new PopStateEvent('popstate'));
  expect(currentWorkspaceRoute()).toEqual({ view: 'chat', threadId: 't1' });
  window.history.replaceState(null, '', '/');
  window.dispatchEvent(new PopStateEvent('popstate'));
  expect(currentWorkspaceRoute()).toEqual({ view: 'home' });
});

it('keeps a reload (refresh) exact through the router history', () => {
  openWorkspaceRoute({ view: 'settings' }, { replace: true });
  expect(currentWorkspaceRoute()).toEqual({ view: 'settings' });
  expect(workspaceRouter.history.location.pathname).toBe('/settings');
});

it('notifies subscribers on every navigation', () => {
  const subscriber = vi.fn();
  const unsubscribe = workspaceRouter.history.subscribe(subscriber);
  openWorkspaceRoute({ view: 'search' });
  expect(subscriber).toHaveBeenCalled();
  unsubscribe();
});
