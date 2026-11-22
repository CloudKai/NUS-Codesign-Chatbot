/** Pace genuine reply fragments across paints, even if they arrive in one network read. */
export function createReplyPreview(paint: (text: string) => void, signal: AbortSignal) {
  const interval = 55;
  const catchUpFrames = 14;
  let shown = '';
  let queued = '';
  let timer: ReturnType<typeof setTimeout> | undefined;
  let complete = false;
  let resolveDrain: (() => void) | undefined;

  function clearTimer() {
    if (timer !== undefined) clearTimeout(timer);
    timer = undefined;
  }

  function discard() {
    clearTimer();
    queued = '';
    shown = '';
    paint('');
    resolveDrain?.();
    resolveDrain = undefined;
  }

  function tick() {
    timer = undefined;
    if (signal.aborted) return;
    // Keep a trailing partial word until the next fragment arrives. Retain all
    // whitespace so Markdown in the validated reply still lines up.
    const words = queued.match(/\s*\S+\s+/g) ?? [];
    const total = words.length + (complete && words.join('').length < queued.length ? 1 : 0);
    const count = Math.max(3, Math.ceil(total / catchUpFrames));
    const part = complete && total <= count ? queued : words.slice(0, count).join('');
    if (part) {
      queued = queued.slice(part.length);
      shown += part;
      paint(shown);
    }
    if (queued && part) timer = setTimeout(tick, interval);
    else if (!queued) { resolveDrain?.(); resolveDrain = undefined; }
  }

  function schedule() {
    if (timer === undefined && !signal.aborted) timer = setTimeout(tick, 0);
  }

  function abort() {
    clearTimer();
    resolveDrain?.();
    resolveDrain = undefined;
  }
  signal.addEventListener('abort', abort, { once: true });

  return {
    append(text: string) { queued += text; schedule(); },
    discard,
    async finish(text: string) {
      if (signal.aborted) return;
      const received = shown + queued;
      if (!received || document.hidden) {
        // A final-only response does not start a typing effect.
        clearTimer();
        queued = '';
        shown = text;
        paint(text);
        return;
      }
      if (shown && !text.startsWith(shown)) {
        // Validation can rewrite the draft. Replace any visible obsolete text.
        clearTimer();
        queued = '';
        paint(text);
        return;
      }
      complete = true;
      queued = text.slice(shown.length);
      if (!queued) return;
      await new Promise<void>(resolve => {
        resolveDrain = resolve;
        schedule();
      });
    },
    dispose() {
      abort();
      signal.removeEventListener('abort', abort);
    },
  };
}
