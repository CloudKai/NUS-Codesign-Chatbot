/**
 * @vitest-environment jsdom
 */
/** Review stage detail makes each stage's deliverable criteria actionable without awarding completion. */
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { ThinkingPath } from './ThinkingPath';
import { Conversation } from './Conversation';
import { createReaderQueryClient } from './api/queryClient';
import { WorkspaceLayoutContext, useWorkspaceLayout } from './workspaceLayout';
import type { Bookmarks, Page, Project } from './api';

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); sessionStorage.clear(); localStorage.clear(); });

const project: Project = {
  owner_id: 'a', thread_id: 'ch1', current_stage: 'problem_identification',
  stages: [{
    id: 'problem_identification', label: 'Problem identification', completed: false,
    selectable: true, artifact_label: 'Working problem statement',
    student_work: [], feedback: [], coach_summary: '', decision: '',
    next_action: 'Describe the affected people.',
    criteria: [
      'Names the affected people and their context.',
      'Describes the outcome they need without fixing one solution.',
      'Points to evidence from interviews or fieldwork.',
    ],
  }, {
    id: 'concept_generation', label: 'Concept generation', completed: false,
    selectable: false, artifact_label: 'Alternatives and reasons',
    student_work: [], feedback: [], coach_summary: '', decision: '',
    next_action: 'Describe two different concepts.',
    criteria: ['Describes at least two distinct concepts.'],
  }],
  pending: null,
  review: {
    summary: '', strengths: [], improvements: [], facione_scores: [],
  },
};

function renderReview() {
  return render(<ThinkingPath project={project} title="Crossing" disabled={false}
    act={async () => {}} startInChat={() => {}} onClose={() => {}} status=""
    insertScaffold={() => {}} onTabChange={() => {}} bookmarks={[]} bookmarkError="" bookmarksReady
    refreshBookmarks={() => {}} removeStar={() => {}} jumpToMessage={() => {}}>
    {null}
  </ThinkingPath>);
}

it('shows the current stage criteria next to its next action once expanded', () => {
  renderReview();
  fireEvent.click(screen.getByRole('button', { name: /Problem identification/ }));
  const detail = screen.getByRole('region', { name: 'Problem identification saved work' });
  expect(detail.textContent).toContain('What a useful deliverable looks like');
  expect(detail.textContent).toContain('Names the affected people and their context.');
  expect(detail.textContent).toContain('Describe the affected people.');
});

it('the Review Summary tab does not render the Deep Review container', () => {
  renderReview();
  fireEvent.click(screen.getByRole('tab', { name: 'Summary' }));
  expect(screen.queryByText(/Deep Review/)).toBeNull();
  expect(screen.queryByRole('button', { name: 'Start Deep Review' })).toBeNull();
});

it('never presents criteria as completion or unlocks a stage', () => {
  renderReview();
  fireEvent.click(screen.getByRole('button', { name: /Concept generation/ }));
  const detail = screen.getByRole('region', { name: 'Concept generation saved work' });
  expect(detail.textContent).toContain('Not available yet.');
  expect(detail.textContent).not.toContain('Complete');
});

it('shows only saved work in Improve Review and restores the pending decision in Design coaching', () => {
  class ResizeObserverStub { observe() {} disconnect() {} }
  vi.stubGlobal('ResizeObserver', ResizeObserverStub);
  vi.stubGlobal('innerWidth', 1600);
  Object.defineProperties(HTMLDialogElement.prototype, {
    show: { configurable: true, value(this: HTMLDialogElement) { this.open = true; } },
    close: { configurable: true, value(this: HTMLDialogElement) { this.open = false; } },
  });
  const pendingProject = { ...project, pending: { id: 'decision-1', from_stage: 'problem_identification',
    to_stage: 'concept_generation', rationale: 'The problem is ready.' } };
  const page: Page = { owner_id: 'a', notebook: { id: 'ch1', name: 'Crossing', kind: 'chat',
    parent_notebook_id: null, pinned: false }, messages: [], total_count: 0, next_cursor: null,
    conversation_revision: 0 };
  const bookmarks: Bookmarks = { owner_id: 'a', thread_id: 'ch1', conversation_revision: 0, messages: [
    { id: 'm1', role: 'assistant', stage_id: null, interaction_intent: 'improve_design', preview: 'Try a larger sign.' },
    { id: 'm2', role: 'user', stage_id: 'problem_identification', interaction_intent: 'project_coaching', preview: 'People cannot see the crossing.' },
  ] };
  function Chat() {
    const layout = useWorkspaceLayout();
    return <WorkspaceLayoutContext.Provider value={layout}><Conversation page={page} project={pendingProject}
      owner="a" preferredIntent="improve" seededBookmarks={bookmarks} refresh={async () => {}}
      expired={() => {}} onHelp={() => {}} showStarters externalBlocked={false} activity={() => {}}
      locateMessage={async () => true} busy={false} loadEarlier={async () => {}}
      onCanvasSelectionConsumed={() => {}} onArtifactSelectionConsumed={() => {}}/></WorkspaceLayoutContext.Provider>;
  }
  render(<QueryClientProvider client={createReaderQueryClient()}><Chat/></QueryClientProvider>);

  expect(screen.queryByRole('button', { name: 'Move to Concept generation' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Review' }));
  const review = within(screen.getByRole('dialog', { name: 'Review' }));
  expect(review.getByRole('heading', { name: 'My work' })).toBeTruthy();
  expect(review.getByText('Try a larger sign.')).toBeTruthy();
  expect(review.getByText('People cannot see the crossing.')).toBeTruthy();
  expect(review.queryByRole('tab')).toBeNull();
  expect(review.queryByRole('button', { name: 'Download project summary' })).toBeNull();

  fireEvent.click(screen.getByRole('radio', { name: 'Design coaching' }));
  expect(screen.getByRole('button', { name: 'Move to Concept generation' })).toBeTruthy();
  expect(review.getByRole('tab', { name: 'Progression', selected: true })).toBeTruthy();
  expect(review.getByRole('tab', { name: 'Summary' })).toBeTruthy();
  expect(review.getByRole('button', { name: 'Confirm next stage' })).toBeTruthy();
});
