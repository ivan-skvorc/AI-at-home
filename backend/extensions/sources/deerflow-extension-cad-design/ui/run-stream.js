import { extractPartialCode } from "./scad-text.js";

// The host binds a plugin tool as ext_<namespace>_<name>_<12 hex of a digest>.
const BOUND = /^ext_cad_design_scad_draft(?:_[0-9a-f]{12})?$/;

/** Whether a tool call is this package's `scad_draft`, under its bound name or bare. */
export function isScadDraft(name) {
  return (
    typeof name === "string" && (name === "scad_draft" || BOUND.test(name))
  );
}

/**
 * The folded view of one joined run: assistant text per message, tool calls
 * per message and index with their argument text, and tool results by call id.
 */
export function createRunState() {
  return {
    messages: new Map(),
    calls: new Map(),
    results: new Map(),
    ended: false,
    error: null,
  };
}

const record = (value) =>
  value !== null && typeof value === "object" && !Array.isArray(value);

function messageText(content) {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .map((block) =>
      typeof block === "string"
        ? block
        : block?.type === "text" && typeof block.text === "string"
          ? block.text
          : "",
    )
    .join("");
}

function role(message) {
  const type = message.type;
  if (type === "AIMessageChunk" || type === "ai" || type === "AIMessage")
    return "assistant";
  if (type === "tool" || type === "ToolMessage" || type === "ToolMessageChunk")
    return "tool";
  return null;
}

function messageEntry(state, id) {
  let entry = state.messages.get(id);
  if (!entry) {
    entry = { id, text: "" };
    state.messages.set(id, entry);
  }
  return entry;
}

function callEntry(state, key) {
  let entry = state.calls.get(key);
  if (!entry) {
    entry = { key, id: null, name: null, args: "", full: null };
    state.calls.set(key, entry);
  }
  return entry;
}

function readResult(content) {
  const text = typeof content === "string" ? content : messageText(content);
  let value = record(content) ? content : null;
  if (!value) {
    try {
      value = JSON.parse(text);
    } catch {
      const match = /"version_id"\s*:\s*"([A-Za-z0-9_-]{1,128})"/.exec(text);
      value = match ? { version_id: match[1] } : null;
    }
  }
  if (!record(value) || typeof value.version_id !== "string")
    return { version_id: null, error: text.slice(0, 500) };
  return {
    version_id: value.version_id,
    seq: Number.isInteger(value.seq) ? value.seq : null,
  };
}

function foldChunk(state, message) {
  const kind = role(message);
  if (kind === "tool") {
    if (typeof message.tool_call_id === "string")
      state.results.set(message.tool_call_id, {
        name: message.name ?? null,
        ...readResult(message.content),
      });
    return;
  }
  if (kind !== "assistant") return;
  const id = typeof message.id === "string" ? message.id : "_";
  const entry = messageEntry(state, id);
  entry.text += messageText(message.content);
  const chunks = Array.isArray(message.tool_call_chunks)
    ? message.tool_call_chunks
    : [];
  for (const part of chunks) {
    if (!record(part)) continue;
    const call = callEntry(
      state,
      `${id}:${Number.isInteger(part.index) ? part.index : 0}`,
    );
    if (typeof part.id === "string" && part.id) call.id = part.id;
    if (typeof part.name === "string" && part.name) call.name = part.name;
    if (typeof part.args === "string") call.args += part.args;
  }
}

function foldComplete(state, message) {
  const kind = role(message);
  if (kind === "tool") return foldChunk(state, message);
  if (kind !== "assistant" || !Array.isArray(message.tool_calls)) return;
  const id = typeof message.id === "string" ? message.id : "_";
  message.tool_calls.forEach((toolCall, index) => {
    if (!record(toolCall)) return;
    const call = callEntry(state, `${id}:${index}`);
    if (typeof toolCall.id === "string") call.id = toolCall.id;
    if (typeof toolCall.name === "string") call.name = toolCall.name;
    if (record(toolCall.args)) call.full = toolCall.args;
  });
}

/** Fold one SSE event of a joined run into `state`; unknown shapes are ignored. */
export function foldRunEvent(state, { event, data } = {}) {
  if (event === "end") state.ended = true;
  else if (event === "error") {
    state.error =
      record(data) && typeof data.message === "string"
        ? data.message
        : typeof data === "string"
          ? data
          : "error";
    state.ended = true;
  } else if (event === "messages") {
    if (Array.isArray(data) && record(data[0])) foldChunk(state, data[0]);
  } else if (event === "messages/partial" || event === "messages/complete") {
    if (Array.isArray(data))
      for (const message of data)
        if (record(message)) foldComplete(state, message);
  } else if (event === "values") {
    if (record(data) && Array.isArray(data.messages))
      for (const message of data.messages)
        if (record(message)) foldComplete(state, message);
  }
  return state;
}

/** Streamed assistant messages that carry text, in arrival order. */
export function assistantMessages(state) {
  return [...state.messages.values()].filter((entry) => entry.text);
}

/**
 * Every `scad_draft` call seen so far, in arrival order: its code (partial
 * while the arguments stream), whether the code is complete, and the stored
 * version once the tool has answered.
 */
export function scadCalls(state) {
  const calls = [];
  for (const call of state.calls.values()) {
    if (!isScadDraft(call.name)) continue;
    const result = call.id ? state.results.get(call.id) : undefined;
    let code = null;
    let complete = false;
    if (call.full && typeof call.full.code === "string") {
      code = call.full.code;
      complete = true;
    } else {
      ({ code, complete } = extractPartialCode(call.args));
    }
    calls.push({
      id: call.id,
      code,
      complete: complete || !!result,
      result: result?.version_id
        ? { version_id: result.version_id, seq: result.seq ?? null }
        : null,
      failed: result && !result.version_id ? result.error || "refused" : null,
    });
  }
  return calls;
}
