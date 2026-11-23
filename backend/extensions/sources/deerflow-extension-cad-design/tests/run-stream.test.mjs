import assert from "node:assert/strict";
import test from "node:test";

import {
  assistantMessages,
  createRunState,
  foldRunEvent,
  isScadDraft,
  scadCalls,
} from "../ui/run-stream.js";

// The name the host binds: ext_<namespace>_<tool>_<12 hex>.
const TOOL = "ext_cad_design_scad_draft_0123456789ab";
const chunk = (fields) => ({
  event: "messages",
  data: [
    { type: "AIMessageChunk", id: "m1", content: "", ...fields },
    { langgraph_node: "model" },
  ],
});

test("the bound tool name is recognised exactly", () => {
  assert.equal(isScadDraft(TOOL), true);
  assert.equal(isScadDraft("scad_draft"), true);
  assert.equal(isScadDraft("ext_cad_design_scad_draft"), true);
  assert.equal(isScadDraft("ext_cad_design_scad_draft_0123456789abc"), false);
  assert.equal(isScadDraft("ext_cad_cad_build_0123456789ab"), false);
  assert.equal(isScadDraft(null), false);
  assert.equal(isScadDraft("ext_other_scad_draft"), false);
});

test("text and tool-call chunks fold into one streaming message", () => {
  const state = createRunState();
  foldRunEvent(state, chunk({ content: "Drafting " }));
  foldRunEvent(
    state,
    chunk({
      content: [
        { type: "text", text: "a cube." },
        { type: "reasoning", reasoning: "x" },
      ],
    }),
  );
  foldRunEvent(
    state,
    chunk({
      tool_call_chunks: [
        { index: 0, id: "call_1", name: TOOL, args: '{"code": "cube(' },
      ],
    }),
  );
  foldRunEvent(
    state,
    chunk({
      tool_call_chunks: [
        { index: 0, id: null, name: null, args: "10);\\nsph" },
      ],
    }),
  );
  assert.deepEqual(
    assistantMessages(state).map((m) => m.text),
    ["Drafting a cube."],
  );
  const [call] = scadCalls(state);
  assert.equal(call.id, "call_1");
  assert.equal(call.code, "cube(10);\nsph");
  assert.equal(call.complete, false);
  assert.equal(call.result, null);
});

test("a tool result completes the call and carries its version", () => {
  const state = createRunState();
  foldRunEvent(
    state,
    chunk({
      tool_call_chunks: [
        { index: 0, id: "call_1", name: TOOL, args: '{"code":"cube(1);"}' },
      ],
    }),
  );
  foldRunEvent(state, {
    event: "messages",
    data: [
      {
        type: "tool",
        id: "t1",
        tool_call_id: "call_1",
        name: TOOL,
        content: '{"version_id":"v9","seq":3,"next":"x"}',
      },
      {},
    ],
  });
  const [call] = scadCalls(state);
  assert.equal(call.complete, true);
  assert.deepEqual(call.result, { version_id: "v9", seq: 3 });
});

test("values snapshots supply complete calls and results when chunks were missed", () => {
  const state = createRunState();
  foldRunEvent(state, {
    event: "values",
    data: {
      messages: [
        { type: "human", id: "h1", content: "make a cube" },
        {
          type: "ai",
          id: "a1",
          content: "Here.",
          tool_calls: [{ id: "c1", name: TOOL, args: { code: "cube(2);" } }],
        },
        {
          type: "tool",
          id: "t1",
          tool_call_id: "c1",
          name: TOOL,
          content: [{ type: "text", text: '{"version_id":"v2","seq":2}' }],
        },
      ],
    },
  });
  const [call] = scadCalls(state);
  assert.equal(call.code, "cube(2);");
  assert.deepEqual(call.result, { version_id: "v2", seq: 2 });
});

test("namespaced subgraph events are ignored and end and error are recorded", () => {
  const state = createRunState();
  foldRunEvent(state, {
    event: "messages|tools:1",
    data: [{ type: "AIMessageChunk", id: "s", content: "sub" }, {}],
  });
  assert.equal(assistantMessages(state).length, 0);
  foldRunEvent(state, { event: "error", data: { message: "boom" } });
  foldRunEvent(state, { event: "end", data: null });
  assert.equal(state.ended, true);
  assert.equal(state.error, "boom");
});

test("unknown shapes do not throw", () => {
  const state = createRunState();
  for (const data of [
    null,
    3,
    "x",
    [],
    [null],
    [{ type: "AIMessageChunk" }],
    { messages: "no" },
  ])
    for (const event of ["messages", "values", "metadata"])
      foldRunEvent(state, { event, data });
  assert.equal(scadCalls(state).length, 0);
});
