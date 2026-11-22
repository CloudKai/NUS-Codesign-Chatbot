/** Plain-Markdown copy of a student's saved project work. Built in the browser from the project view. */
import type { Project, ReviewFeedback } from './api';
import { skillLevel } from './coachingContent';

function unique(groups: ReviewFeedback[]) {
  return [...new Set(groups.flatMap(group => group.items.map(item => item.trim()).filter(Boolean)))];
}

/** Markdown text for the project; empty sections are left out so nothing is invented. */
export function projectMarkdown(project: Project, title: string, now = new Date()) {
  const review = project.review;
  const lines: string[] = [`# ${title || 'My project'}`, '', `Saved ${now.toLocaleDateString(undefined, { dateStyle: 'long' })}. Your work here is not graded.`, ''];
  const brief = review?.project_brief?.status === 'current' ? review.project_brief.brief : null;
  if (brief) {
    lines.push('## Your project so far', '');
    for (const [key, label] of [['who_and_why', 'Who and why'], ['problem', 'Problem'], ['current_idea', 'Current idea'], ['what_matters', 'What matters'], ['still_to_explore', 'Still to explore']] as const) {
      lines.push(`### ${label}`, '', brief[key].text || 'Not yet established', '');
    }
  } else if (review?.summary) lines.push('## Saved coach assessment', '', review.summary.trim(), '');
  const strengths = unique(review?.strengths ?? []);
  if (strengths.length) lines.push('## Strengths', '', ...strengths.map(item => `- ${item}`), '');
  const improvements = unique(review?.improvements ?? []);
  if (improvements.length) lines.push('## Areas to improve', '', ...improvements.map(item => `- ${item}`), '');
  const scored = (review?.facione_scores ?? []).filter(item => item.score !== null);
  if (scored.length) lines.push('## How your idea scores', '', 'Feedback on your critical thinking, not a grade.', '',
    ...scored.map(item => `- ${item.dimension}: ${item.score}/4 (${skillLevel(item.score as number)})`), '');
  project.stages.forEach((stage, index) => {
    if (!stage.student_work.length && !stage.coach_summary) return;
    lines.push(`## ${index + 1}. ${stage.label}${stage.completed ? ' (done)' : stage.id === project.current_stage ? ' (current)' : ''}`, '');
    if (stage.coach_summary) lines.push(stage.coach_summary.trim(), '');
    if (stage.student_work.length) lines.push('Your work:', '', ...stage.student_work.map(work => `> ${work.text.trim().replace(/\n/g, '\n> ')}`), '');
  });
  return lines.join('\n').replace(/\n{3,}/g, '\n\n').trimEnd() + '\n';
}

/** Start a browser download of the Markdown file. */
export function downloadProject(project: Project, title: string) {
  const blob = new Blob([projectMarkdown(project, title)], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  const name = (title || 'my-project').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'my-project';
  anchor.href = url;
  anchor.download = `${name}-summary.md`;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
