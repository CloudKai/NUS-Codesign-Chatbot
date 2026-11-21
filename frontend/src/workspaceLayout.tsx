/**
 * Workspace panel layout: where the sidebar and Review sit and how wide they are.
 *
 * Placement follows the space the window has, never a single breakpoint:
 * 1. Keep the chat column at CHAT_MIN or wider.
 * 2. When Review would squeeze the chat, the sidebar becomes an icon rail first. The saved
 *    sidebar preference is not changed, so the full sidebar returns when space allows.
 * 3. If the chat still would be too narrow, Review becomes a drawer (tablet) or a full-screen
 *    view (phone). Temporary shrinking never overwrites the widths the student chose.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';

/** The chat column is never narrower than this while the panels are docked. */
export const CHAT_MIN = 600;
export const RAIL_WIDTH = 60;
const PHONE_MAX_WIDTH = 767;
export const SIDEBAR_LIMITS = { min: 200, max: 360, fallback: 236 } as const;
export const REVIEW_LIMITS = { min: 320, max: 640, fallback: 380 } as const;
const KEY_STEP = 16;
const KEY_STEP_LARGE = 64;
const STORAGE_KEY = 'codesign-layout:v1';

export type NavPreference = 'expanded' | 'collapsed';
export type NavMode = 'docked' | 'rail' | 'drawer';
export type ReviewMode = 'docked' | 'drawer' | 'fullscreen';

interface Preferences { nav: NavPreference; sidebar: number; review: number }

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max);

/** Read the saved layout. Missing, unreadable or out-of-range values fall back to the defaults. */
function readPreferences(): Preferences {
  const fallback: Preferences = { nav: 'expanded', sidebar: SIDEBAR_LIMITS.fallback, review: REVIEW_LIMITS.fallback };
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
    if (!saved || typeof saved !== 'object') return fallback;
    const number = (value: unknown, limits: { min: number; max: number }, otherwise: number) =>
      typeof value === 'number' && Number.isFinite(value) ? clamp(Math.round(value), limits.min, limits.max) : otherwise;
    return {
      nav: saved.nav === 'collapsed' ? 'collapsed' : 'expanded',
      sidebar: number(saved.sidebar, SIDEBAR_LIMITS, fallback.sidebar),
      review: number(saved.review, REVIEW_LIMITS, fallback.review),
    };
  } catch { return fallback; }
}

export interface Layout {
  /** Sidebar: docked and full, a 60 px icon rail, or a drawer (phones). */
  nav: NavMode;
  /** Pixels the sidebar column takes in the workspace grid. */
  navWidth: number;
  /** Where Review goes when it is open. */
  review: ReviewMode;
  /** Review width in pixels when docked. */
  reviewWidth: number;
  /** True when the full sidebar fits next to the chat (and Review, when docked). */
  canDockNav: boolean;
  sidebarMax: number;
  reviewMax: number;
}

/** Decide panel placement from the window width, saved preferences and whether Review is open. */
export function computeLayout(width: number, prefs: Preferences, reviewOpen: boolean): Layout {
  const sidebar = clamp(prefs.sidebar, SIDEBAR_LIMITS.min, SIDEBAR_LIMITS.max);
  const preferred = clamp(prefs.review, REVIEW_LIMITS.min, REVIEW_LIMITS.max);
  if (width <= PHONE_MAX_WIDTH) {
    return { nav: 'drawer', navWidth: 0, review: 'fullscreen', reviewWidth: 0, canDockNav: false, sidebarMax: sidebar, reviewMax: preferred };
  }
  const wantsFullSidebar = prefs.nav === 'expanded';
  // Where Review would sit if it were open, and what the sidebar does to make room.
  let review: ReviewMode = 'drawer';
  let reviewNav: NavMode = 'rail';
  let reviewWidth = 0;
  if (wantsFullSidebar && width - sidebar - preferred >= CHAT_MIN) {
    review = 'docked'; reviewNav = 'docked'; reviewWidth = preferred;
  } else if (width - RAIL_WIDTH - preferred >= CHAT_MIN) {
    review = 'docked'; reviewWidth = preferred;
  } else if (width - RAIL_WIDTH - REVIEW_LIMITS.min >= CHAT_MIN) {
    review = 'docked'; reviewWidth = width - RAIL_WIDTH - CHAT_MIN;
  }
  const plainNav: NavMode = wantsFullSidebar && width - sidebar >= CHAT_MIN ? 'docked' : 'rail';
  const nav = reviewOpen && review === 'docked' ? reviewNav : plainNav;
  const navWidth = nav === 'docked' ? sidebar : RAIL_WIDTH;
  const dockedReview = reviewOpen && review === 'docked' ? reviewWidth : 0;
  return {
    nav, navWidth, review, reviewWidth,
    canDockNav: width - sidebar - dockedReview >= CHAT_MIN,
    sidebarMax: clamp(width - CHAT_MIN - dockedReview, SIDEBAR_LIMITS.min, SIDEBAR_LIMITS.max),
    reviewMax: clamp(width - navWidth - CHAT_MIN, REVIEW_LIMITS.min, REVIEW_LIMITS.max),
  };
}

