/** Canonical saved-work view; eligibility and next actions come only from the API. */
import { useRef, useState, type ReactNode } from 'react';
import type { Project, ReviewFeedback, Stage } from './api';
import { CoachText } from './CoachText';
import { Icon } from './Icon';
import { buildScaffold, improveScaffold, practiceScaffold, skillExplanation, skillLevel, skillSummary, skillTip } from './coachingContent';

const reviewTabs = ['Summary', 'Progression'] as const;

/** Show saved feedback and the explicit Thinking Path actions for this chat. */
export function ThinkingPath({ project, disabled, act, startInChat, onClose, status, children, insertScaffold, initialTab }: {
  project: Project; disabled: boolean; insertScaffold: (text: string, switchTo?: 'project') => void; initialTab?: (typeof reviewTabs)[number]; act: (route: string, body: object) => Promise<void>;
  startInChat: () => void; onClose: () => void; status: string; children: ReactNode;
}) {
  const [activeTab, setActiveTab] = useState<(typeof reviewTabs)[number]>(
    initialTab ?? (project.pending ? 'Progression' : 'Summary'),
  );
  const tabButtons = useRef<Array<HTMLButtonElement | null>>([]);
  const [opened, setOpened] = useState('');
  const [heroOpen, setHeroOpen] = useState(false);
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
  function selectTab(tab: (typeof reviewTabs)[number], button: HTMLButtonElement) {
    if (tab === activeTab) return;
    setActiveTab(tab);
    button.closest('dialog')?.scrollTo({ top: 0 });
    button.focus({ preventScroll: true });
  }

  return <section className="thinking-path">
    <div className="review-toolbar">
      <header className="review-header">
        <h2 id="review-heading" tabIndex={-1}>Review</h2>
        <button className="icon-button" aria-label="Close Review" title="Close Review" onClick={onClose}><Icon name="close"/></button>
      </header>
      <div className="review-tabs" role="tablist" aria-label="Review views">
        {reviewTabs.map((tab, index) => {
          const id = tab.toLowerCase();
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
              const next = event.key === 'Home' ? 0 : event.key === 'End' ? reviewTabs.length - 1 : 1 - index;
              const button = tabButtons.current[next];
              if (button) selectTab(reviewTabs[next], button);
            }}>
            {tab}{pendingDecision ? <span className="decision-dot" aria-hidden="true"/> : null}
          </button>;
        })}
      </div>
    </div>
    <p className="review-status supporting" role="status">{status}</p>
    {children}
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
            const count = stage.student_work.length;
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
                {expanded ? <StageDetail stage={stage} isCurrent={isCurrent} disabled={disabled}
                  onSelect={() => void decide('select-stage', { stage_id: stage.id })}/> : null}
              </section>
            </li>;
          })}
        </ol>
      </section>
    </section>
  </section>;
}

const WORK_PREVIEW = 1;

/** Compact stage detail: next action, coach summary, and a short preview of the student's own work. */
function StageDetail({ stage, isCurrent, disabled, onSelect }: { stage: Stage; isCurrent: boolean; disabled: boolean; onSelect: () => void }) {
  const [allWork, setAllWork] = useState(false);
  const [summaryOpen, setSummaryOpen] = useState(false);
  const newestFirst = [...stage.student_work].reverse();
  const work = allWork ? newestFirst : newestFirst.slice(0, WORK_PREVIEW);
  const extra = stage.student_work.length - WORK_PREVIEW;
  const longSummary = stage.coach_summary.length > 220;
  const actionLabel = stage.completed ? 'Revisit' : 'Continue';
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
    <div className="stage-block">
      <h4>Your work</h4>
      {work.length ? <ul className="work-list" data-scroll={allWork || undefined} tabIndex={allWork ? 0 : undefined} aria-label={allWork ? 'All your work in this stage' : undefined}>{work.map(item => <li key={item.message_id} className="work-quote" data-open={allWork || undefined}>{item.text}</li>)}</ul>
        : <p className="supporting">Work you share in Design coaching will appear here.</p>}
      {extra > 0 ? <button className="card-link" aria-expanded={allWork} onClick={() => setAllWork(open => !open)}>
        {allWork ? 'Show less' : `Show all ${stage.student_work.length}`}</button> : null}
    </div>
  </div>;
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
