import assert from "node:assert/strict";
import test from "node:test";

import {
  assistantMessages,
  createRunState,
  foldRunEvent,
  summarizeArgs,
  toolCalls,
} from "../ui/run-stream.js";

const chunk = (fields) => ({
  event: "messages",
  data: [
    { type: "AIMessageChunk", id: "m1", content: "", ...fields },
    { langgraph_node: "model" },
  ],
});
const RENDER =
  "python3 /mnt/skills/public/cad-modeling/scripts/cadkit.py render model.scad --design /mnt/user-data/outputs/design --print-layout";

test("text and tool-call chunks fold into one streaming message and call", () => {
  const state = createRunState();
  foldRunEvent(state, chunk({ content: "Rendering " }));
  foldRunEvent(
    state,
    chunk({
      content: [
        { type: "text", text: "v1." },
        { type: "reasoning", reasoning: "x" },
      ],
    }),
  );
  const args = JSON.stringify({ command: `${RENDER}\necho done` });
  foldRunEvent(
    state,
    chunk({
      tool_call_chunks: [
        { index: 0, id: "call_1", name: "bash", args: args.slice(0, 20) },
      ],
    }),
  );
  // Half the arguments: the call shows its name, without a summary yet.
  assert.deepEqual(toolCalls(state), [
    { id: "call_1", name: "bash", summary: "", done: false },
  ]);
  foldRunEvent(
    state,
    chunk({
      tool_call_chunks: [
        { index: 0, id: null, name: null, args: args.slice(20) },
      ],
    }),
  );
  assert.deepEqual(
    assistantMessages(state).map((m) => m.text),
    ["Rendering v1."],
  );
  assert.deepEqual(toolCalls(state), [
    { id: "call_1", name: "bash", summary: RENDER, done: false },
  ]);
});

test("a tool result marks its call answered and counts once", () => {
  const state = createRunState();
  foldRunEvent(
    state,
    chunk({
      tool_call_chunks: [
        { index: 0, id: "call_1", name: "bash", args: '{"command":"ls"}' },
      ],
    }),
  );
  const result = {
    event: "messages",
    data: [
      {
        type: "tool",
        id: "t1",
        tool_call_id: "call_1",
        name: "bash",
        content: "v1: 2/2 bodies rendered",
      },
      { langgraph_node: "tools" },
    ],
  };
  foldRunEvent(state, result);
  foldRunEvent(state, result);
  assert.equal(state.results.size, 1);
  assert.equal(toolCalls(state)[0].done, true);
});

test("a values event folds only this run's messages, after the last user message", () => {
  const state = createRunState();
  foldRunEvent(state, {
    event: "values",
    data: {
      messages: [
        { type: "human", id: "h0", content: "first prompt" },
        {
          type: "ai",
          id: "a0",
          content: "",
          tool_calls: [{ id: "old", name: "bash", args: { command: "old" } }],
        },
        {
          type: "tool",
          id: "t0",
          tool_call_id: "old",
          name: "bash",
          content: "",
        },
        { type: "human", id: "h1", content: "this prompt" },
        {
          type: "ai",
          id: "a1",
          content: "",
          tool_calls: [
            {
              id: "new",
              name: "read_file",
              args: { path: "/mnt/x/report.json" },
            },
          ],
        },
      ],
    },
  });
  assert.deepEqual(toolCalls(state), [
    {
      id: "new",
      name: "read_file",
      summary: "/mnt/x/report.json",
      done: false,
    },
  ]);
  assert.equal(state.results.size, 0);
});

test("end and error events end the run; malformed events are ignored", () => {
  const state = createRunState();
  for (const event of [
    { event: "messages", data: "nope" },
    { event: "messages", data: [null] },
    { event: "values", data: { messages: "x" } },
    { event: "messages/complete", data: [42, { type: "ai", tool_calls: "x" }] },
    {},
  ])
    foldRunEvent(state, event);
  assert.equal(state.ended, false);
  assert.deepEqual(toolCalls(state), []);
  foldRunEvent(state, { event: "error", data: { message: "boom" } });
  assert.equal(state.ended, true);
  assert.equal(state.error, "boom");
  const ended = foldRunEvent(createRunState(), { event: "end", data: null });
  assert.equal(ended.ended, true);
  assert.equal(ended.error, null);
});

test("a call summary is one bounded line of the telling argument", () => {
  assert.equal(summarizeArgs({ description: "x", command: "a\nb" }), "a");
  assert.equal(
    summarizeArgs({ filepaths: ["/a", "/b", "", 3, "/c", "/d", "/e", "/f"] }),
    "/a, /b, /c, /d, /e",
  );
  assert.equal(summarizeArgs({ other: "fallback" }), "fallback");
  assert.equal(summarizeArgs({ command: "x".repeat(500) }).length, 203);
  assert.equal(summarizeArgs(null), "");
  assert.equal(summarizeArgs({ n: 1 }), "");
});
