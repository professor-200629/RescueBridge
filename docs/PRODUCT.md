# Product

## Problem

The developer (Balu) once had a mouse problem that made normal interaction with the laptop difficult. That
experience is the starting point; no other user stories are claimed. When the primary input,
the sound, or a window is wrong, the usual fixes are hard to reach exactly because the
thing that is broken is the thing you would use to fix it. This is sharpest right before something
time-critical, such as an interview starting in minutes with notes open that must not be lost.

## Target user (initial)

An ordinary Windows user, including someone who needs help using Settings, who has RescueBridge already
installed and a phone paired while the laptop still worked. No disability-specific effectiveness is
claimed: that needs evaluation with real users, which has not been done (zero participants so far).

## What it does

A **second interaction channel** (phone voice/text) into the **existing, still-running** Windows session:

1. Listens to the person's own words; records each symptom as a separate issue.
2. Takes fresh observations through a narrow, fixed Windows helper.
3. Asks one focused question when the right answer depends on the person (e.g. left-handed preference,
   which app is missing).
4. Proposes one exact change and waits for an explicit tap on the paired phone.
5. Applies it, re-observes, and asks the person to confirm with a functional check (test tone, test click,
   "can you see it"). Partial results stay partial.
6. Keeps inspectable evidence: observed before/after, operation outcome, the person's answer, all labelled
   Real Windows / Fixture Simulation / Controlled Live Lab.

## Proposed differentiation (to be shown, not assumed)

Known alternatives: Windows Settings and troubleshooters, Get Help, Quick Assist (a helper takes remote
control), voice access/accessibility tools, and AI agents that operate a computer by vision and input
injection. RescueBridge does not claim to be the first or best at any of these. Its intended differences:

- **No remote control of the pointer or keyboard.** Only three narrow, validated operations exist.
- **The work session stays open.** No reboot, no logout, no app restart; WorkPad's unsaved text is
  fingerprinted before and after.
- **Approval is exact and enforced in code**, bound to the displayed proposal, revocable by Stop, and
  impossible for the model to grant.
- **Evidence over assertions.** API success is never reported as "fixed"; the person's confirmation is
  separate from the observed system state.

## Validation assumptions (open)

- People will pair a phone in advance (setup measured: see VALIDATION; under ten minutes is a target, not a
  measured claim for others).
- The three workflows cover a meaningful share of "laptop suddenly unusable" moments. **Unvalidated.**
- Speaking to a phone is easier than navigating Settings when input is impaired. **Unvalidated.**
- A 3B local model gives acceptable understanding with ~5–6 s latency on a 16 GB laptop. Measured on the
  test laptop only.

## Possible later directions (hypotheses only)

Family support (a trusted relative's phone as the second channel), bounded helpdesk workflows with a
privacy-preserving handoff bundle, more diagnosed audio routing cases. No sales pipeline, partnerships, or
acquisition interest exist.
