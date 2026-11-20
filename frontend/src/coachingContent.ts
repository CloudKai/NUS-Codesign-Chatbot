/** Static coaching content and deterministic helpers. Nothing here calls a model or the network. */
import type { ChatSummary, Project, Stage } from './api';

export interface Starter { label: string; text: string }

/** Stage ids match backend THINKING_STAGES. Unknown ids use the generic starters. */
const STAGE_STARTERS: Record<string, Starter[]> = {
  problem_identification: [
    { label: 'Who is affected?', text: 'The people affected by my problem are…\nHelp me check whether I understand their situation and needs.' },
    { label: 'Sharpen my problem', text: 'My problem statement right now is…\nHelp me make it clearer and more specific.' },
    { label: 'Why does it matter?', text: 'This problem matters because…\nWhat evidence would show that it really is a problem worth solving?' },
  ],
  concept_generation: [
    { label: 'Give me three alternatives', text: 'My current idea is…\nGive me three genuinely different alternatives to consider.' },
    { label: 'Compare two of my ideas', text: 'Idea A is… Idea B is…\nCompare them against my problem and tell me what trade-offs I should think about.' },
    { label: 'Pick a direction', text: 'The concept I am leaning towards is…\nHelp me test whether it is the right one to develop.' },
  ],
  design_specification: [
    { label: 'List requirements', text: 'My design must…\nHelp me check whether these requirements are complete and testable.' },
    { label: 'Name the constraints', text: 'The constraints I know about are…\nWhat constraints might I be missing?' },
    { label: 'How will I judge success?', text: 'I will know my design works if…\nHelp me turn this into measurable criteria.' },
  ],
  deep_analysis: [
    { label: 'Challenge my assumption', text: 'One assumption in my design is…\nWhat evidence would challenge it?' },
    { label: 'Weigh the trade-offs', text: 'The main trade-off in my design is…\nHelp me weigh the options and what I would give up.' },
    { label: 'Ethical implications', text: 'Someone who could be affected by my design is…\nWhat ethical risks should I consider?' },
  ],
  reflection: [
    { label: 'What changed in my thinking?', text: 'At the start I thought…\nNow I think…\nHelp me explain what changed and why.' },
    { label: 'What is still uncertain?', text: 'I am still unsure about…\nHelp me decide how to deal with this uncertainty.' },
    { label: 'Plan next steps', text: 'If I continued this project, I would next…\nHelp me prioritise.' },
  ],
};
const GENERIC_STARTERS: Starter[] = [
  { label: 'Share my idea', text: 'My idea so far is…\nHelp me develop it.' },
  { label: 'Test an assumption', text: 'One assumption I am making is…\nWhat evidence would challenge it?' },
  { label: 'What next?', text: 'I am not sure what to do next on my project.\nWhat should I think about?' },
];

/** Up to three starters for a stage. */
export function starterChips(stageId: string): Starter[] {
  return STAGE_STARTERS[stageId] ?? GENERIC_STARTERS;
}

interface SkillContent { explanation: string; practice: string }
/** Keyed by lowercase Facione dimension label from the API (FACIONE_DIMENSIONS). */
const SKILLS: Record<string, SkillContent> = {
  analysis: {
    explanation: 'Breaking an idea into parts and seeing how they relate.',
    practice: 'I want to practise Analysis.\nHere is one part of my idea, and how I think it connects to the rest…',
  },
  interpretation: {
    explanation: 'Working out what information or feedback really means.',
    practice: 'I want to practise Interpretation.\nHere is a piece of information or feedback and what I think it means for my design…',
  },
  inference: {
    explanation: 'Drawing reasoned conclusions from the evidence you have.',
    practice: 'I want to practise Inference.\nFrom this evidence…, I conclude…, because…',
  },
  evaluation: {
    explanation: 'Judging how strong your evidence and arguments are.',
    practice: 'I want to practise Evaluation.\nThe strongest and weakest parts of my argument are…',
  },
  explanation: {
    explanation: 'Explaining your reasoning clearly so others can follow it.',
    practice: 'I want to practise Explanation.\nHere is my reasoning for this decision, step by step…',
  },
  'self-regulation': {
    explanation: 'Checking and correcting your own thinking.',
    practice: 'I want to practise Self-Regulation.\nLooking back at my work, something I would revise is…',
  },
};

/** One-line plain explanation; unknown skills get an empty string. */
export function skillExplanation(dimension: string): string {
  return SKILLS[dimension.trim().toLowerCase()]?.explanation ?? '';
}

/** General guide per skill and score (index 0 = score 1). It describes the level, not the student's work. */
const SKILL_TIPS: Record<string, [string, string, string, string]> = {
  analysis: [
    'Your idea is described as a whole. Try splitting it into its main parts.',
    'Some parts are named, but how they connect is unclear. Say how each part affects the others.',
    'You break the idea into clear parts. Next, show which part matters most and why.',
    'You map parts and their links well. Keep checking for parts you may have missed.',
  ],
  interpretation: [
    'Information is taken at face value. Ask what a finding or comment really tells you.',
    'You notice information, but its meaning is vague. Say what it means for your users.',
    'You explain what information means. Next, try another reading of the same evidence.',
    'You read evidence accurately and in context. Keep comparing different readings.',
  ],
  inference: [
    'Conclusions come without reasons. Add a “because…” to each one.',
    'Some conclusions go further than your evidence. Say what each one rests on.',
    'Your conclusions follow from the evidence. Next, ask what could make them wrong.',
    'You draw well-supported conclusions and weigh alternatives. Keep it up.',
  ],
  evaluation: [
    'Ideas and sources are accepted as given. Ask how reliable each one is.',
    'You judge some claims, but without clear criteria. Say what makes evidence strong or weak.',
    'You judge evidence with reasonable criteria. Next, apply them to your own idea too.',
    'You weigh strengths and weaknesses, including your own. Keep using the same standard.',
  ],
  explanation: [
    'Decisions are stated without reasons. Walk through why you made them.',
    'Reasons are given but hard to follow. Put them in order, step by step.',
    'Your reasoning is clear. Next, explain why you ruled out the alternatives.',
    'Others can follow and trust your reasoning. Keep it clear as the project grows.',
  ],
  'self-regulation': [
    'There is little checking of your own work. Pause and ask what you might have missed.',
    'You notice some gaps but have not acted yet. Pick one thing to revise.',
    'You check your work and make fixes. Next, ask which assumptions you have not tested.',
    'You question and improve your own thinking. Keep noting what you changed and why.',
  ],
};
const GENERIC_TIPS = [
  'Early days for this skill. Pick one small step to practise.',
  'Some of this skill is showing. Add more detail to your reasons.',
  'This skill is working well. Next, push it a little further.',
  'This is a strength. Keep using it.',
];

