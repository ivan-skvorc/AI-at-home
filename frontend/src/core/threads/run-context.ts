import type { InputMode } from "../models/capabilities";
import { getLocalSettings } from "../settings/local";

import {
  type DemocracyGrading,
  democracyRunContext,
  isValidDemocracyPanel,
} from "./democracy";

/**
 * Derive the run context the backend actually reads from the composer's mode.
 *
 * The `mode` string itself is inert server-side — nothing in Python branches on
 * it. What drives behaviour is the set of booleans below, which is why this
 * derivation is the load-bearing part of a mode and why it lives in one pure
 * function: it used to be duplicated at the submit and regenerate call sites,
 * where the two copies could disagree and a regenerated turn would silently run
 * in a different mode than the original.
 */
export interface ModeDerivedContext {
  thinking_enabled: boolean;
  is_plan_mode: boolean;
  subagent_enabled: boolean;
  reasoning_effort?: "minimal" | "low" | "medium" | "high";
  democracy_participants?: string[];
  democracy_grading?: DemocracyGrading;
  max_total_subagents?: number;
  max_concurrent_subagents?: number;
}

interface ModeContextInput {
  mode: InputMode | undefined;
  reasoning_effort?: "minimal" | "low" | "medium" | "high";
  model_name?: string | undefined;
  democracy_participants?: string[];
  democracy_grading?: DemocracyGrading;
}

function defaultReasoningEffort(
  mode: InputMode | undefined,
): "minimal" | "low" | "medium" | "high" | undefined {
  switch (mode) {
    // A panel is the most expensive thing this app can do; running its members
    // at anything less than full effort spends the money without buying the
    // quality it was spent for.
    case "democracy":
    case "ultra":
      return "high";
    case "pro":
      return "medium";
    case "thinking":
      return "low";
    default:
      return undefined;
  }
}

export function deriveModeContext(
  context: ModeContextInput,
): ModeDerivedContext {
  const { mode } = context;
  const derived: ModeDerivedContext = {
    thinking_enabled: mode !== "flash",
    is_plan_mode: mode === "pro" || mode === "ultra" || mode === "democracy",
    // Democracy dispatches its entire panel through `task`, so it is an Ultra
    // run with an organizer brief on top.
    subagent_enabled: mode === "ultra" || mode === "democracy",
    reasoning_effort: context.reasoning_effort ?? defaultReasoningEffort(mode),
    // Cleared unless this really is a panel run. The caller spreads the whole
    // thread context first, and the roster is a thread-scoped key that outlives
    // a mode change — so switching a Democracy thread to Ultra would otherwise
    // keep sending the roster, and the organizer section (which only needs
    // `subagent_enabled`) would render on a run the user did not ask to be a
    // panel. Overwriting with `undefined` is what actually removes it.
    democracy_participants: undefined,
    // Cleared for the same reason as the roster: a scale left over from a panel
    // thread would otherwise put a scoreboard on an ordinary Ultra answer.
    democracy_grading: undefined,
  };

  const participants = context.democracy_participants ?? [];
  if (mode === "democracy" && isValidDemocracyPanel(participants)) {
    // The delegation budget must travel with the panel. The run-wide default
    // (6) is below what even a three-model panel needs across two phases, and
    // `task` calls beyond the ledger are discarded with their work lost — so
    // omitting this truncates the panel mid-run instead of failing loudly.
    Object.assign(
      derived,
      democracyRunContext({
        organizer: context.model_name ?? "",
        participants,
        task: "",
        grading: context.democracy_grading ?? "off",
      }),
    );
    // `democracyRunContext` also returns the organizer as `model_name`, which is
    // already the thread's selected model; drop it so this helper only ever adds
    // derived keys and never rewrites the user's model selection.
    delete (derived as { model_name?: string }).model_name;
  }

  return derived;
}

/**
 * Resolve the per-conversation internet switch for the run context
 * (fork feature, FORK.md §27).
 *
 * The backend treats **only an explicit `false`** as "go offline" — absent means
 * "no opinion" so non-web callers (IM channels, TUI, scheduler) keep the
 * operator's configured tools. This normalizes whatever localStorage holds into
 * that strict boolean, so a corrupted or hand-edited settings blob can never put
 * a string like `"false"` on the wire, where the backend would read it as
 * *enabled* and quietly hand an offline conversation its web tools back.
 */
export function resolveInternetEnabled(context: {
  internet_enabled?: unknown;
}): boolean {
  return context.internet_enabled !== false;
}

/**
 * The automatic-rename keys for the run context (fork feature, FORK.md §33).
 *
 * Read at submit time rather than at hook-render time so a preference changed
 * in Settings applies to the very next message, with no remount.
 *
 * Three states, and the difference between the last two is the whole point of
 * the model picker:
 *   - renaming off        -> `auto_title_enabled: false`, and no model key at
 *                            all (there is nothing to pick a model for).
 *   - "server default"    -> the model key is **omitted**, so the backend keeps
 *                            whatever `config.yaml -> title.model_name` says.
 *   - an explicit choice  -> the model name, or `""` for "rename without a
 *                            model call".
 * Sending `undefined` instead of omitting would be the same on the wire but is
 * left to the object spread deliberately: an omitted key is what the backend
 * reads as "no opinion".
 */
export function autoTitleRunContext(): {
  auto_title_enabled: boolean;
  auto_title_model_name?: string;
} {
  const { enabled, modelName } = getLocalSettings().autoTitle;
  if (!enabled) {
    return { auto_title_enabled: false };
  }
  return {
    auto_title_enabled: true,
    ...(modelName === undefined ? {} : { auto_title_model_name: modelName }),
  };
}
