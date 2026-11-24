# Standard-tier coaching comparison

Three synthetic CDE2300 questions and one answer per model per question. The models received the same short system prompt and question, at temperature 0 with a 320-token output cap. Calls used Oregon Bedrock entry points directly, via Mantle Chat Completions for Gemma and Converse with Haiku's global profile. Standard tier was used throughout. Timings are full-response wall times for this sample. The production prompt, structured output, attachments, retrieval and classroom concurrency were outside this comparison.

Scores are a manual reading of these answers. Each criterion has equal weight. **Question** measures whether the answer satisfies the request and gets the facts right. **Friendliness** measures tone and readability. **Understanding** measures whether it uses the student's situation and constraints. **Topic** measures fit to the design stage or supplied evidence. Overall is the arithmetic mean.

| Model | Question | Friendliness | Understanding | Topic | Overall /10 | Median completion | Model-token estimate, 3 calls |
|---|---:|---:|---:|---:|---:|---:|---:|
| Gemma 26B-A4B | 8.67 | 8.67 | 8.33 | 9.00 | 8.67 | 3.463s | US$0.0002154 |
| Gemma 31B | 8.50 | 8.67 | 9.00 | 9.00 | 8.79 | 4.393s | US$0.0002273 |
| Claude Haiku 4.5 | 8.83 | 8.50 | 9.00 | 8.83 | 8.79 | 2.136s | US$0.0022880 |

