/** Request-local activity. Only a saved server receipt completes progress. */
import { useEffect, useState } from 'react';

type Phase = 'waiting' | 'writing' | 'saving' | 'saved' | 'discarded';
interface Progress { phase: Phase }

/** Track actual lifecycle events and briefly retain confirmed saved feedback. */
export function useChatProgress() {
  const [value, setValue] = useState<Progress | null>(null);
  const phase = value?.phase;
  useEffect(() => {
    if (!phase) return;
    if (phase === 'saved') {
      const timer = window.setTimeout(() => setValue(null), 650);
      return () => window.clearTimeout(timer);
    }
  }, [phase]);

  return {
    value,
    start: () => setValue({ phase: 'waiting' }),
    writing: () => setValue(current => current && (current.phase === 'waiting' || current.phase === 'discarded')
      ? { phase: 'writing' } : current),
    saving: () => setValue(current => current && current.phase !== 'saved' ? { phase: 'saving' } : current),
    discard: () => setValue(current => current ? { phase: 'discarded' } : current),
    saved: () => setValue(current => current ? { phase: 'saved' } : current),
    clear: () => setValue(null),
  };
}

/** Show indeterminate activity alongside the actual, separately announced status. */
export function ChatProgress({ value, status }: { value: Progress | null; status: string }) {
  if (!value) return null;
  const saved = value.phase === 'saved';
  return <div className="chat-progress grid gap-2" data-phase={value.phase}>
    {saved ? <span className="chat-progress-label">Reply saved</span> : null}
    <div className="chat-progress-track" aria-hidden="true">
      <div className={`chat-progress-fill motion-reduce:transition-none${saved ? '' : ' chat-progress-indeterminate'}`}/>
    </div>
    <span className="sr-only" role="progressbar" aria-label="Coach reply"
      aria-valuetext={saved ? 'Reply saved' : status}
      aria-valuenow={saved ? 100 : undefined} aria-valuemin={0} aria-valuemax={100}/>
  </div>;
}
