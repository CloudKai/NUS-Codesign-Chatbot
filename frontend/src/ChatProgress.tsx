/** Request-local visual estimates. Only a saved server receipt completes progress. */
import { useEffect, useState } from 'react';

type Phase = 'waiting' | 'writing' | 'saving' | 'saved' | 'discarded';
interface Progress { phase: Phase; started: number; percent: number; elapsed: number }

/** Own the active request's bounded estimate and clean up its animation timers. */
export function useChatProgress() {
  const [value, setValue] = useState<Progress | null>(null);
  const phase = value?.phase;
  const started = value?.started;
  useEffect(() => {
    if (!phase) return;
    if (phase === 'saved') {
      const timer = window.setTimeout(() => setValue(null), 650);
      return () => window.clearTimeout(timer);
    }
    if (phase !== 'waiting' && phase !== 'discarded') return;
    const timer = window.setInterval(() => setValue(current => {
      if (!current) return null;
      const elapsed = performance.now() - current.started;
      const estimate = 10 + 55 * (1 - Math.exp(-elapsed / 5000));
      const percent = current.phase === 'waiting' ? Math.min(65, estimate) : current.percent;
      return { ...current, elapsed, percent };
    }), 200);
    return () => window.clearInterval(timer);
  }, [phase, started]);

  return {
    value,
    start: () => setValue({ phase: 'waiting', started: performance.now(), percent: 10, elapsed: 0 }),
    writing: () => setValue(current => current && (current.phase === 'waiting' || current.phase === 'discarded')
      ? { ...current, phase: 'writing', percent: Math.max(90, current.percent) } : current),
    saving: () => setValue(current => current && current.phase !== 'saved' ? { ...current, phase: 'saving', percent: 98 } : current),
    discard: () => setValue(current => current ? { ...current, phase: 'discarded', percent: 0 } : current),
    saved: () => setValue(current => current ? { ...current, phase: 'saved', percent: 100 } : current),
    clear: () => setValue(null),
  };
}

/** Display decorative estimated percentages alongside accessible request status. */
export function ChatProgress({ value, status }: { value: Progress | null; status: string }) {
  if (!value) return null;
  const discarded = value.phase === 'discarded';
  return <div className="chat-progress grid gap-2" data-phase={value.phase}>
    <div className="flex items-center justify-between gap-3">
      <span className="chat-progress-label">{value.phase === 'saved' ? 'Reply saved' : 'Estimated progress'}</span>
      <span className="chat-progress-percent tabular-nums" aria-hidden="true">{discarded ? '…' : `${Math.floor(value.percent)}%`}</span>
    </div>
    <div className="chat-progress-track" aria-hidden="true">
      <div className={`chat-progress-fill motion-reduce:transition-none${discarded ? ' chat-progress-indeterminate' : ''}`}
        style={{ transform: `scaleX(${discarded ? .3 : value.percent / 100})` }}/>
    </div>
    <span className="sr-only" role="progressbar" aria-label="Coach reply"
      aria-valuetext={value.phase === 'saved' ? 'Reply saved' : status}
      aria-valuenow={value.phase === 'saved' ? 100 : undefined} aria-valuemin={0} aria-valuemax={100}/>
    {(value.phase === 'waiting' || discarded) && value.elapsed >= 6000
      ? <p className="chat-progress-explanation">A new or idle chat may need AWS to start a secure session and load the coach’s code before preparing your reply.</p> : null}
  </div>;
}
