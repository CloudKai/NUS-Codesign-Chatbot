/** Request-local activity state; only a saved server receipt completes progress. */
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

