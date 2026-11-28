/**
 * The folded view of one joined run: assistant text per message, tool calls
 * per message and index, and which calls have answered. Only this run's
 * messages count: a `values` event carries the whole thread, so messages up
 * to its last user message (the prompt that started the run) are history.
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

/** The argument that says best what a call does (actions.py SUMMARY_KEYS). */
const SUMMARY_KEYS = ["command", "path", "image_path", "filepaths", "description"];
const MAX_SUMMARY = 200;

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
  const type = message.type ?? message.role;
  if (type === "AIMessageChunk" || type === "ai" || type === "AIMessage")
    return "assistant";
  if (type === "tool" || type === "ToolMessage" || type === "ToolMessageChunk")
    return "tool";
  if (type === "human" || type === "HumanMessage" || type === "user")
    return "user";
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

function foldResult(state, message) {
  if (typeof message.tool_call_id === "string" && message.tool_call_id)
    state.results.set(message.tool_call_id, {
      name: typeof message.name === "string" ? message.name : null,
    });
}

function foldChunk(state, message) {
  const kind = role(message);
  if (kind === "tool") return foldResult(state, message);
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
  if (kind === "tool") return foldResult(state, message);
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

/** The messages after the last user message: this run's part of a thread. */
function ownMessages(messages) {
  let start = 0;
  messages.forEach((message, index) => {
    if (record(message) && role(message) === "user") start = index + 1;
  });
  return messages.slice(start);
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
      for (const message of ownMessages(data.messages))
        if (record(message)) foldComplete(state, message);
  }
  return state;
}

/** Streamed assistant messages that carry text, in arrival order. */
export function assistantMessages(state) {
  return [...state.messages.values()].filter((entry) => entry.text);
}

function firstLine(value) {
  if (typeof value === "string") return value.trim().split(/\r?\n/)[0].trim();
  if (Array.isArray(value))
    return value
      .filter((item) => typeof item === "string" && item.trim())
      .slice(0, 5)
      .join(", ");
  return "";
}

/** One bounded line of a call's arguments: a bash command's first line, a path, else the first text. */
export function summarizeArgs(args) {
  if (!record(args)) return "";
  const keys = [...SUMMARY_KEYS, ...Object.keys(args)];
  for (const key of keys) {
    const text = firstLine(args[key]);
    if (text)
      return text.length > MAX_SUMMARY
        ? `${text.slice(0, MAX_SUMMARY)}...`
        : text;
  }
  return "";
}

function argsOf(call) {
  if (call.full) return call.full;
  try {
    const value = JSON.parse(call.args);
    return record(value) ? value : null;
  } catch {
    return null;
  }
}

/** This run's tool calls in arrival order: name, one line of arguments, and whether it answered. */
export function toolCalls(state) {
  const calls = [];
  for (const call of state.calls.values()) {
    if (!call.name) continue;
    calls.push({
      id: call.id,
      name: call.name,
      summary: summarizeArgs(argsOf(call)),
      done: !!call.id && state.results.has(call.id),
    });
  }
  return calls;
}
