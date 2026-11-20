/** Static coaching content and deterministic helpers. Nothing here calls a model or the network. */
import type { ChatSummary, Project, Stage } from './api';

export interface Starter { label: string; text: string }
/** A template from the CDE2300 lecture notes. `week` names the lecture file it comes from. */
export interface CourseTool extends Starter { week: string }

/**
 * Templates taken from the CDE2300 lecture notes (lecture_notes/lectureNotes) and the app's own How Might We
 * formula (agentcore_runtime/prompts/stages). Wording follows the slides. Stage ids match backend THINKING_STAGES.
 * The first three tools of a stage appear as chips above the composer; all of them are listed in Review.
 */
const COURSE_TOOLS: Record<string, CourseTool[]> = {
  problem_identification: [
    { label: 'Job statement', week: 'Week 2', text: 'My job statement:\nWHEN I … (what is the context?)\nBUT … (what is the barrier getting in the way today?)\nHELP ME … (what is the user trying to do?)\nSO I … (what is the outcome of achieving it?)\n' },
    { label: 'Persona', week: 'Week 4', text: 'My persona:\nEmpathic title: \nQuote: \nBasic demographics: \nGoals & frustrations: \nHabits/preferences: \n' },
    { label: 'How Might We', week: 'Week 7', text: 'How might we … (action or opportunity)\nfor … (user)\nso that … (desired outcome or benefit)\n' },
    { label: 'Functional, emotional, social jobs', week: 'Week 2', text: 'The jobs my user is hiring this product to do:\nFunctional: \nEmotional: \nSocial: \n' },
    { label: 'Interview questions', week: 'Week 2', text: 'Questions for my JTBD interview:\nWhen did you first think about buying something like this?\nTell me the story about buying this product.\nWhy did you buy this product?\nHow do you feel about your purchase now?\nHow did you share your buying story with friends and family?\n\nWhat I learned: ' },
    { label: 'User journey map', week: 'Week 10', text: 'User journey map:\nPersona: \nScenario or Job-To-Be-Done: \nTypical journey (before, during and after the experience): \nActions: \nThinking: \nEmotion: \nOpportunities: \nAreas of responsibility: ' },
  ],
  concept_generation: [
    { label: 'Creative matrix', week: 'Week 7', text: 'Creative matrix for my How Might We… (defer judgment, aim for many ideas):\nPeople / Process / Policy: \nObjects: \nEnvironment: \nMedia: \nServices: \n' },
    { label: 'Crazy 8', week: 'Week 4', text: 'Crazy 8, eight different ideas for my How Might We…:\n1. \n2. \n3. \n4. \n5. \n6. \n7. \n8. \n' },
    { label: 'Powers of Ten', week: 'Week 8', text: 'Powers of Ten on my problem:\nZoomed in (smaller magnitude): \nZoomed out (larger magnitude): \nWhat new angle does this show? ' },
    { label: 'Combine old elements', week: 'Week 7', text: 'An idea is a new combination of old elements.\nElement A: \nElement B: \nThe relationship I see between them: ' },
    { label: 'Metaphor or analogy', week: 'Weeks 8–9', text: 'Metaphor or analogy for my design:\n1. Pain points: \n2. Convert the pain points to attributes: \n3. Source domain outside my design problem (nature, technology, art, social systems): \n4. Mapping relationships (how the source\'s attributes map to my design): ' },
  ],
  design_specification: [
    { label: 'Selection criteria', week: 'Week 7', text: 'My selection criteria, based on my persona, job statement and design challenge (for example big impact, best customer experience, most disruptive):\n1. \n2. \n3. \n\nThe concept that best meets them is… because… ' },
    { label: 'Prioritisation matrix', week: 'Week 7', text: 'Prioritisation matrix (importance to the customer experience vs difficulty):\nHigh importance, low difficulty: \nHigh importance, high difficulty: \nLow importance, low difficulty: \nLow importance, high difficulty: \n' },
    { label: 'Goals, values, features', week: 'Week 4', text: 'User goal (why?): \nProduct value (what?): \nProduct feature (how?): \n' },
  ],
  deep_analysis: [
    { label: 'Riskiest assumption', week: 'Week 8', text: 'The most important assumption we need to test (the one that would make the whole solution fail if it is wrong):\n\nHow I could test it: ' },
    { label: 'Test questions', week: 'Week 9', text: 'Questions for my test:\nIs the intended solution valued by users?\nAm I focusing on the critical issues of the users?\nHow will I measure the value of the solution to the user?\n' },
    { label: 'Prototyping plan', week: 'Week 8', text: 'My prototyping plan:\n1. My design problem or challenge: \n2. My solution: \n3. My plan for user testing:\n   The most important assumption to test: \n   The prototype(s) I will build (which features?): \n   Tools and materials needed: \n' },
    { label: 'Feedback from my test', week: 'Week 9', text: 'What I observed (listening with curiosity, not selling my idea): \nWhat it tells me about my assumptions, solutions and concepts: \nMy new point of view on my persona or job statement: ' },
    { label: 'Who could be affected?', week: '', text: 'Someone who could be affected by my design is…\nWhat could go wrong for them, and how would I find out?' },
  ],
  reflection: [
    { label: 'What changed in my thinking?', week: '', text: 'At the start I thought…\nNow I think…\nWhat changed it was… ' },
    { label: 'Story arc', week: 'Week 10', text: 'My story arc:\nBackground: \nIntroduction: \nBuild-up and problems: \nSolution and testing: \nTake-home message: \n' },
    { label: 'What is still uncertain?', week: '', text: 'I am still unsure about…\nHow I could find out: ' },
  ],
};
const GENERIC_TOOLS: CourseTool[] = [
  { label: 'Share my idea', week: '', text: 'My idea so far is…\nWhat I am not sure about: ' },
  { label: 'Test an assumption', week: '', text: 'One assumption I am making is…\nWhat evidence would challenge it? ' },
  { label: 'What next?', week: '', text: 'I am not sure what to do next on my project.\nWhat should I think about? ' },
];

/** Every template for a stage, for the Review stage list. */
export function courseTools(stageId: string): CourseTool[] {
  return COURSE_TOOLS[stageId] ?? GENERIC_TOOLS;
}

/** Up to three starters for a stage: the lecture tools most used at that point. */
export function starterChips(stageId: string): Starter[] {
  return courseTools(stageId).slice(0, 3);
}

/** Progressive hints: a nudge first, then a more specific one. Neither asks for the answer. */
export function hintScaffold(level: number, stage: string) {
  return level <= 0
    ? `I'm stuck on ${stage}.\n\nPlease give me a small hint, such as a question or a nudge. If a tool from our lectures could help, name it. Don't give me the answer. `
    : `Your last hint helped a little, but I'm still stuck on ${stage}.\n\nPlease give me a more specific hint. Don't write the answer for me. `;
}

/** One optional line after a stage move, to build the habit of noticing how thinking changed. */
export const reflectionScaffold = (stage: string) => `Looking back on ${stage}, what changed in my thinking: `;


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

export const improveScaffold = (item: string) => `Working on this feedback: “${item}”\n\nHere is how I will address it: `;
export const buildScaffold = (item: string) => `Building on this strength: “${item}”\n\nHere is how I can take it further: `;
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
