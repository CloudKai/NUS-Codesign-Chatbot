/** Welcome-back home: where the student left off, in one click. Read-only; no model calls. */
import { useEffect, useMemo, useState } from 'react';
import type { ChatSummary, Notebook, Project } from './api';
import { readProject, readArtifacts, readCanvases } from './api/client';
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

export function HomeView({ owner, name, entries, summaries, locked, openChat, startChat,
  openArtifact, openCanvas }: {
  owner: string; name: string; entries: Notebook[]; summaries: Record<string, ChatSummary>; locked: boolean;
  openChat: (id: string) => void; startChat: (intent: 'project' | 'improve') => void;
  expired?: () => void;
  openArtifact?: (folderId: string, artifactId: string) => void;
  openCanvas?: (folderId: string, canvasId: string) => void;
}) {
  // Chats without a saved preview are empty or untitled drafts, so they are not worth resuming from Home.
  const chats = useMemo(() => recentChats([
    ...entries.filter(entry => entry.kind === 'chat'),
    ...entries.filter(entry => entry.kind === 'notebook'),
  ].filter(entry => summaries[entry.id]?.preview), summaries), [entries, summaries]);
  const latest = chats[0];
  const others = chats.slice(1, 4);
  const [project, setProject] = useState<Project | null>(null);
  async function loadProject(id: string, signal: AbortSignal) {
    const value = await readProject(id, signal);
    if (value.owner_id === owner && value.thread_id === id) setProject(value);
  }
  useEffect(() => {
    setProject(null);
    if (!latest) return;
    const request = new AbortController();
    loadProject(latest.id, request.signal)
      .catch(() => { /* The card still shows title, preview and time without progress. */ });
    return () => request.abort();
  }, [latest?.id, owner]);
  const folder = (chat: Notebook) => entries.find(entry => entry.id === chat.parent_notebook_id && entry.kind === 'notebook')?.name;
  const stage = project?.stages.find(item => item.id === project.current_stage);
  const skills = skillSummary(project?.review?.facione_scores ?? []);
  // The project notebook owns the persistent artifacts and canvases; everything
  // here reuses persisted summaries, timestamps and bounded list reads. No
  // model call, no fabricated progress and no activity counts as learning.
  const projectNotebookId = latest
    ? (latest.kind === 'notebook' ? latest.id : latest.parent_notebook_id ?? undefined)
    : undefined;
  const [artifacts, setArtifacts] = useState<{ id: string; title: string; updated_at: string }[] | null>(null);
  const [canvases, setCanvases] = useState<{ id: string; title: string; updated_at: string }[] | null>(null);
  useEffect(() => {
    setArtifacts(null); setCanvases(null);
    if (!projectNotebookId) return;
    const request = new AbortController();
    readArtifacts(projectNotebookId, request.signal)
      .then(list => setArtifacts(list.artifacts.slice(0, 2)))
      .catch(() => { /* The card still shows the chat and progress without saved work. */ });
    readCanvases(projectNotebookId, request.signal)
      .then(list => setCanvases(list.canvases.slice(0, 2)))
      .catch(() => { /* Same truthful absence for canvases. */ });
    return () => request.abort();
  }, [projectNotebookId]);
  const stageFeedback = (project?.review?.improvements ?? [])
    .find(item => item.stage_id === project?.current_stage)?.items.slice(0, 2) ?? [];
  // The most recent confirmed-milestone recap, persisted at confirmation time.
  const recap = (project?.recaps ?? [])
    .slice()
    .sort((a, b) => (a.confirmed_at < b.confirmed_at ? 1 : -1))[0] ?? null;
  // The student's own latest saved contribution, so Home shows the companion remembers their work.
  const lastShared = (() => {
    if (!project) return '';
    const ordered = [...project.stages].sort((a, b) => Number(b.id === project.current_stage) - Number(a.id === project.current_stage));
    const text = ordered.map(item => item.student_work[item.student_work.length - 1]?.text).find(Boolean)?.trim() ?? '';
    return text.length > 160 ? `${text.slice(0, 157).trimEnd()}…` : text;
  })();
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
        {lastShared || summaries[latest.id]?.preview
          ? <p className="continue-preview">{lastShared ? <span className="continue-label">You last shared</span> : null}{lastShared ? `“${lastShared}”` : summaries[latest.id].preview}</p> : null}
        {project && stage && hasProjectWork(project) ? <div className="continue-progress">
          <StageStepper stages={project.stages} currentStage={project.current_stage} pending={!!project.pending} compact/>
          <p className="home-work-on"><span className="continue-label">To work on</span>
            {(() => {
              const pending = project.pending;
              const pendingLabel = pending
                ? project.stages.find(item => item.id === pending.to_stage)?.label ?? 'the next stage'
                : '';
              return project.pending
                ? `“${bounded(project.pending.rationale) || pendingLabel}”`
                : stage.next_action;
            })()}</p>
          <button className="primary" disabled={locked} onClick={() => openChat(latest.id)}>Continue <Icon name="chevronRight"/></button>
          {stageFeedback.length
            ? <p className="supporting">Saved feedback for this stage: {stageFeedback.join(' · ')}</p> : null}
          {skills ? <p className="supporting">Strongest skill: {skills.strongest}. Next to grow: {skills.grow}.</p> : null}
        </div> : null}
        {recap ? <section className="milestone-recap" aria-label="Milestone recap">
          <h3>Milestone: {recap.stage_label} confirmed</h3>
          {recap.accomplishments ? <p>{recap.accomplishments}</p> : null}
          {recap.changes ? <p>What changed: {recap.changes}</p> : null}
          {recap.gaps.length ? <p className="supporting">Still open: {recap.gaps.join(' · ')}</p> : null}
          <p className="supporting">Next: {recap.next_action}</p>
        </section> : null}
        {projectNotebookId ? <section className="recent-work" aria-label="Recent work">
          <h3>Recent work</h3>
          {artifacts === null ? null : artifacts.length
            ? <ul>{artifacts.map(entry => <li key={entry.id}>
                <button disabled={locked || !openArtifact}
                  onClick={() => openArtifact?.(projectNotebookId, entry.id)}>
                  <Icon name="document"/><span>{entry.title}</span>
                  <time>{relativeTime(entry.updated_at)}</time>
                </button>
              </li>)}</ul>
            : <p className="supporting">No documents yet. Create one from your notebook.</p>}
          {canvases === null ? null : canvases.length
            ? <ul>{canvases.map(entry => <li key={entry.id}>
                <button disabled={locked || !openCanvas}
                  onClick={() => openCanvas?.(projectNotebookId, entry.id)}>
                  <Icon name="panel"/><span>{entry.title}</span>
                  <time>{relativeTime(entry.updated_at)}</time>
                </button>
              </li>)}</ul>
            : <p className="supporting">No canvases yet. Map your reasoning from your notebook.</p>}
        </section> : null}
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
          <button aria-describedby="home-improve-description" disabled={locked} onClick={() => startChat('improve')}>Improve my design</button>
        </div>
        <p id="home-improve-description" className="supporting">Get feedback on a design you already have.</p>
      </section>
    </>}
    <p className="supporting privacy-note">Your work here is not graded.</p>
  </section>;
}

function lastActive(summary: ChatSummary | undefined, folder: string | undefined) {
  const when = relativeTime(summary?.activity_at);
  return [when ? `Last active ${when}` : 'Your latest chat', folder ? `in ${folder}` : ''].filter(Boolean).join(' ');
}

/** Bounded AI-generated work-on text: the saved coach rationale, never re-generated on page load. */
function bounded(text: string): string {
  const trimmed = text.split(/\s+/).filter(Boolean).join(' ').trim();
  return trimmed.length > 160 ? `${trimmed.slice(0, 157).trimEnd()}…` : trimmed;
}
