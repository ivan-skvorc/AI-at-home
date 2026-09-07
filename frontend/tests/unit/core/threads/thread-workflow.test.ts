/**
 * A conversation remembers what it was running with.
 *
 * The per-thread selection in `localStorage` keeps two open chats independent,
 * but it only knows the conversations *this browser* has touched — so anywhere
 * else the selection fell back to the app default and an older chat opened on
 * whichever model happened to be selected last. Recording it on the thread
 * makes it a property of the conversation instead.
 *
 * The properties below are the ones that are silent when broken: a read that
 * half-succeeds would partly override the user's live selection, a change
 * detector that is too eager would PATCH on every render, and a patch that
 * merges instead of replacing would leave a stale subagent model behind for a
 * chat that has left Ultra mode.
 */
import { describe, expect, test } from "@rstest/core";

import {
  THREAD_WORKFLOW_METADATA_KEY,
  buildThreadWorkflowPatch,
  readThreadWorkflow,
  workflowChanged,
  workflowOfContext,
} from "@/core/threads/thread-workflow";

const FULL = {
  model_name: "claude-opus-5",
  subagent_model_name: "ollama:llama3",
  mode: "ultra",
  reasoning_effort: "high",
};

describe("readThreadWorkflow", () => {
  test("reads a recorded selection", () => {
    expect(
      readThreadWorkflow({ [THREAD_WORKFLOW_METADATA_KEY]: FULL }),
    ).toEqual(FULL);
  });

  test("a thread that never recorded one reports null", () => {
    // Null, not `{}` — "nothing recorded" has to be distinguishable from "an
    // empty selection", because only the first leaves the user's choice alone.
    expect(readThreadWorkflow({})).toBeNull();
    expect(readThreadWorkflow(null)).toBeNull();
    expect(readThreadWorkflow(undefined)).toBeNull();
  });

  test("drops unrecognized and non-string fields rather than failing", () => {
    expect(
      readThreadWorkflow({
        [THREAD_WORKFLOW_METADATA_KEY]: {
          model_name: "claude-opus-5",
          mode: 5,
          api_key: "sk-live-secret",
          reasoning_effort: "",
        },
      }),
    ).toEqual({ model_name: "claude-opus-5" });
  });

  test("a non-object entry reports null", () => {
    expect(
      readThreadWorkflow({ [THREAD_WORKFLOW_METADATA_KEY]: "claude-opus-5" }),
    ).toBeNull();
    expect(
      readThreadWorkflow({ [THREAD_WORKFLOW_METADATA_KEY]: ["claude-opus-5"] }),
    ).toBeNull();
  });
});

describe("workflowOfContext", () => {
  test("keeps only the workflow fields", () => {
    expect(
      workflowOfContext({
        ...FULL,
        // Per-conversation, but about how the *next* turn runs rather than what
        // this conversation is — so deliberately not recorded.
        internet_enabled: false,
        democracy_participants: ["a", "b"],
      } as Parameters<typeof workflowOfContext>[0]),
    ).toEqual(FULL);
  });

  test("an empty context records nothing", () => {
    expect(workflowOfContext({})).toEqual({});
  });
});

describe("workflowChanged", () => {
  test("an unrecorded thread with a real selection is a change", () => {
    expect(workflowChanged(null, { model_name: "claude-opus-5" })).toBe(true);
  });

  test("the same selection is not a change", () => {
    // The composer re-reports its context on every render pass that touches it;
    // without this the chat would PATCH its own metadata continuously.
    expect(workflowChanged(FULL, { ...FULL })).toBe(false);
  });

  test("key order is not a change", () => {
    expect(
      workflowChanged(FULL, {
        reasoning_effort: "high",
        mode: "ultra",
        subagent_model_name: "ollama:llama3",
        model_name: "claude-opus-5",
      }),
    ).toBe(false);
  });

  test("a different model, mode or subagent model is a change", () => {
    expect(workflowChanged(FULL, { ...FULL, model_name: "gpt-5" })).toBe(true);
    expect(workflowChanged(FULL, { ...FULL, mode: "flash" })).toBe(true);
    expect(
      workflowChanged(FULL, {
        ...FULL,
        subagent_model_name: "claude-haiku-4-5",
      }),
    ).toBe(true);
  });

  test("a dropped field is a change", () => {
    // Leaving Ultra mode drops the subagent model, and the record has to follow.
    const withoutSubagent = { ...FULL, subagent_model_name: undefined };
    delete withoutSubagent.subagent_model_name;
    expect(workflowChanged(FULL, withoutSubagent)).toBe(true);
  });

  test("an empty selection never triggers a write", () => {
    // A chat whose models have not resolved yet reports nothing; writing that
    // would erase a real recorded selection on every cold open.
    expect(workflowChanged(FULL, {})).toBe(false);
    expect(workflowChanged(null, {})).toBe(false);
  });
});

describe("buildThreadWorkflowPatch", () => {
  test("replaces the whole object rather than merging", () => {
    // A conversation that leaves Ultra mode must lose its subagent model; a
    // merge would leave the stale one to be read back as its choice.
    expect(buildThreadWorkflowPatch({ model_name: "gpt-5" })).toEqual({
      [THREAD_WORKFLOW_METADATA_KEY]: { model_name: "gpt-5" },
    });
  });
});