/** One-sentence guide for what a 1–4 score looks like and how to move up. */
export function skillTip(dimension: string, score: number): string {
  const level = Math.min(Math.max(Math.round(score), 1), 4) - 1;
  return (SKILL_TIPS[dimension.trim().toLowerCase()] ?? GENERIC_TIPS)[level];
}

/** Plain word for a 1–4 score so the number reads as feedback, not a grade. */
export function skillLevel(score: number): string {
  return ['Just starting', 'Developing', 'Solid', 'Strong'][Math.min(Math.max(Math.round(score), 1), 4) - 1];
}

export function practiceScaffold(dimension: string): string {
  return SKILLS[dimension.trim().toLowerCase()]?.practice
    ?? `I want to practise ${dimension}.\nHere is an example from my project…`;
}

export const improveScaffold = (item: string) => `I want to work on this feedback: "${item}"\nHere is how I will address it…`;
export const buildScaffold = (item: string) => `A strength I want to build on: "${item}"\nHere is how I can take it further…`;
export const pickUpScaffold = (stage: string, nextAction: string) =>
  `Picking up where I left off on ${stage}.\nNext step: ${nextAction}\nMy update is…`;
export const stageScaffold = (stage: string) => `For ${stage}, here is what I have so far…`;

/** First sentence of an answer with light Markdown removed, at most 200 characters. */
export function firstSentence(text: string): string {
  const plain = text.replace(/```[\s\S]*?```/g, ' ').replace(/[#>*_`]/g, '').replace(/\s+/g, ' ').trim();
  const match = plain.match(/^.*?[.!?](?=\s|$)/);
  const sentence = (match ? match[0] : plain).trim();
  return sentence.length > 200 ? `${sentence.slice(0, 199).trimEnd()}…` : sentence;
}

export const lectureToProjectScaffold = (answer: string) =>
  `From lecture help: "${firstSentence(answer)}"\nHere is how this applies to my project…`;

export interface SkillSummary { strongest: string; grow: string; growScore: number; strongestScore: number }

/** Strongest and lowest assessed skills. Null when nothing is assessed. Ties keep API order. */
export function skillSummary(scores: { dimension: string; score: number | null }[]): SkillSummary | null {
  const assessed = scores.filter((item): item is { dimension: string; score: number } => item.score !== null);
  if (!assessed.length) return null;
  const strongest = assessed.reduce((best, item) => item.score > best.score ? item : best);
  const grow = assessed.reduce((low, item) => item.score < low.score ? item : low);
  return { strongest: strongest.dimension, strongestScore: strongest.score, grow: grow.dimension, growScore: grow.score };
}

export type CheckInRule = 'welcome-back' | 'no-work' | 'review-item' | 'skill';
export interface CheckIn { rule: CheckInRule; message: string; action: string; scaffold: string }

const DAY = 24 * 60 * 60 * 1000;

/** Choose at most one check-in from saved data. First matching rule wins; dismissed rules are skipped. */
export function chooseCheckIn(project: Project, summary: ChatSummary | undefined, mode: 'lecture' | 'project',
  dismissed: readonly string[], now = Date.now()): CheckIn | null {
  if (project.pending) return null;
  const stage: Stage | undefined = project.stages.find(item => item.id === project.current_stage);
  if (!stage) return null;
  const active = Date.parse(summary?.activity_at ?? '');
  if (!dismissed.includes('welcome-back') && Number.isFinite(active) && now - active > DAY) {
    return { rule: 'welcome-back', message: `Welcome back. Last time you were working on ${stage.label}. Next: ${stage.next_action}`,
      action: 'Pick up here', scaffold: pickUpScaffold(stage.label, stage.next_action) };
  }
  if (mode !== 'project') return null;
  if (!dismissed.includes('no-work') && stage.student_work.length === 0) {
    return { rule: 'no-work', message: `You haven't shared anything for ${stage.label} yet.`,
      action: 'Start here', scaffold: stageScaffold(stage.label) };
  }
  const item = project.review?.improvements.find(group => group.stage_id === stage.id)?.items[0];
  if (!dismissed.includes('review-item') && item) {
    return { rule: 'review-item', message: `Your last review suggested: ${item}`,
      action: 'Work on this', scaffold: improveScaffold(item) };
  }
  const skill = skillSummary(project.review?.facione_scores ?? [])?.grow;
  if (!dismissed.includes('skill') && skill) {
    return { rule: 'skill', message: `Want to practise ${skill}?`, action: `Practice ${skill}`, scaffold: practiceScaffold(skill) };
  }
  return null;
}
