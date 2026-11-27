/** Canonical saved-work view; eligibility and next actions come only from the API. */
import { useEffect, useRef, useState, type ReactNode } from 'react';
import type { Bookmark, Project, ProjectBriefResult, Stage } from './api';
import { ProjectBriefCard } from './ProjectBrief';
import { CoachText } from './CoachText';
import { Icon } from './Icon';
import { downloadProject } from './projectExport';
import { isStudentWork, practiceScaffold, courseTools, skillExplanation, skillLevel, skillSummary, skillTip } from './coachingContent';

const reviewTabs = ['Progression', 'Summary', 'My work'] as const;
export type ReviewTab = (typeof reviewTabs)[number];
const tabSlug = (tab: ReviewTab) => tab.toLowerCase().replace(/\s+/g, '-');

/** Show saved feedback and the explicit Thinking Path actions for this chat. */
export function ThinkingPath({ projectMode = true, project, title, disabled, act, startInChat: _startInChat, onClose, status, children, insertScaffold, initialTab, onTabChange, bookmarks, bookmarkError, bookmarksReady, refreshBookmarks, removeStar, jumpToMessage }: {
  jumpToMessage: (id: string) => void; bookmarks: Bookmark[]; bookmarkError: string; bookmarksReady: boolean; refreshBookmarks: () => void; removeStar: (id: string) => void;
  projectMode?: boolean;
  project: Project; title: string; disabled: boolean; insertScaffold: (text: string, switchTo?: 'project') => void; initialTab?: ReviewTab; onTabChange: (tab: ReviewTab) => void; act: (route: string, body: object) => Promise<void>;
  startInChat: () => void; onClose: () => void; status: string; children: ReactNode;
}) {
  const [activeTab, setActiveTab] = useState<ReviewTab>(initialTab ?? 'Progression');
  const tabButtons = useRef<Array<HTMLButtonElement | null>>([]);
  const [opened, setOpened] = useState('');
  const [workFocus, setWorkFocus] = useState<{ id: string; n: number }>();
  const [saved, setSaved] = useState('');
  const savedTimer = useRef(0);
  // A newer project status, or a new action starting, replaces the short-lived download note.
  useEffect(() => { window.clearTimeout(savedTimer.current); setSaved(''); }, [status, disabled]);
  const [showTips, setShowTips] = useState(false);
  const current = project.stages.find(stage => stage.id === project.current_stage)!;
  const pending = project.pending;
  const review = project.review;
  const [generatedBrief, setGeneratedBrief] = useState<ProjectBriefResult | null>(null);
  const downloadView = generatedBrief && review && generatedBrief.version === review.project_brief?.version
    ? { ...project, review: { ...review, project_brief: generatedBrief } } : project;
  const scores = review?.facione_scores ?? [];
  const skills = skillSummary(scores);
  async function decide(route: string, body: object) {
    await act(route, body);
    document.getElementById('review-heading')?.focus({ preventScroll: true });
  }
  function selectTab(tab: ReviewTab, button: HTMLButtonElement) {
    if (tab === activeTab) return;
    setActiveTab(tab);
    onTabChange(tab);
    button.closest('dialog')?.scrollTo({ top: 0 });
    button.focus({ preventScroll: true });
  }

  return <section className="thinking-path">
    <div className="review-toolbar">
      <header className="review-header">
        <h2 id="review-heading" tabIndex={-1}>Review</h2>
        <div className="review-header-actions">
          {projectMode ? <button className="icon-button" aria-label="Download project summary" title="Download project summary"
            onClick={() => { downloadProject(downloadView, title); setSaved('Project summary downloaded.'); window.clearTimeout(savedTimer.current); savedTimer.current = window.setTimeout(() => setSaved(''), 4000); }}><Icon name="download"/></button> : null}
          <button className="icon-button" aria-label="Close Review" title="Close Review" onClick={onClose}><Icon name="close"/></button>
        </div>
      </header>
      {projectMode ? <div className="review-tabs" role="tablist" aria-label="Review views">
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
      </div> : null}
    </div>
    <p className="review-status supporting" role="status">{(projectMode && saved) || status}</p>
    {children}
    {projectMode ? <>
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
                {expanded ? <StageDetail bookmarkCount={bookmarks.filter(item => item.stage_id === stage.id).length} stage={stage} isCurrent={isCurrent} disabled={disabled} onUseTool={text => insertScaffold(text, 'project')} onSeeWork={() => { setActiveTab('My work'); onTabChange('My work'); setWorkFocus(value => ({ id: stage.id, n: (value?.n ?? 0) + 1 })); }}
                  onSelect={() => void decide('select-stage', { stage_id: stage.id })}/> : null}
              </section>
            </li>;
          })}
        </ol>
      </section>
    </section>
    <section id="review-panel-summary" role="tabpanel" aria-labelledby="review-tab-summary"
      hidden={activeTab !== 'Summary'} tabIndex={0}>
      <ProjectBriefCard project={project} disabled={disabled} onSaved={setGeneratedBrief}/>
      <section className="review-card summary-feedback-list" aria-labelledby="summary-feedback-title">
        <h3 id="summary-feedback-title">Stage feedback</h3>
        {project.stages.map(stage => <StageFeedback key={stage.id} stage={stage} review={review}/>)}
      </section>
      <section className="review-card" aria-labelledby="review-facione">
        <header className="card-head">
          <span className="card-icon" aria-hidden="true"><Icon name="spark"/></span>
          <h3 id="review-facione">How your idea scores</h3>
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
        {scores.length ? skills ? <details className="review-disclosure skill-detail-disclosure">
          <summary>All six skill scores</summary>
          <button className="card-link" aria-pressed={showTips} onClick={() => setShowTips(show => !show)}>{showTips ? 'Hide tips' : 'Show tips'}</button>
          <ul className="skill-list">
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
        </ul></details> : <details className="review-disclosure">
          <summary>The six skills</summary>
          <ul className="skill-glossary">
            {scores.map(item => <li key={item.dimension}><strong>{item.dimension}</strong>{skillExplanation(item.dimension) ? <span>{skillExplanation(item.dimension)}</span> : null}</li>)}
          </ul>
        </details> : null}
      </section>
    </section>
    </> : null}
    <div id="review-panel-my-work" role={projectMode ? 'tabpanel' : undefined} aria-labelledby={projectMode ? 'review-tab-my-work' : undefined}
      hidden={projectMode && activeTab !== 'My work'} tabIndex={projectMode ? 0 : undefined}>
      <MyWork project={project} groupByStage={projectMode} focus={workFocus} bookmarks={bookmarks} disabled={disabled} error={bookmarkError} ready={bookmarksReady} refresh={refreshBookmarks} removeStar={removeStar} jumpToMessage={jumpToMessage}/>
    </div>
  </section>;
}

