/** Canonical saved-work view; eligibility and next actions come only from the API. */
import { useEffect, useRef, useState, type ReactNode } from 'react';
import type { Project, ReviewFeedback, Stage } from './api';
import { CoachText } from './CoachText';
import { Icon } from './Icon';
import { downloadProject } from './projectExport';
import { buildScaffold, improveScaffold, isStudentWork, practiceScaffold, courseTools, skillExplanation, skillLevel, skillSummary, skillTip } from './coachingContent';

const reviewTabs = ['Progression', 'Summary', 'My work'] as const;
export type ReviewTab = (typeof reviewTabs)[number];
const tabSlug = (tab: ReviewTab) => tab.toLowerCase().replace(/\s+/g, '-');

/** Show saved feedback and the explicit Thinking Path actions for this chat. */
export function ThinkingPath({ project, title, disabled, act, startInChat, onClose, status, children, insertScaffold, initialTab }: {
  project: Project; title: string; disabled: boolean; insertScaffold: (text: string, switchTo?: 'project') => void; initialTab?: ReviewTab; act: (route: string, body: object) => Promise<void>;
  startInChat: () => void; onClose: () => void; status: string; children: ReactNode;
}) {
  const [activeTab, setActiveTab] = useState<ReviewTab>(initialTab ?? 'Progression');
  const tabButtons = useRef<Array<HTMLButtonElement | null>>([]);
  const [opened, setOpened] = useState('');
  const [workFocus, setWorkFocus] = useState<{ id: string; n: number }>();
  const [heroOpen, setHeroOpen] = useState(false);
  const [saved, setSaved] = useState('');
  const savedTimer = useRef(0);
  // A newer project status, or a new action starting, replaces the short-lived download note.
  useEffect(() => { window.clearTimeout(savedTimer.current); setSaved(''); }, [status, disabled]);
  const [showTips, setShowTips] = useState(false);
  const current = project.stages.find(stage => stage.id === project.current_stage)!;
  const done = project.stages.filter(stage => stage.completed).length;
  const pending = project.pending;
  const review = project.review;
  const scores = review?.facione_scores ?? [];
  const skills = skillSummary(scores);
  const stageIndex = project.stages.findIndex(stage => stage.id === current.id);
  const summaryText = review?.summary || current.coach_summary || '';
  const longSummary = summaryText.length > 260;
  async function decide(route: string, body: object) {
    await act(route, body);
    document.getElementById('review-heading')?.focus({ preventScroll: true });
  }
  function selectTab(tab: ReviewTab, button: HTMLButtonElement) {
    if (tab === activeTab) return;
    setActiveTab(tab);
    button.closest('dialog')?.scrollTo({ top: 0 });
    button.focus({ preventScroll: true });
  }

  return <section className="thinking-path">
    <div className="review-toolbar">
      <header className="review-header">
        <h2 id="review-heading" tabIndex={-1}>Review</h2>
        <div className="review-header-actions">
          <button className="icon-button" aria-label="Download project summary" title="Download project summary"
            onClick={() => { downloadProject(project, title); setSaved('Project summary downloaded.'); window.clearTimeout(savedTimer.current); savedTimer.current = window.setTimeout(() => setSaved(''), 4000); }}><Icon name="download"/></button>
          <button className="icon-button" aria-label="Close Review" title="Close Review" onClick={onClose}><Icon name="close"/></button>
        </div>
      </header>
      <div className="review-tabs" role="tablist" aria-label="Review views">
        {reviewTabs.map((tab, index) => {
          const id = tabSlug(tab);
          const selected = activeTab === tab;
          const pendingDecision = tab === 'Progression' && pending;
          return <button key={tab} ref={button => { tabButtons.current[index] = button; }}
            type="button" role="tab" id={`review-tab-${id}`} aria-controls={`review-panel-${id}`}
            aria-selected={selected} tabIndex={selected ? 0 : -1}
            aria-description={pendingDecision ? 'Stage decision pending' : undefined}
            onClick={event => selectTab(tab, event.currentTarget)}
            onKeyDown={event => {
              if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
              event.preventDefault();
              const last = reviewTabs.length - 1;
              const next = event.key === 'Home' ? 0 : event.key === 'End' ? last : event.key === 'ArrowRight' ? (index === last ? 0 : index + 1) : (index === 0 ? last : index - 1);
              const button = tabButtons.current[next];
              if (button) selectTab(reviewTabs[next], button);
            }}>
            {tab}{pendingDecision ? <span className="decision-dot" aria-hidden="true"/> : null}
          </button>;
        })}
      </div>
    </div>
    <p className="review-status supporting" role="status">{saved || status}</p>
    {children}
    <section id="review-panel-progression" role="tabpanel" aria-labelledby="review-tab-progression"
      hidden={activeTab !== 'Progression'} tabIndex={0}>
      {pending ? <section className="review-card recommendation-card" aria-labelledby="recommendation-title">
        <p className="hero-eyebrow">Decision needed</p>
        <h3 id="recommendation-title" className="hero-title">Ready for {project.stages.find(stage => stage.id === pending.to_stage)?.label}?</h3>
        <p className="next-text">{pending.rationale}</p>
        <p className="supporting">You stay in {current.label} until you confirm.</p>
        <div className="stage-actions">
          <button className="primary" disabled={disabled} onClick={() => void decide(`resolve/${encodeURIComponent(pending.id)}`, { accepted: true })}>Confirm next stage</button>
          <button disabled={disabled} onClick={() => void decide(`resolve/${encodeURIComponent(pending.id)}`, { accepted: false })}>Stay here</button>
        </div>
      </section> : null}
      <section className="review-card" aria-labelledby="path-title">
        <header className="card-head">
          <span className="card-icon" aria-hidden="true"><Icon name="path"/></span>
          <h3 id="path-title">All stages</h3>
        </header>
        <ol aria-label="Thinking Path stages" className="stage-list">
          {project.stages.map((stage, index) => {
            const isCurrent = stage.id === current.id;
            const expanded = opened === stage.id;
            const count = stage.student_work.filter(item => isStudentWork(item.text)).length;
            const caption = [isCurrent ? 'Current' : stage.completed ? 'Done' : '', count ? `${count} ${count === 1 ? 'contribution' : 'contributions'}` : '']
              .filter(Boolean).join(' · ');
            return <li key={stage.id} className={isCurrent ? 'current-stage' : ''}>
              <button className="stage-row" aria-current={isCurrent ? 'step' : undefined} aria-expanded={expanded} aria-controls={`stage-work-${stage.id}`} onClick={() => setOpened(expanded ? '' : stage.id)}>
                <span className={`stage-number ${stage.completed ? 'completed' : ''}`} aria-hidden="true">{stage.completed ? <Icon name="check"/> : index + 1}</span>
                <span className="stage-label">{stage.label}{stage.completed ? <span className="sr-only"> (completed)</span> : null}
                  {caption ? <small className="stage-count">{caption}</small> : null}</span>
                <Icon name={expanded ? 'chevronDown' : 'chevronRight'}/>
              </button>
              <section hidden={!expanded} id={`stage-work-${stage.id}`} className="stage-work" aria-label={`${stage.label} saved work`}>
                {expanded ? <StageDetail stage={stage} isCurrent={isCurrent} disabled={disabled} onUseTool={text => insertScaffold(text, 'project')} onSeeWork={() => { setActiveTab('My work'); setWorkFocus(value => ({ id: stage.id, n: (value?.n ?? 0) + 1 })); }}
                  onSelect={() => void decide('select-stage', { stage_id: stage.id })}/> : null}
              </section>
            </li>;
          })}
        </ol>
      </section>
    </section>
    <section id="review-panel-summary" role="tabpanel" aria-labelledby="review-tab-summary"
      hidden={activeTab !== 'Summary'} tabIndex={0}>
      <section className="review-card review-hero" aria-labelledby="review-summary">
        <p className="hero-eyebrow">Stage {stageIndex + 1} of {project.stages.length}</p>
        <div className="hero-steps" aria-hidden="true">
          {project.stages.map(stage => <span key={stage.id} data-state={stage.id === current.id ? 'current' : stage.completed ? 'done' : undefined}/>)}
        </div>
        <h3 id="review-summary" className="hero-title">{current.label}</h3>
        {summaryText
          ? <div id="hero-summary" className="hero-summary" data-clamped={(longSummary && !heroOpen) || undefined}><CoachText text={summaryText}/></div>
          : <p className="supporting">A summary will appear after the coach has reviewed your design reasoning.</p>}
        {longSummary ? <button className="card-link" aria-expanded={heroOpen} aria-controls="hero-summary" onClick={() => setHeroOpen(open => !open)}>
          {heroOpen ? 'Show less' : 'Read more'}</button> : null}
      </section>
      <FeedbackCard tone="strength" title="Strengths" icon="check" groups={review?.strengths ?? []} stages={project.stages} currentStage={current.id}
        action="Build on this" empty="Strengths will show up after the coach reviews your work." onAct={item => insertScaffold(buildScaffold(item), 'project')}/>
      <FeedbackCard tone="improve" title="Areas to improve" icon="arrow" groups={review?.improvements ?? []} stages={project.stages} currentStage={current.id}
        action="Work on this" empty="Ideas to work on will show up after the coach reviews your work." onAct={item => insertScaffold(improveScaffold(item), 'project')}/>
      <section className="review-card" aria-labelledby="review-facione">
        <header className="card-head">
          <span className="card-icon" aria-hidden="true"><Icon name="spark"/></span>
          <h3 id="review-facione">How your idea scores</h3>
          {skills ? <button className="card-link card-head-action" aria-pressed={showTips} onClick={() => setShowTips(show => !show)}>{showTips ? 'Hide tips' : 'Show tips'}</button> : null}
        </header>
        <p className="supporting">Feedback on your critical thinking, not a grade.{skills ? ' Tips are a general guide for each score.' : ''}</p>
        {skills ? <div className="skill-highlights">
          {skills.strongest !== skills.grow ? <p className="skill-strong-line">
            <span className="skill-tile-label">Strongest</span>
            <strong>{skills.strongest}</strong>
            <span className="skill-tile-score">{skillLevel(skills.strongestScore)} · {skills.strongestScore}/4</span>
          </p> : null}
          <div className="skill-tile grow">
            <div className="skill-grow-main">
              <span className="skill-tile-label">{skills.strongest !== skills.grow ? 'Grow next' : 'Keep building'}</span>
              <strong>{skills.grow}</strong>
              <span className="skill-tile-score">{skillLevel(skills.growScore)} · {skills.growScore}/4</span>
              <span className="skill-tile-tip">{skillTip(skills.grow, skills.growScore)}</span>
            </div>
            <button disabled={disabled} onClick={() => insertScaffold(practiceScaffold(skills.grow), 'project')}>Practice this</button>
          </div>
        </div> : <p className="skill-empty">Your skill scores will appear here as you share your thinking with the coach.</p>}
        {scores.length ? skills ? <ul className="skill-list">
          {scores.map(item => <li key={item.dimension} className="skill-row" data-unassessed={item.score === null || undefined}>
            <div className="skill-head">
              <strong>{item.dimension}</strong>
              {item.score === null ? <span className="skill-value"><span aria-hidden="true">–</span><span className="sr-only">Not yet assessed</span></span>
                : <span className="skill-value"><span className="skill-level">{skillLevel(item.score)}</span> {item.score}/4</span>}
            </div>
            <div className="skill-pips" aria-hidden="true">{[1, 2, 3, 4].map(step => <span key={step} data-on={(item.score ?? 0) >= step || undefined}/>)}</div>
            {showTips ? <p className="skill-note" title={skillExplanation(item.dimension) || undefined}>
              {item.score !== null ? skillTip(item.dimension, item.score) : skillExplanation(item.dimension)}</p> : null}
          </li>)}
        </ul> : <details className="review-disclosure">
          <summary>The six skills</summary>
          <ul className="skill-glossary">
            {scores.map(item => <li key={item.dimension}><strong>{item.dimension}</strong>{skillExplanation(item.dimension) ? <span>{skillExplanation(item.dimension)}</span> : null}</li>)}
          </ul>
        </details> : null}
      </section>
    </section>
    <section id="review-panel-my-work" role="tabpanel" aria-labelledby="review-tab-my-work"
      hidden={activeTab !== 'My work'} tabIndex={0}>
      <MyWork project={project} focus={workFocus}/>
    </section>
  </section>;
}

