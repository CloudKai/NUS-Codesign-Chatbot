/** Welcome-back home: where the student left off, in one click. Read-only; no model calls. */
import { useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, currentSession, get, type ChatSummary, type Notebook, type Project } from './api';
import { skillSummary } from './coachingContent';
import { Icon } from './Icon';
import { recentChats } from './notebookChats';
import { StageStepper, hasProjectWork } from './StageStepper';

const STAGE_NAMES = ['Problem identification', 'Concept generation', 'Design specification', 'Ethics & Critical Thinking', 'Reflection'];

/** Time-of-day greeting from the browser clock. */
function greeting(now: Date) {
  const hour = now.getHours();
  return hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
}

const units: [Intl.RelativeTimeFormatUnit, number][] = [['year', 31536000], ['month', 2592000], ['week', 604800], ['day', 86400], ['hour', 3600], ['minute', 60]];
const relative = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });

/** "2 days ago" style label; empty when the time is unknown. */
export function relativeTime(iso: string | undefined, now = Date.now()) {
  const time = Date.parse(iso ?? '');
  if (!Number.isFinite(time)) return '';
  const seconds = Math.round((time - now) / 1000);
  for (const [unit, size] of units) if (Math.abs(seconds) >= size) return relative.format(Math.round(seconds / size), unit);
  return 'just now';
}