/** Independently disclose saved stage feedback without changing its wording or assessment. */
function StageFeedback({ stage, review }: { stage: Stage; review: Project['review'] }) {
  const [open, setOpen] = useState(false);
  const [groups, setGroups] = useState({ strengths: true, improvements: true });
  const feedback = {
    strengths: review?.strengths.find(group => group.stage_id === stage.id)?.items ?? [],
    improvements: review?.improvements.find(group => group.stage_id === stage.id)?.items ?? [],
  };
  const caption = feedback.strengths.length || feedback.improvements.length
    ? <><span className="feedback-count tone-strength">{feedback.strengths.length} going well</span>{' · '}<span className="feedback-count tone-improve">{feedback.improvements.length} to work on</span></>
    : 'No saved feedback yet';
  return <section className="stage-feedback" aria-labelledby={`summary-stage-${stage.id}`}>
    <h4><button id={`summary-stage-${stage.id}`} className="feedback-toggle" aria-label={stage.label} aria-describedby={`summary-feedback-count-${stage.id}`} aria-expanded={open}
      aria-controls={`summary-feedback-${stage.id}`} onClick={() => setOpen(value => !value)}>
      <span className="feedback-stage-label"><span>{stage.label}</span><small id={`summary-feedback-count-${stage.id}`}>{caption}</small></span><Icon name={open ? 'chevronDown' : 'chevronRight'}/>
    </button></h4>
    <div id={`summary-feedback-${stage.id}`} hidden={!open}>
      {(['strengths', 'improvements'] as const).map(field => {
        const label = field === 'strengths' ? 'Going well' : 'To work on';
        const tone = field === 'strengths' ? 'strength' : 'improve';
        const items = feedback[field];
        const id = `summary-${field}-${stage.id}`;
        return <div className="feedback-group" key={field}>
          <h5><button className={`feedback-toggle journey-label tone-${tone}`} aria-expanded={groups[field]}
            aria-controls={id} onClick={() => setGroups(value => ({ ...value, [field]: !value[field] }))}>
            <span>{label}</span><Icon name={groups[field] ? 'chevronDown' : 'chevronRight'}/>
          </button></h5>
          <section id={id} hidden={!groups[field]} aria-label={`${label} in ${stage.label}`}>
            {items.length ? <ul className={`journey-points tone-${tone}`}>{items.map(item => <li key={item}>
              <Icon name={field === 'strengths' ? 'check' : 'arrow'}/><span>{item}</span>
            </li>)}</ul> : <p className="supporting">No saved {label} feedback for this stage yet.</p>}
          </section>
        </div>;
      })}
    </div>
  </section>;
}