/** Compact stage detail: next action, a short coach summary, a link to the saved work, and course tools one tap away. */
function StageDetail({ stage, isCurrent, disabled, onSelect, onUseTool, onSeeWork }: { stage: Stage; isCurrent: boolean; disabled: boolean; onSelect: () => void; onUseTool: (text: string) => void; onSeeWork: () => void }) {
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [toolsOpen, setToolsOpen] = useState(false);
  const workCount = stage.student_work.filter(item => isStudentWork(item.text)).length;
  const longSummary = stage.coach_summary.length > 220;
  const actionLabel = stage.completed ? 'Revisit' : 'Continue';
  const showTools = isCurrent || stage.selectable;
  const tools = showTools ? courseTools(stage.id) : [];
  return <div className="stage-detail">
    <p className="stage-next">{stage.next_action}</p>
    {!isCurrent && !stage.selectable ? <p className="supporting">Not available yet.</p> : null}
    {!isCurrent && stage.selectable ? <button className="stage-continue" aria-label={`${actionLabel} ${stage.label}`} disabled={disabled} onClick={onSelect}>
      {actionLabel} <Icon name="chevronRight"/></button> : null}
    {stage.coach_summary ? <div className="stage-block">
      <h4>Coach summary</h4>
      <div className="stage-summary" id={`stage-summary-${stage.id}`} data-clamped={(longSummary && !summaryOpen) || undefined}><CoachText text={stage.coach_summary}/></div>
      {longSummary ? <button className="card-link" aria-expanded={summaryOpen} aria-controls={`stage-summary-${stage.id}`} onClick={() => setSummaryOpen(open => !open)}>
        {summaryOpen ? 'Show less' : 'Read more'}</button> : null}
    </div> : null}
    {workCount ? <button className="card-link stage-work-link" onClick={onSeeWork}>Your work · {workCount}<Icon name="chevronRight"/></button> : null}
    {tools.length ? <div className="stage-block">
      <button className="tool-toggle" aria-expanded={toolsOpen} aria-controls={`stage-tools-${stage.id}`} onClick={() => setToolsOpen(open => !open)}>
        <span>Tools from the course</span><small>{tools.length}</small><Icon name={toolsOpen ? 'chevronDown' : 'chevronRight'}/></button>
      <ul className="tool-list" id={`stage-tools-${stage.id}`} hidden={!toolsOpen}>{tools.map(tool => <li key={tool.label}>
        <button className="tool-chip" disabled={disabled} onClick={() => onUseTool(tool.text)}>
          {tool.label}{tool.week ? <small>{tool.week}</small> : null}</button></li>)}</ul>
    </div> : null}
  </div>;
}

