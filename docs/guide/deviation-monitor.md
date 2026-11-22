# Deviation monitor: a second model keeps the run on your request

A long run can drift without failing. The agent reads a large file, the request
ages out of its window or is compacted away, and it settles into the task its
remaining context suggests, usually "summarise this", in place of what you
asked. Nothing errors. The deviation monitor is a second model that checks, on a
cadence you choose, whether the agent's recent work still serves your request,
and stops the run when it confirms a drift. It is a fork feature (FORK.md §57).

It is **off in every chat** until you turn it on in that chat.

## Turn it on in a chat

The compass button in the message box's tool row (**Deviation monitor off**)
opens a dialog:

- **Monitor model**, chosen with the same model picker as the rest of the app.
  The dialog preselects the model this chat's monitor used last, else the
  Settings default, else the chat's own model.
- **How often to check**:
  - **Every X steps** (1-50): agent steps within one reply. A step check judges
    the response that just arrived, **before its tool calls run**, so a stop
    prevents the drifting actions.
  - **Every N turns** (1-20): a turn is one message and the agent's work on it.
    The check runs once, just before the final answer of every Nth turn.
  - **Every turn**: the same as every 1 turn.

  A reply counts as one, however it runs: approving a tool call, a subagent
  batch's follow-up and a goal continuation carry on its step count, its turn
  and its one retry, and only your next message starts them again. A response
  the to-do list or the completion review sends back for more work is a step
  too; when the step due for a check is sent back, the next one is checked.

**Turn on** turns it on for this chat only; **Cancel** changes nothing. Click
the button again to change the model or cadence (**Save**), or to turn it off.
The status bar above the message box also has a one-click **Turn off**.
A run reads the chat's choice when it is sent, so a change made while the agent
works applies from your next message: the bar keeps the running run's status
with **Off from your next message**, or says **On from your next message** for
a run sent without the monitor.

**Settings → Deviation monitor** holds the defaults for new chats: **On for new
chats**, a default monitor model (or **The chat's model**) and a default cadence.
They are stored in this browser and apply to chats as they start; an existing
chat is never changed, and a new chat can still be switched off on its own. A
default model that has since left `config.yaml` is shown as **The chat's
model**, and that is what a new chat then uses.
Side chats are never monitored.

## What you see

While the monitor is on, a status bar above the message box shows its latest
report: **Watching** (no check yet in this reply), **Checking…** (with an
every-X-steps cadence only, from the start of the step being checked until its
verdict; an every-N-turns check runs after the final answer has streamed and
shows no separate status), **On track**,
**Unsure, not acted on**, **Possible drift, not confirmed**, **Drift confirmed,
retrying in smaller pieces**, **Stopped the run: it drifted from your request**
or **Off for this run** (the chat asked for something invalid, or you may not
use the chosen model). **Details** shows the reason, the kind of drift, your
request as the monitor understood it, and the model. The bar appears on the
normal and the custom-agent chat pages, and survives a reload. A report older
than the chat's latest run is not shown as current: a run sent while the
monitor was off writes nothing, so turning it back on starts from **Watching**.

## What a confirmed drift does

The monitor asks its model for one of three verdicts: on task, drifting or
unsure. Small models are noisy, so a "drifting" verdict is asked once more, and
the monitor acts only when both answers agree, or when one does and a mechanical
signal backs it: a partial file read, a truncated or externalized tool result,
three or more failed tool calls in the turn, a HarnessGuard flag, a compaction
during this run (a summary from an earlier run is shown to the monitor but is
no signal), or a nearly full window. An "unsure" verdict, a malformed reply, a
timeout or a provider error is shown and **never acted on**.

- **In Flash, Thinking and Pro**, a confirmed drift **stops the run**. The
  checked response keeps its text, loses its tool calls, and ends with a note
  that names the reason and your request. A final answer the monitor stopped
  stays visible with that note, marked as off-task. No reminder, review or goal
  continuation resumes the run. A goal on the chat gets no hidden continuation:
  it stays active for your next message, with the stand-down reason
  `deviation_stopped` unless the goal check names another blocker, and it is
  marked met only if the goal check judges that the visible answer meets it.
- **In a mode with subagents** (Ultra, Democracy, Plus Ultracode and Double
  Plus Ultracode), the first confirmed drift **retries once**: the drifting
  tool calls are dropped, a visible notice is added, and the agent gets a
  hidden reminder with your request, asking it to split the remaining work
  across subagents so each piece fits a window. A second confirmed drift in the
  same reply stops it. An Ultra or Democracy run that has used all the
  subagents it may start is stopped instead, since a retry could not split
  anything. The next check sees the held-back response as the agent wrote it,
  with a neutral line saying the monitor held it back, not the visible notice.

IM channels, scheduled tasks and API callers that do not send the setting are
never monitored.

## What it costs

- **The agent waits for each check.** A check every step can roughly double the
  time of a run on a local GPU.
- **Each check is a separate model call** (two when a drift is re-checked),
  billed to the run under `middleware:deviation_monitor` and counted by the
  spend caps from the next step.
- **A second local model** that does not fit beside the main one makes Ollama
  swap models on every check. The chat's own model avoids that.
- The main agent's request gains nothing: no tool, no prompt text, except the
  hidden reminder of a retry.

## Limits

- **It is advisory, not a security boundary.** Text the agent read can steer
  the monitor's model the same way it can steer the agent.
- The monitor sees a bounded picture: your request verbatim, the goal and to-do
  list, the last six steps of the turn (older ones shortened), the compaction
  summary and the mechanical signals. It is sized to the monitor model's own
  window and capped by `max_evidence_chars`. Older steps are dropped first;
  **your request is never cut**. When the request alone does not fit, the check
  is skipped and reported as unsure.
- With `pii_redaction.enabled`, personal data is redacted before the monitor
  sees it, as for the goal check.
- Subagents are not monitored themselves; only what they return is.
- A run that a loop, token or spend cap already stopped, and a response that a
  safety or length stop marked, is neither checked nor resumed.

## Operator settings

The feature is offered by default. `config.yaml`:

```yaml
deviation_monitor:
  enabled: true              # false hides the button and ignores any request
  judge_timeout_seconds: 60  # 5-600; a check that runs out of time is unsure
  max_evidence_chars: 24000  # 4000-200000; the model's window lowers it further
```

`GET /api/features` reports `deviation_monitor.enabled`, and the composer shows
the button only when it is `true`. Adding the block raised `config_version` to
77; `make config-upgrade` adds it to an existing `config.yaml`.

## For API callers

Send the choice in the run context on every run you want monitored:

```json
{"deviation_monitor": {"enabled": true, "model": "<configured model name>",
  "cadence": {"mode": "steps", "every": 3}}}
```

`mode` is `steps` (1-50) or `turns` (1-20). Without the key the monitor does
nothing. An invalid value turns the monitor off for that run with a reason in
the status channel; it never fails the run. The status arrives in the
`deviation_monitor` thread-state channel, in `updates` frames and on the
`POST /history` head; it is server-owned, so a client that writes it gets a
400. The shapes both sides rely on are in
[`contracts/deviation_monitor_contract.json`](../../contracts/deviation_monitor_contract.json),
and the request is described in
[backend/docs/API.md](../../backend/docs/API.md#deviation-monitor).

## Measuring it

`make drift-eval MODE=agent` runs the drift benchmark through the whole agent
loop (see the README's *Measuring Mission Drift on a Large Document*). Comparing
it with the monitor off and on, on the same model, is how the monitor is meant to
be accepted; the eval's agent mode does not send the monitor's run-context key
yet, and roadmap item 60 adds that option and the first measured runs.