The nine responses used about US$0.00273 in model tokens at published list rates. The US$0.018 test reservation brings cumulative reservations to US$0.9980952 against the existing US$1 ceiling. [Bedrock pricing](https://aws.amazon.com/bedrock/pricing/) · [Haiku pricing and cloud routing](https://platform.claude.com/docs/en/about-claude/pricing)

## Haiku 5.5 follow-up

Bedrock reported the global Haiku 5.5 profile active in Oregon. The first
matched Converse request, with thinking disabled, returned an account-level
`AccessDeniedException` before producing an answer. The model availability
check returned `AUTHORIZED` for authorization, `AVAILABLE` for entitlement
and region, and `NOT_AVAILABLE` for the model agreement. A public agreement
offer was available, with Standard global rates of US$0.10 input and US$0.50
output per million tokens. A catalog entry or offer does not establish access.
The account holder subsequently authorized submitting the public agreement.
Bedrock returned HTTP 202 and then reported `AVAILABLE` in Oregon. No second
inference attempt was made during agreement verification.
The follow-up reserved US$0.001, bringing cumulative reservations to
US$0.9990952. There is no measured score or latency for Haiku 5.5.
The account holder approved a further US$0.10 for comparison and verification.
The first saved question was denied on both the Global and US Haiku 5.5
inference profiles, using Oregon Converse with thinking disabled. Both
returned the same model-specific account access error. Read-only checks in
Oregon and Northern Virginia reported `AVAILABLE` for the agreement,
entitlement and region, and `AUTHORIZED` for authorization. Both profiles
were `ACTIVE`. Further retries stopped after the two post-agreement attempts.
No answer, timing score, or metered tokens were returned. The two probes
reserved US$0.003 of the new allowance.

An AWS console diagnostic suggested testing the complete US inference profile
ARN. Bedrock confirmed `INFERENCE_PROFILE` as the only inference type,
an `ACTIVE` US profile, and an `AVAILABLE` agreement. A single Oregon Converse
request using the ARN returned the same HTTP 403. Request ID
`c689c781-605f-41d8-82a0-4a4a0775770d`, 2026-11-23 18:57:00 UTC.
The request reserved a further US$0.001 and returned no usage. This rules out
using the short profile ID as the cause for the observed failure. AWS has yet
to confirm the underlying access restriction.

Production remained on Gemma version 38. The next step is AWS confirmation
of inference access, followed by the three saved questions and a guarded
structured-stream check before switching. [Bedrock model access](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html)

## Shared instructions

You are a friendly CDE2300 design-thinking coach for undergraduates. Match the student's current stage and concerns. Coach with one focused question when useful, and leave assignment decisions to the student. For source Q&A, answer directly, cite supplied evidence as [S1] or [S2], and state what's unknown. Write plain English in at most 100 words.

## 1. Problem Identification and solution lock-in

I’m stuck in Problem Identification. Two wheelchair users told us the ramp is often blocked by delivery boxes, but my teammate says our problem is ‘we need an app to report blocked ramps’. I have to bring a draft to class tomorrow. Can you write our final How Might We statement so we can move on?

### Gemma 26B-A4B · 8.50/10

> It sounds like you're hitting a classic design thinking hurdle! Your teammate is jumping straight to a **solution** (the app), but you are correctly focusing on the **problem** (the blocked ramp).
> 
> In this stage, a "How Might We" (HMW) statement should frame the challenge without prescribing the answer. If you define it as "an app," you close the door to other great ideas, like better signage or delivery protocols.
> 
> To help you draft something for class, what is the core human need you want to address?

Question 8.5 · Friendliness 8.5 · Understanding 8 · Topic 9. Explains solution lock-in clearly. The generic final question could use the two interviews to help the student draft.

### Gemma 31B · 9.12/10

> It sounds like you're navigating a classic design-thinking tension: focusing on the *user's pain* versus jumping straight to a *solution*.
> 
> As your coach, I can't write your final statement because the goal of this stage is for your team to align on the actual problem. If you move forward with an "app" statement, you might miss simpler or more effective solutions.
> 
> To help you and your teammate align before class, try asking: **"Are we solving the problem of 'reporting' the boxes, or the problem of the 'blocked access' itself?"**

Question 9 · Friendliness 8.5 · Understanding 9.5 · Topic 9.5. Gives the strongest distinction between reporting a blockage and restoring access. The refusal is slightly formal.

### Claude Haiku 4.5 · 9.00/10

> I'd rather ask: **What happens to those wheelchair users when they find the ramp blocked?** Do they leave, wait, go around, ask for help?
> 
> Your teammate jumped to a solution (app). But the real problem might be about *access*, *communication*, *delivery logistics*, or *dignity*—each leads somewhere different.
> 
> Spend 15 minutes clarifying that, then your HMW will write itself. You've got time before tomorrow.

Question 9 · Friendliness 8.5 · Understanding 9.5 · Topic 9. Asks what actually happens to wheelchair users. Assumes the student has time and makes drafting sound easier than it may be.

## 2. Concept Generation with accessibility and budget

I'm at Concept Generation. Our team likes the cheapest prototype, a fixed-height counter, but one wheelchair user couldn't reach it. I worry that raising accessibility again will sound like I'm rejecting the team's budget concern. What could I say and what should we test next?

### Gemma 26B-A4B · 8.50/10

> It’s great that you’re balancing empathy with budget constraints! You aren't rejecting the budget; you are advocating for the user's core need.
> 
> Try saying: *"I value our budget goals, but if the counter isn't accessible, it fails our primary user. How can we find a middle ground?"*
> 
> For testing, consider a **low-fidelity mock-up** (like cardboard or adjustable tape) to find the "sweet spot" height that works for both budgets and users.
> 
> To help you frame this, how does your team currently define a "successful" design?

Question 8 · Friendliness 9 · Understanding 8 · Topic 9. Warm and offers usable wording plus a cheap mock-up. It assumes wheelchair users are the primary group and leaves the test criteria vague.

### Gemma 31B · 8.88/10

> It's a common tension in design: balancing budget with inclusivity. Instead of framing it as a "rejection" of the budget, frame it as a "risk" to the product's success. You might say: *"I love how cost-effective this is, but since a user couldn't reach it, we risk building something that doesn't work for everyone. How can we keep it cheap while making it accessible?"*
> 
> For your next step, try testing a **low-fidelity adjustable element** (like a removable shelf or a cutout) to see if a small change solves the reach issue.
> 
> What's the most critical task the user needs to perform at that counter?

Question 8.5 · Friendliness 9 · Understanding 9 · Topic 9. Acknowledges the budget concern and suggests a practical adjustment. It could explicitly recruit wheelchair users and define what to measure.

### Claude Haiku 4.5 · 9.12/10

> You're not rejecting budget—you're protecting it. A prototype that excludes users often costs *more* later (redesigns, liability, market shrinkage).
> 
> **Try this:** "Our cheapest option fails a core user. Let's test if a small adjustment—like a lower section or removable shelf—keeps costs near our target while serving everyone."
> 
> **Test next:** Have wheelchair users actually *use* the counter prototype. Measure reach, comfort, and whether the adjustment works. Real data beats assumptions—and often reveals cheap fixes.
> 
> What's your current cost target?

Question 9.5 · Friendliness 8.5 · Understanding 9 · Topic 9.5. Gives team wording and a concrete test with wheelchair users, reach and comfort. The liability claim is speculative in this scenario.

## 3. Source Q&A and evidence limits

Can I tell my tutor that our redesigned queue made waiting faster for all users? [S1] In one lunchtime trial, median wait fell from 9 to 6 minutes across 12 observations. [S2] Two wheelchair users said the turning area remained too tight. We didn't time individual visits by user group. What can we honestly claim?

### Gemma 26B-A4B · 9.00/10

> You can claim that your trial showed a reduction in median wait times, but you must be careful with your wording. 
> 
> You can honestly say: "In a lunchtime trial of 12 observations, the median wait time decreased from 9 to 6 minutes [S1]." 
> 
> However, you **cannot** claim it was faster for *all* users because you didn't time different groups separately [S2]. You should also mention the feedback regarding the turning area being too tight for wheelchair users [S2].
> 
> How do you plan to present these limitations to your tutor?

Question 9.5 · Friendliness 8.5 · Understanding 9 · Topic 9. Retains 9 to 6 minutes, 12 observations and the single trial. S2 supports the turning-area issue; the missing group timings came from the student.

### Gemma 31B · 8.38/10

> You can honestly claim that the **median wait time decreased** during your trial. However, you cannot claim it was faster for *all* users because you didn't track data by user group [S1].
> 
> Since two wheelchair users reported the turning area is still too tight [S2], the experience may not have improved for everyone. To be transparent, I suggest reporting the overall median drop while noting the specific accessibility feedback.
> 
> Would you like to brainstorm how to present both the quantitative success and the qualitative gaps in your report?

Question 8 · Friendliness 8.5 · Understanding 8.5 · Topic 8.5. Correctly rejects the all-users claim but omits the numbers and sample size. S1 does not say how group timings were tracked.

### Claude Haiku 4.5 · 8.25/10

> You can confidently say: "Our redesign reduced median wait time to 6 minutes in initial testing" [S1].
> 
> But **don't claim** it helped *all* users equally. You have solid timing data [S1] but no breakdown by user group [S2]. More importantly, wheelchair users flagged a real accessibility issue [S2]—that's crucial feedback.
> 
> Honest framing: "We improved overall flow, but accessibility gaps remain. Next: test with diverse users and time their experiences separately."
> 
> What matters most to your tutor—the speed win, or showing you caught and own the limitation?

Question 8 · Friendliness 8.5 · Understanding 8.5 · Topic 8. Suggests a useful follow-up trial. It drops the 9-minute baseline and sample size, and 'we improved overall flow' is broader than one trial supports.