/** Where a stage stands, in the words a student would use. */
function stageStatus(stage: Stage, currentId: string, shared: number): { label: string; tone: 'current' | 'done' | 'started' | 'idle' } {
  if (stage.id === currentId) return { label: 'Current', tone: 'current' };
  if (stage.completed) return { label: 'Done', tone: 'done' };
  return shared ? { label: 'Started', tone: 'started' } : { label: 'Not started', tone: 'idle' };
}

/** One stage of the journey: what the student shared, what the coach summarised, and what is going well or next. */
function JourneyStage({ stage, index, status, open, onToggle, shared, strengths, improvements }: {
  stage: Stage; index: number; status: ReturnType<typeof stageStatus>; open: boolean; onToggle: () => void;
  shared: { message_id: string; text: string }[]; strengths: string[]; improvements: string[];
}) {
  const bodyId = `journey-${stage.id}`;
  const empty = !shared.length && !stage.coach_summary && !strengths.length && !improvements.length;
  return <li id={`journey-stage-${stage.id}`} className="journey-stage" data-status={status.tone}>
    <button className="journey-head" aria-expanded={open} aria-controls={bodyId} onClick={onToggle}>
      <span className={`stage-number ${stage.completed ? 'completed' : ''}`} aria-hidden="true">{stage.completed ? <Icon name="check"/> : index + 1}</span>
      <span className="journey-title">
        <strong>{stage.label}</strong>
        <small>{stage.artifact_label}</small>
      </span>
      <span className="journey-side">
        <span className="journey-badge" data-tone={status.tone}>{status.label}</span>
        {shared.length ? <small>{shared.length} {shared.length === 1 ? 'entry' : 'entries'}</small> : null}
      </span>
      <Icon name={open ? 'chevronDown' : 'chevronRight'}/>
    </button>
    <div id={bodyId} className="journey-body" hidden={!open}>
      {empty ? <p className="supporting">Nothing shared in this stage yet.</p> : null}
      {shared.length ? <section aria-label={`What you shared in ${stage.label}`}>
        <h4 className="journey-label">What you shared</h4>
        <ol className="journey-entries">{shared.map((item, position) => <li key={item.message_id} className="journey-entry">
          <span className="journey-step" aria-hidden="true">{position + 1}</span>
          <p>{item.text.trim()}</p>
        </li>)}</ol>
      </section> : null}
      {stage.coach_summary ? <section aria-label={`Coach summary for ${stage.label}`}>
        <h4 className="journey-label">Coach summary</h4>
        <div className="journey-summary"><CoachText text={stage.coach_summary}/></div>
      </section> : null}
      {strengths.length ? <section aria-label={`Going well in ${stage.label}`}>
        <h4 className="journey-label tone-strength">Going well</h4>
        <ul className="journey-points tone-strength">{strengths.map(item => <li key={item}><Icon name="check"/><span>{item}</span></li>)}</ul>
      </section> : null}
      {improvements.length ? <section aria-label={`To work on in ${stage.label}`}>
        <h4 className="journey-label tone-improve">To work on</h4>
        <ul className="journey-points tone-improve">{improvements.map(item => <li key={item}><Icon name="arrow"/><span>{item}</span></li>)}</ul>
      </section> : null}
    </div>
  </li>;
}