export interface WorkspaceLayout extends Layout {
  sidebarPreference: number;
  reviewPreference: number;
  navPreference: NavPreference;
  setNavPreference: (value: NavPreference) => void;
  resizeSidebar: (pixels: number) => void;
  resizeReview: (pixels: number) => void;
  resetSidebar: () => void;
  resetReview: () => void;
  setReviewOpen: (open: boolean) => void;
}

/** Track the window width, the saved panel preferences and the open state of Review. */
export function useWorkspaceLayout(): WorkspaceLayout {
  const [width, setWidth] = useState(() => window.innerWidth);
  const [prefs, setPrefs] = useState(readPreferences);
  const [reviewOpen, setReviewOpen] = useState(false);
  useEffect(() => {
    let frame = 0;
    const onResize = () => { window.cancelAnimationFrame(frame); frame = window.requestAnimationFrame(() => setWidth(window.innerWidth)); };
    window.addEventListener('resize', onResize);
    return () => { window.cancelAnimationFrame(frame); window.removeEventListener('resize', onResize); };
  }, []);
  useEffect(() => {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs)); } catch { /* Layout preferences are optional. */ }
  }, [prefs]);
  const layout = useMemo(() => computeLayout(width, prefs, reviewOpen), [width, prefs, reviewOpen]);
  const latest = useRef(layout);
  latest.current = layout;
  const setNavPreference = useCallback((nav: NavPreference) => setPrefs(value => value.nav === nav ? value : { ...value, nav }), []);
  const resizeSidebar = useCallback((pixels: number) => {
    const sidebar = clamp(Math.round(pixels), SIDEBAR_LIMITS.min, latest.current.sidebarMax);
    setPrefs(value => value.sidebar === sidebar ? value : { ...value, sidebar });
  }, []);
  const resizeReview = useCallback((pixels: number) => {
    const review = clamp(Math.round(pixels), REVIEW_LIMITS.min, latest.current.reviewMax);
    setPrefs(value => value.review === review ? value : { ...value, review });
  }, []);
  // Reset stores the default itself. The layout still protects the chat width when the default does not fit.
  const resetSidebar = useCallback(() => setPrefs(value => ({ ...value, sidebar: SIDEBAR_LIMITS.fallback })), []);
  const resetReview = useCallback(() => setPrefs(value => ({ ...value, review: REVIEW_LIMITS.fallback })), []);
  return {
    ...layout,
    sidebarPreference: prefs.sidebar, reviewPreference: prefs.review, navPreference: prefs.nav,
    setNavPreference, resizeSidebar, resizeReview, resetSidebar, resetReview, setReviewOpen,
  };
}

export const WorkspaceLayoutContext = createContext<WorkspaceLayout | null>(null);

/** Read the shared layout. Must be used inside the workspace. */
export function useWorkspaceLayoutContext(): WorkspaceLayout {
  const layout = useContext(WorkspaceLayoutContext);
  if (!layout) throw new Error('Workspace layout is unavailable outside the workspace.');
  return layout;
}

/**
 * A separator between two panels. Drag it, use the arrow keys, press Home or double-click to reset.
 * `side` is the panel it resizes: the sidebar grows to the right, Review grows to the left.
 */
export function ResizeHandle({ side, label, value, min, max, onResize, onReset }: {
  side: 'sidebar' | 'review'; label: string; value: number; min: number; max: number;
  onResize: (pixels: number) => void; onReset: () => void;
}) {
  const [dragging, setDragging] = useState(false);
  function widthAt(event: PointerEvent<HTMLDivElement>) {
    const frame = (event.currentTarget.offsetParent as HTMLElement | null)?.getBoundingClientRect();
    if (!frame) return value;
    return side === 'sidebar' ? event.clientX - frame.left : frame.right - event.clientX;
  }
  function end(event: PointerEvent<HTMLDivElement>) {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    setDragging(false);
  }
  useEffect(() => {
    if (!dragging) return;
    document.body.classList.add('is-resizing');
    return () => document.body.classList.remove('is-resizing');
  }, [dragging]);
  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const step = event.shiftKey ? KEY_STEP_LARGE : KEY_STEP;
    const grow = side === 'sidebar' ? 'ArrowRight' : 'ArrowLeft';
    const shrink = side === 'sidebar' ? 'ArrowLeft' : 'ArrowRight';
    if (event.key === grow) onResize(value + step);
    else if (event.key === shrink) onResize(value - step);
    else if (event.key === 'Home') onReset();
    else return;
    event.preventDefault();
  }
  return <div role="separator" aria-orientation="vertical" tabIndex={0} className={`resize-handle ${side}`} data-dragging={dragging || undefined}
    aria-label={label} aria-valuemin={min} aria-valuemax={max} aria-valuenow={Math.round(value)}
    title="Drag to resize. Double-click or press Home to reset."
    onPointerDown={event => {
      if (event.button !== 0) return;
      event.preventDefault();
      event.currentTarget.setPointerCapture(event.pointerId);
      setDragging(true);
    }}
    onPointerMove={event => { if (dragging) onResize(widthAt(event)); }}
    onPointerUp={end} onPointerCancel={end}
    onDoubleClick={onReset} onKeyDown={onKeyDown}/>;
}
