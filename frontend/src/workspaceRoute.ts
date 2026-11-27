/** Typed workspace URLs for the existing student views; the app's open flow stays the only navigation loader. */
import { createBrowserHistory, createRoute, createRootRoute, createRouter } from '@tanstack/react-router';
import { useSyncExternalStore } from 'react';

export type WorkspaceRoute =
  | { view: 'home' }
  | { view: 'library' }
  | { view: 'search' }
  | { view: 'settings' }
  | { view: 'chat'; threadId: string }
  | { view: 'notebook'; folderId: string }
  | { view: 'artifact'; folderId: string; artifactId: string }
  | { view: 'canvas'; folderId: string; canvasId: string };

const rootRoute = createRootRoute({});
const homeRoute = createRoute({ getParentRoute: () => rootRoute, path: '/' });
const chatRoute = createRoute({ getParentRoute: () => rootRoute, path: '/chats/$threadId' });
const notebookRoute = createRoute({ getParentRoute: () => rootRoute, path: '/notebooks/$folderId' });
const artifactRoute = createRoute({ getParentRoute: () => rootRoute, path: '/notebooks/$folderId/artifacts/$artifactId' });
const canvasRoute = createRoute({ getParentRoute: () => rootRoute, path: '/notebooks/$folderId/canvases/$canvasId' });
const libraryRoute = createRoute({ getParentRoute: () => rootRoute, path: '/library' });
const searchRoute = createRoute({ getParentRoute: () => rootRoute, path: '/search' });
const settingsRoute = createRoute({ getParentRoute: () => rootRoute, path: '/settings' });
// The /pilot hosting alias renders the same typed views.
const pilotHomeRoute = createRoute({ getParentRoute: () => rootRoute, path: '/pilot/' });
const pilotChatRoute = createRoute({ getParentRoute: () => rootRoute, path: '/pilot/chats/$threadId' });
const pilotNotebookRoute = createRoute({ getParentRoute: () => rootRoute, path: '/pilot/notebooks/$folderId' });
const pilotArtifactRoute = createRoute({ getParentRoute: () => rootRoute, path: '/pilot/notebooks/$folderId/artifacts/$artifactId' });
const pilotCanvasRoute = createRoute({ getParentRoute: () => rootRoute, path: '/pilot/notebooks/$folderId/canvases/$canvasId' });
const pilotLibraryRoute = createRoute({ getParentRoute: () => rootRoute, path: '/pilot/library' });
const pilotSearchRoute = createRoute({ getParentRoute: () => rootRoute, path: '/pilot/search' });
const pilotSettingsRoute = createRoute({ getParentRoute: () => rootRoute, path: '/pilot/settings' });

const routeTree = rootRoute.addChildren([homeRoute, chatRoute, notebookRoute, artifactRoute,
  canvasRoute,
  libraryRoute, searchRoute, settingsRoute, pilotHomeRoute, pilotChatRoute, pilotNotebookRoute,
  pilotArtifactRoute, pilotCanvasRoute, pilotLibraryRoute, pilotSearchRoute, pilotSettingsRoute]);

/** Browser history owned by the typed route tree; back/forward and refresh stay exact. */
export const workspaceRouter = createRouter({ routeTree, history: createBrowserHistory() });

/** Parse one recognized student view; unrecognized hosting paths render the public default. */
export function parseWorkspaceRoute(pathname: string): WorkspaceRoute {
  let path = pathname.length > 1 && pathname.endsWith('/') && !pathname.startsWith('/pilot/')
    ? pathname.slice(0, -1) : pathname;
  if (path === '/pilot') return { view: 'home' };
  if (path.startsWith('/pilot/')) path = path.slice('/pilot'.length);
  if (path === '/' || path === '') return { view: 'home' };
  if (path === '/library') return { view: 'library' };
  if (path === '/search') return { view: 'search' };
  if (path === '/settings') return { view: 'settings' };
  try {
    const chat = path.match(/^\/chats\/([^/]+)$/);
    if (chat) {
      const threadId = decodeURIComponent(chat[1]);
      if (threadId && !threadId.includes('/') && !threadId.startsWith('.')) return { view: 'chat', threadId };
    }
    const folder = path.match(/^\/notebooks\/([^/]+)$/);
    if (folder) {
      const folderId = decodeURIComponent(folder[1]);
      if (folderId && !folderId.includes('/') && !folderId.startsWith('.')) return { view: 'notebook', folderId };
    }
    const artifact = path.match(/^\/notebooks\/([^/]+)\/artifacts\/([^/]+)$/);
    if (artifact) {
      const folderId = decodeURIComponent(artifact[1]);
      const artifactId = decodeURIComponent(artifact[2]);
      if (folderId && !folderId.includes('/') && !folderId.startsWith('.')
        && artifactId && !artifactId.includes('/') && !artifactId.startsWith('.')) {
        return { view: 'artifact', folderId, artifactId };
      }
    }
    const canvas = path.match(/^\/notebooks\/([^/]+)\/canvases\/([^/]+)$/);
    if (canvas) {
      const folderId = decodeURIComponent(canvas[1]);
      const canvasId = decodeURIComponent(canvas[2]);
      if (folderId && !folderId.includes('/') && !folderId.startsWith('.')
        && canvasId && !canvasId.includes('/') && !canvasId.startsWith('.')) {
        return { view: 'canvas', folderId, canvasId };
      }
    }
  } catch { /* Malformed identities render the public default. */ }
  return { view: 'home' };
}

/** Build one recognized view path; identities are percent-encoded exactly once. */
export function workspacePath(route: WorkspaceRoute): string {
  if (route.view === 'chat') return `/chats/${encodeURIComponent(route.threadId)}`;
  if (route.view === 'notebook') return `/notebooks/${encodeURIComponent(route.folderId)}`;
  if (route.view === 'artifact') {
    return `/notebooks/${encodeURIComponent(route.folderId)}/artifacts/${encodeURIComponent(route.artifactId)}`;
  }
  if (route.view === 'canvas') {
    return `/notebooks/${encodeURIComponent(route.folderId)}/canvases/${encodeURIComponent(route.canvasId)}`;
  }
  if (route.view === 'home') return '/';
  return `/${route.view}`;
}

/** The current typed route of this tab. */
export function currentWorkspaceRoute(): WorkspaceRoute {
  return parseWorkspaceRoute(workspaceRouter.history.location.pathname);
}

/** Push one workspace route; same-path pushes are ignored to keep history clean. */
export function openWorkspaceRoute(route: WorkspaceRoute, options: { replace?: boolean } = {}): void {
  const location = workspaceRouter.history.location.pathname;
  const base = location === '/pilot' || location.startsWith('/pilot/') ? '/pilot' : '';
  const target = base + workspacePath(route);
  if (location === target) return;
  if (options.replace) workspaceRouter.history.replace(target);
  else workspaceRouter.history.push(target);
}

/** React binding: re-render on every typed URL change, including back/forward. */
export function useWorkspaceRoute(): WorkspaceRoute {
  const pathname = useSyncExternalStore(
    done => workspaceRouter.history.subscribe(done),
    () => workspaceRouter.history.location.pathname,
    () => workspaceRouter.history.location.pathname,
  );
  return parseWorkspaceRoute(pathname);
}