/**
 * The student's whole journey, stage by stage, in order. Each stage folds so a long project stays easy to scan:
 * the current stage opens first, and "Expand all" opens everything.
 */
function MyWork({ project, focus }: { project: Project; focus?: { id: string; n: number } }) {
  const review = project.review;
  const rows = project.stages.map((stage, index) => {
    const shared = stage.student_work.filter(item => isStudentWork(item.text));
    return {
      stage, index, shared,
      status: stageStatus(stage, project.current_stage, shared.length),
      strengths: review?.strengths.find(group => group.stage_id === stage.id)?.items ?? [],
      improvements: review?.improvements.find(group => group.stage_id === stage.id)?.items ?? [],
    };
  });
  const [open, setOpen] = useState<Record<string, boolean>>(() => ({ [project.current_stage]: true }));
  const total = rows.reduce((sum, row) => sum + row.shared.length, 0);
  const done = rows.filter(row => row.stage.completed).length;
  const allOpen = rows.every(row => open[row.stage.id]);
  const handled = useRef(0);
  // "Your work" on a stage in Progression opens that stage here and brings it into view.
  useEffect(() => {
    if (!focus || focus.n === handled.current) return;
    handled.current = focus.n;
    setOpen(value => ({ ...value, [focus.id]: true }));
    window.requestAnimationFrame(() => document.getElementById(`journey-stage-${focus.id}`)?.scrollIntoView({ block: 'start' }));
  }, [focus]);
  return <section className="review-card journey" aria-labelledby="my-work-title">
    <header className="card-head">
      <span className="card-icon" aria-hidden="true"><Icon name="chat"/></span>
      <h3 id="my-work-title">My work</h3>
      <button className="card-link card-head-action" aria-pressed={allOpen}
        onClick={() => setOpen(allOpen ? { [project.current_stage]: true } : Object.fromEntries(rows.map(row => [row.stage.id, true])))}>
        {allOpen ? 'Collapse all' : 'Expand all'}</button>
    </header>
    <p className="supporting">Your progress, stage by stage. {done} of {rows.length} stages done · {total} {total === 1 ? 'entry' : 'entries'} shared.</p>
    <div className="hero-steps" aria-hidden="true">
      {rows.map(row => <span key={row.stage.id} data-state={row.status.tone === 'current' ? 'current' : row.stage.completed ? 'done' : undefined}/>)}
    </div>
    <ol className="journey-list" aria-label="Stages">
      {rows.map(row => <JourneyStage key={row.stage.id} {...row} open={!!open[row.stage.id]}
        onToggle={() => setOpen(value => ({ ...value, [row.stage.id]: !value[row.stage.id] }))}/>)}
    </ol>
  </section>;
}