/** Compact stage detail: next action, a short coach summary, a link to the saved work, and course tools one tap away. */
function StageDetail({ stage, bookmarkCount, isCurrent, disabled, onSelect, onUseTool, onSeeWork }: { stage: Stage; bookmarkCount: number; isCurrent: boolean; disabled: boolean; onSelect: () => void; onUseTool: (text: string) => void; onSeeWork: () => void }) {
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [toolsOpen, setToolsOpen] = useState(false);
  const longSummary = stage.coach_summary.length > 220;
  const actionLabel = stage.completed ? 'Revisit' : 'Continue';
  const showTools = isCurrent || stage.selectable;
  const tools = showTools ? courseTools(stage.id) : [];
  return <div className="stage-detail">
    <p className="stage-next">{stage.next_action}</p>
    {stage.criteria.length ? <div className="stage-block">
      <h4>What a useful deliverable looks like</h4>
      <ul className="stage-criteria">{stage.criteria.map(item => <li key={item}>{item}</li>)}</ul>
    </div> : null}
    {!isCurrent && !stage.selectable ? <p className="supporting">Not available yet.</p> : null}
    {!isCurrent && stage.selectable ? <button className="stage-continue" aria-label={`${actionLabel} ${stage.label}`} disabled={disabled} onClick={onSelect}>
      {actionLabel} <Icon name="chevronRight"/></button> : null}
    {stage.coach_summary ? <div className="stage-block">
      <h4>Coach summary</h4>
      <div className="stage-summary" id={`stage-summary-${stage.id}`} data-clamped={(longSummary && !summaryOpen) || undefined}><CoachText text={stage.coach_summary}/></div>
      {longSummary ? <button className="card-link" aria-expanded={summaryOpen} aria-controls={`stage-summary-${stage.id}`} onClick={() => setSummaryOpen(open => !open)}>
        {summaryOpen ? 'Show less' : 'Read more'}</button> : null}
    </div> : null}
    {bookmarkCount ? <button className="card-link stage-work-link" onClick={onSeeWork}>Starred messages · {bookmarkCount}<Icon name="chevronRight"/></button> : null}
    {tools.length ? <div className="stage-block">
      <button className="tool-toggle" aria-expanded={toolsOpen} aria-controls={`stage-tools-${stage.id}`} onClick={() => setToolsOpen(open => !open)}>
        <span>Tools from the course</span><small>{tools.length}</small><Icon name={toolsOpen ? 'chevronDown' : 'chevronRight'}/></button>
      <ul className="tool-list" id={`stage-tools-${stage.id}`} hidden={!toolsOpen}>{tools.map(tool => <li key={tool.label}>
        <button className="tool-chip" disabled={disabled} onClick={() => onUseTool(tool.text)}>
          {tool.label}{tool.week ? <small>{tool.week}</small> : null}</button></li>)}</ul>
    </div> : null}
  </div>;
}