export function HomeView({ owner, name, entries, summaries, locked, openChat, startChat, decided, expired }: {
  owner: string; name: string; entries: Notebook[]; summaries: Record<string, ChatSummary>; locked: boolean;
  openChat: (id: string) => void; startChat: (intent: 'project' | 'lecture') => void;
  decided: (id: string) => Promise<void>; expired: () => void;
}) {
  // Chats without a saved preview are empty or untitled drafts, so they are not worth resuming from Home.
  const chats = useMemo(() => recentChats([
    ...entries.filter(entry => entry.kind === 'chat'),
    ...entries.filter(entry => entry.kind === 'notebook'),
  ].filter(entry => summaries[entry.id]?.preview), summaries), [entries, summaries]);
  const latest = chats[0];
  const others = chats.slice(1, 4);
  const [project, setProject] = useState<Project | null>(null);
  const [deciding, setDeciding] = useState(false);
  const [decisionStatus, setDecisionStatus] = useState('');
  const lock = useRef(false);
  const active = useRef(true);
  const controller = useRef(new AbortController());
  useEffect(() => {
    active.current = true;
    return () => { active.current = false; controller.current.abort(); };
  }, []);
  async function loadProject(id: string, signal: AbortSignal) {
    const value = await get<Project>(`/api/v1/reader/threads/${encodeURIComponent(id)}/project`, signal);
    if (value.owner_id === owner && value.thread_id === id) setProject(value);
  }
  useEffect(() => {
    setProject(null);
    setDecisionStatus('');
    if (!latest) return;
    const request = new AbortController();
    loadProject(latest.id, request.signal)
      .catch(() => { /* The card still shows title, preview and time without progress. */ });
    return () => request.abort();
  }, [latest?.id, owner]);
  /** Same endpoint and lock rules as the in-chat card; the answer is never replayed, only re-read. */
  async function decide(accepted: boolean) {
    const pending = project?.pending;
    if (!latest || !pending || lock.current || locked) return;
    const id = latest.id;
    lock.current = true;
    setDeciding(true);
    setDecisionStatus('Checking saved project…');
    controller.current = new AbortController();
    const signal = controller.current.signal;
    try {
      const session = await currentSession(signal);
      if (session.owner_id !== owner) { expired(); return; }
      const response = await fetch(`/api/v1/reader/threads/${encodeURIComponent(id)}/project/resolve/${encodeURIComponent(pending.id)}`, {
        method: 'POST', credentials: 'same-origin', cache: 'no-store', signal,
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ accepted }),
      });
      if ([401, 403].includes(response.status)) { expired(); return; }
      await loadProject(id, signal);
      await decided(id);
      if (active.current) setDecisionStatus(response.ok ? (accepted ? 'Moved to the next stage.' : 'Staying in this stage.') : 'That decision is no longer available. Saved project refreshed.');
    } catch (error) {
      if (active.current && !(error instanceof DOMException && error.name === 'AbortError')) {
        setDecisionStatus(error instanceof ApiError && [401, 403].includes(error.status) ? 'Sign in again to continue.' : 'Could not verify the decision. Open the chat to check the saved project.');
      }
    } finally {
      lock.current = false;
      if (active.current) setDeciding(false);
    }
  }
  const folder = (chat: Notebook) => entries.find(entry => entry.id === chat.parent_notebook_id && entry.kind === 'notebook')?.name;
  const stage = project?.stages.find(item => item.id === project.current_stage);
  const skills = skillSummary(project?.review?.facione_scores ?? []);
  const when = useMemo(() => greeting(new Date()), []);

  return <section className="home" aria-labelledby="home-title">
    <span className="welcome-mark"><Icon name="spark"/></span>
    <h1 id="home-title">{when}{name ? `, ${name}` : ''}</h1>
    {latest ? <>
      <p className="home-lead">Pick up where you left off.</p>
      <article className="continue-card" aria-label="Continue where you left off">
        <div className="continue-meta">
          <span>{lastActive(summaries[latest.id], folder(latest))}</span>
        </div>
        <h2>{latest.name}</h2>
        {summaries[latest.id]?.preview ? <p className="continue-preview">{summaries[latest.id].preview}</p> : null}
        {project && stage && hasProjectWork(project) ? <div className="continue-progress">
          <StageStepper stages={project.stages} currentStage={project.current_stage} pending={!!project.pending} compact/>
          <p><strong>{stage.label}</strong></p>
          {project.pending ? <div className="home-decision">
            <p className="home-decision-question">Ready for {project.stages.find(item => item.id === project.pending!.to_stage)?.label ?? 'the next stage'}?</p>
            <div className="stage-actions">
              <button className="primary" disabled={locked || deciding} onClick={() => void decide(true)}>Move on</button>
              <button disabled={locked || deciding} onClick={() => void decide(false)}>Stay here</button>
            </div>
          </div> : <p className="supporting">{stage.next_action}</p>}
          <p className="supporting" role="status">{decisionStatus}</p>
          {skills ? <p className="supporting">Strongest skill: {skills.strongest}. Next to grow: {skills.grow}.</p> : null}
        </div> : null}
        <button className="primary" disabled={locked} onClick={() => openChat(latest.id)}>Continue <Icon name="chevronRight"/></button>
      </article>
      {others.length ? <section className="recent-chats" aria-label="Other recent chats">
        <h2>Recent chats</h2>
        <ul>{others.map(chat => <li key={chat.id}><button disabled={locked} onClick={() => openChat(chat.id)}>
          <Icon name="chat"/>
          <span><strong>{chat.name}</strong>{summaries[chat.id]?.preview ? <small>{summaries[chat.id].preview}</small> : null}</span>
          <time>{relativeTime(summaries[chat.id]?.activity_at)}</time>
        </button></li>)}</ul>
      </section> : null}
    </> : <>
      <p className="home-lead">Bring a half-formed thought. We’ll work through it together.</p>
      <section className="first-run" aria-label="How the Thinking Path works">
        <h2>Your Thinking Path has five stages</h2>
        <ol>{STAGE_NAMES.map((label, index) => <li key={label}><span className="stage-number" aria-hidden="true">{index + 1}</span>{label}</li>)}</ol>
        <p className="supporting">The coach suggests when to move on. You decide.</p>
        <div className="empty-workspace-actions">
          <button className="primary" disabled={locked} onClick={() => startChat('project')}>Start my design project</button>
          <button disabled={locked} onClick={() => startChat('lecture')}>Ask a lecture question</button>
        </div>
      </section>
    </>}
    <p className="supporting privacy-note">Your work here is not graded.</p>
  </section>;
}

function lastActive(summary: ChatSummary | undefined, folder: string | undefined) {
  const when = relativeTime(summary?.activity_at);
  return [when ? `Last active ${when}` : 'Your latest chat', folder ? `in ${folder}` : ''].filter(Boolean).join(' ');
}