interface FeedbackEntry { text: string; stageIds: string[] }

/** Merge repeated sentences across stages, with the current stage first and then the latest stages. */
function feedbackEntries(groups: ReviewFeedback[], currentStage: string): FeedbackEntry[] {
  const populated = groups.filter(group => group.items.length);
  const ordered = [...populated.filter(group => group.stage_id === currentStage),
    ...populated.filter(group => group.stage_id !== currentStage).reverse()];
  const merged = new Map<string, FeedbackEntry>();
  for (const group of ordered) {
    for (const raw of group.items) {
      const text = raw.trim();
      const entry = merged.get(text.toLowerCase());
      if (!entry) merged.set(text.toLowerCase(), { text, stageIds: [group.stage_id] });
      else if (!entry.stageIds.includes(group.stage_id)) entry.stageIds.push(group.stage_id);
    }
  }
  return [...merged.values()];
}

const FEEDBACK_PREVIEW = 2;

/** Show the top feedback in a card, with identical sentences merged and the rest one click away. */
function FeedbackCard({ tone, title, icon, groups, stages, currentStage, action, empty, onAct }: {
  tone: 'strength' | 'improve'; title: string; icon: 'check' | 'arrow'; groups: ReviewFeedback[]; stages: Stage[];
  currentStage: string; action: string; empty: string; onAct: (item: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const entries = feedbackEntries(groups, currentStage);
  const visible = expanded ? entries : entries.slice(0, FEEDBACK_PREVIEW);
  const hidden = entries.length - FEEDBACK_PREVIEW;
  const listId = `feedback-${tone}`;
  const stageName = (id: string) => id === currentStage ? '' : stages.find(stage => stage.id === id)?.label ?? '';
  const caption = (ids: string[]) => ids.length > 2 ? `${ids.length} stages` : ids.map(stageName).filter(Boolean).join(' · ');
  return <section className={`review-card tone-${tone}`} aria-labelledby={`${listId}-title`}>
    <header className="card-head">
      <span className="card-icon" aria-hidden="true"><Icon name={icon}/></span>
      <h3 id={`${listId}-title`}>{title}</h3>
      {entries.length ? <span className="card-count" aria-label={`${entries.length} ${entries.length === 1 ? 'item' : 'items'}`}>{entries.length}</span> : null}
    </header>
    {entries.length ? <ul id={listId} className="fb-list" data-expanded={expanded || undefined} tabIndex={expanded ? 0 : undefined}>
      {visible.map(entry => <li key={entry.text} className="fb-item">
        <p className="fb-text">{entry.text}</p>
        <div className="fb-meta">
          {caption(entry.stageIds) ? <span className="fb-stage">{caption(entry.stageIds)}</span> : null}
          <button className="scaffold-action fb-act" aria-label={`${action}: ${entry.text}`} onClick={() => onAct(entry.text)}>{action}<Icon name="chevronRight"/></button>
        </div>
      </li>)}
    </ul> : <p className="supporting fb-empty">{empty}</p>}
    {hidden > 0 ? <button className="card-link" aria-expanded={expanded} aria-controls={listId} onClick={() => setExpanded(open => !open)}>
      {expanded ? 'Show less' : `Show ${hidden} more`}</button> : null}
  </section>;
}
