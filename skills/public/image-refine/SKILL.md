---
name: image-refine
description: Use this skill when the user wants a locally generated image or video clip to actually be good — "make me a picture of X and get it right", "keep trying until the lighting works", "iterate on this until the character is consistent" — or whenever a first local generation misses what was asked for. Drives a generate → look → judge → change-one-thing loop against criteria frozen before the first attempt, using the local ComfyUI tools (generate_image / generate_video), and stops on success, on the iteration cap, or when it is not converging. Requires the local media tools to be enabled; it is not for the cloud image-generation / video-generation skills.
---

# Image Refine

## Overview

First-attempt diffusion output is usually not what was asked for. On a metered
API, four attempts cost four times as much; on your own GPU they cost
electricity, so iterating is simply how good results are produced here.

This skill is a **loop the agent runs**, not a tool that runs a loop. You
generate, look at what came out, judge it against criteria you fixed *before*
the first attempt, change exactly one thing, and try again. The server holds
the iteration counter and the rubric so a lost count cannot turn into a runaway
loop.

## Prerequisites

The local media tools must be enabled (`generate_image`, `refine_start`,
`refine_verdict`, and `generate_video` for clips) and a ComfyUI must be
running. The tools ship enabled, so the usual failure is not a missing tool but
an unreachable service: if `generate_image` is not available, **or** it answers
that ComfyUI is unreachable or has no checkpoint installed, say so and use the
cloud `image-generation` skill instead — do not try to emulate this loop with
it, and do not retry the local tool hoping for a different answer.

**`view_image` is required for the judging step.** It is only bound when the
lead model reports vision support, so a text-only local model cannot run this
skill: it would be guessing at what it produced. If `view_image` is missing,
generate once, tell the user you cannot see the result, and stop — do not
iterate blind.

## Workflow

### Step 1: Freeze the rubric — before generating anything

Turn the request into **3–6 checkable criteria**. Checkable means you could
look at an image and answer yes or no.

- Good: "the cat is orange", "warm late-afternoon light from the left", "no
  text or watermark anywhere in frame", "full body, nothing cropped".
- Useless: "looks nice", "high quality", "professional". These cannot fail, so
  they cannot guide anything.

Then open the session:

```
refine_start(goal="<the request in one sentence>", criteria=[...], kind="image")
```

It returns a `session_id`. The criteria are now frozen — every iteration is
judged against that exact list. This is what makes the loop converge instead of
drifting: an open-ended "is this good?" either accepts the first attempt or
never accepts anything.

### Step 2: Generate

```
generate_image(prompt="...", session_id="<session_id>")
```

Pass the `session_id` every time — that is what counts the iteration. The tool
writes the PNG into the outputs directory (it appears in the artifact panel on
its own; no `present_files` call needed) and reports the `seed` that ran and the
graph it saved beside the image.

For a clip, use `generate_video(prompt="...", session_id=...)` instead. Expect
minutes, not seconds.

### Step 3: Look at it

```
view_image(image_path="<the image path the tool returned>")
```

**For video, view the contact sheet, not the clip.** `view_image` cannot read
an MP4. The contact sheet tiles evenly spaced frames into one PNG, which is
also the better critic input: flicker, morphing and identity drift read far
more clearly side by side than frame by frame.

**Only view the newest result each round.** Carry the earlier verdicts forward
in writing — they are in the session record. Re-viewing every previous image
bills full-resolution vision tokens again on every iteration, which is exactly
the cost this local pipeline exists to avoid.

### Step 4: Judge it

```
refine_verdict(
  session_id=..., iteration=<N>,
  criteria_results=[{"criterion": "...", "passed": true, "note": "what you actually saw"}, ...],
  overall="accept" | "retry" | "abandon",
  change="<the single change to make next>"   # retry only
)
```

Rules the tool enforces, so follow them rather than fighting them:

- **Every frozen criterion gets a pass/fail and a note.** Notes describe what
  you saw ("the light is flat and frontal"), not what you want.
- **A retry names exactly one change.** One change per iteration is what makes
  the loop diagnosable — with three changes at once you learn nothing about
  which one helped.
- **`abandon` is a legitimate answer.** If the criteria cannot be met with this
  checkpoint or this prompt shape, say so and stop. Spinning through the cap
  wastes the user's time and your own.

### Step 5: Change one thing, and hold the seed

Seed discipline is the difference between iteration and a slot machine:

- **Changing prompt wording, weights, cfg, or steps → pass the SAME seed.**
  Then the difference you see is attributable to the change you made.
- **Changing the seed is itself the one change** — do it only when the
  composition is unlucky (bad crop, wrong pose, mangled subject) rather than
  wrong, and say so in the verdict.

Then go back to Step 2, applying exactly the change you named.

### Step 6: Stop

Stop when any of these happens:

- The verdict is `accept` — present the image and say briefly which criteria it
  meets.
- The verdict is `abandon` — say what could not be achieved and what would be
  needed (a different checkpoint, a LoRA, a different framing).
- The tool **refuses** the next generation because the iteration cap or the
  time budget is spent — report the best result so far, name the criteria still
  failing, and say what the next change would have been. Do **not** open a
  second session to get around the cap; the cap is the user's setting.

## Choosing a model

If the user names a style or the result is far off in look rather than content,
call `list_media_models` to see what checkpoints are installed and pass one
explicitly as `checkpoint=`. The list comes from the running ComfyUI, so it is
what can actually be loaded — never invent a model name.

## What good iteration looks like

```
rubric: orange cat / warm side light / no text / full body
1  seed 4471  "an orange cat on a windowsill"                  3/4 — light is flat        → retry: add "warm late afternoon side lighting"
2  seed 4471  + warm late afternoon side lighting              4/4 but tail cropped       → retry: change the seed (composition is unlucky)
3  seed 9182  same prompt                                      4/4                        → accept
```

Three iterations, one change each, and the reason each change was made is on
the record.