/** Show explicitly starred messages, grouping by stage for Design coaching. */
function MyWork({ project, groupByStage, focus, bookmarks, disabled, error, ready, refresh, removeStar, jumpToMessage }: {
  project: Project; groupByStage: boolean; focus?: { id: string; n: number }; bookmarks: Bookmark[]; disabled: boolean;
  jumpToMessage: (id: string) => void; error: string; ready: boolean; refresh: () => void; removeStar: (id: string) => void;
}) {
  const [open, setOpen] = useState<Record<string, boolean>>({ [project.current_stage]: true });
  useEffect(() => {
    if (!focus) return;
    setOpen(value => ({ ...value, [focus.id]: true }));
    window.requestAnimationFrame(() => document.getElementById(`bookmarks-${focus.id}`)?.scrollIntoView({ block: 'nearest' }));
  }, [focus]);
  const groups = [...project.stages.map(stage => ({ id: stage.id, label: stage.label })),
    ...(bookmarks.some(item => item.stage_id === null) ? [{ id: 'none', label: 'No stage' }] : [])];
  return <section className="review-card bookmarks" aria-labelledby="my-work-title">
    <header className="card-head"><h3 id="my-work-title">My work</h3></header>
    <p className="supporting">Star messages in Chat to keep useful ideas and coach replies here.</p>
    {error ? <p role="alert">{error} <button disabled={disabled} onClick={refresh}>Refresh bookmarks</button></p> : !ready ? <p role="status">Loading bookmarks…</p> : null}
    {!groupByStage && ready && !bookmarks.length ? <p className="supporting">No starred messages yet.</p> : null}
    {!groupByStage && bookmarks.length ? <BookmarkList label="Starred messages" entries={bookmarks} disabled={disabled}
      jumpToMessage={jumpToMessage} removeStar={removeStar}/> : null}
    {groupByStage ? groups.map(group => {
      const entries = bookmarks.filter(item => (item.stage_id ?? 'none') === group.id);
      return <section className="bookmark-group" id={`bookmarks-${group.id}`} key={group.id} aria-labelledby={`bookmark-heading-${group.id}`}>
        <h4><button id={`bookmark-heading-${group.id}`} className="bookmark-heading" aria-label={group.label} aria-describedby={`bookmark-count-${group.id}`} aria-expanded={!!open[group.id]} aria-controls={`bookmark-list-${group.id}`}
          onClick={() => setOpen(value => ({ ...value, [group.id]: !value[group.id] }))}>
          <span>{group.label}</span><small id={`bookmark-count-${group.id}`}>{entries.length} saved</small><Icon name={open[group.id] ? 'chevronDown' : 'chevronRight'}/>
        </button></h4>
        <div className="bookmark-content" id={`bookmark-list-${group.id}`} hidden={!open[group.id]}>
          {ready && !entries.length ? <p className="supporting">No starred messages in this stage yet.</p> : null}
          <BookmarkList label={`Starred messages in ${group.label}`} entries={entries} disabled={disabled}
            jumpToMessage={jumpToMessage} removeStar={removeStar}/>
        </div>
      </section>;
    }) : null}
  </section>;
}

/** Keep saved previews and their actions consistent across both Review modes. */
function BookmarkList({ label, entries, disabled, jumpToMessage, removeStar }: {
  label: string; entries: Bookmark[]; disabled: boolean; jumpToMessage: (id: string) => void; removeStar: (id: string) => void;
}) {
  return <ol className="bookmark-list" aria-label={label}>{entries.map(item => <li key={item.id} className="bookmark-entry">
    <p className="bookmark-author"><strong>{item.role === 'user' ? 'You' : 'Coach'}</strong>{item.interaction_intent === 'lecture_help' ? <span className="bookmark-mode">Lecture Help</span> : null}</p>
    <div className="bookmark-preview">{item.role === 'assistant' ? <CoachText text={item.preview} links={false}/> : item.preview}</div>
    <div className="bookmark-actions"><button className="bookmark-jump" disabled={disabled} onClick={() => jumpToMessage(item.id)}>Jump to message<Icon name="chevronRight"/></button>
      <button className="bookmark-remove" disabled={disabled} aria-label="Remove star" title="Remove star" onClick={() => removeStar(item.id)}><Icon name="star"/></button></div>
  </li>)}</ol>;
}
