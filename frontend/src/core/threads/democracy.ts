import { resolveModelPrice } from "../models/sorting";
import type { Model } from "../models/types";
import { safeLocalStorage } from "../settings/local";

/**
 * Democracy panels — the launch spec for a multi-model deliberation run.
 *
 * A Democracy run is one **organizer** model that gathers the shared facts once
 * and then dispatches one identical assignment to several deliberately
 * different **panelist** models, before synthesizing what came back. This module
 * owns the pure half of that: what a valid panel is, what it will cost relative
 * to an ordinary answer, and the one-shot handoff from the setup dialog to the
 * new chat.
 *
 * Everything here is deliberately free of React and of `window` beyond the
 * guarded storage facade, so the arithmetic that decides how much money a click
 * is about to spend is unit-testable on its own.
 */

/** A panel needs at least two *different* models; one model asked twice is the
 * same opinion at twice the price. Mirrors the backend's own quorum. */
export const MIN_DEMOCRACY_PARTICIPANTS = 2;

/** Upper bound on panel size, mirroring the backend's roster cap. */
export const MAX_DEMOCRACY_PARTICIPANTS = 12;

/** Dispatch + cross-review. Each phase is one full model run per panelist. */
export const DEMOCRACY_PHASES = 2;

/** The backend clamps `max_total_subagents` to this range (1-50). */
const MAX_TOTAL_SUBAGENTS = 50;

/**
 * Headroom on top of the panel's own phases, so the organizer can retry a
 * failed panelist without the delegation ledger cutting the run short. Excess
 * `task` calls are *discarded and their work lost*, so a budget sized exactly
 * to the happy path turns one transient failure into a silently smaller panel.
 */
const DEMOCRACY_BUDGET_HEADROOM = 2;

/**
 * How the organizer scores each panelist's contribution, chosen at setup.
 *
 * `"off"` is a real choice, not an absence: a user who did not ask for a
 * scoreboard should not get one appended to every answer.
 */
export type DemocracyGrading = "off" | "five_point" | "boolean";

export const DEMOCRACY_GRADING_OPTIONS: readonly DemocracyGrading[] = [
  "off",
  "five_point",
  "boolean",
];

export interface DemocracyLaunch {
  /** Model that collects the shared facts, dispatches, and synthesizes. */
  organizer: string;
  /** Panelist models, in the user's chosen order. */
  participants: string[];
  /** The question put to the panel. */
  task: string;
  /** How the organizer grades panelists each turn. */
  grading: DemocracyGrading;
}

/**
 * The `task` allowance a panel needs for the whole run.
 *
 * Sized as participants x phases plus headroom, because the run-wide delegation
 * ledger (default 6) is far below what even a three-model panel needs across two
 * phases, and the frontend is the only place that knows the panel size.
 */
export function democracyDelegationBudget(participantCount: number): number {
  const needed =
    participantCount * DEMOCRACY_PHASES + DEMOCRACY_BUDGET_HEADROOM;
  return Math.max(1, Math.min(MAX_TOTAL_SUBAGENTS, needed));
}

/** Whether a roster can actually be dispatched as a panel. */
export function isValidDemocracyPanel(
  participants: readonly string[],
): boolean {
  const chosen = participants.filter((name) => name.length > 0);
  return (
    chosen.length >= MIN_DEMOCRACY_PARTICIPANTS &&
    chosen.length <= MAX_DEMOCRACY_PARTICIPANTS &&
    new Set(chosen).size === chosen.length
  );
}

/**
 * Clamp a requested panel size into the supported range.
 *
 * A non-finite value (an emptied number input) collapses to the minimum rather
 * than to `NaN` slots, so the dialog can never render an unbounded list.
 */
export function clampParticipantCount(count: number): number {
  if (!Number.isFinite(count)) return MIN_DEMOCRACY_PARTICIPANTS;
  return Math.max(
    MIN_DEMOCRACY_PARTICIPANTS,
    Math.min(MAX_DEMOCRACY_PARTICIPANTS, Math.floor(count)),
  );
}

export interface DemocracyCostEstimate {
  /** Full model runs the panel dispatches, across both phases. */
  runs: number;
  /**
   * Roughly how many times a single answer from the organizer this panel's
   * *rates* come to, per phase. Null when the organizer has no configured price
   * (nothing to compare against).
   */
  rateMultiple: number | null;
  /** Panelists with no configured price, which therefore count as zero. */
  unpricedParticipants: string[];
}

function blendedRate(model: Model | undefined): number | null {
  if (!model) return null;
  const price = resolveModelPrice(model);
  if (!price) return null;
  // Input and output rates summed: a crude blend, but it moves in the right
  // direction for every model and needs no token estimate to be honest about.
  const rate = price.input + price.output;
  return rate > 0 ? rate : null;
}

/**
 * Estimate what a panel costs relative to a single answer, at list rates.
 *
 * Deliberately a **rate** comparison rather than a currency figure: predicting
 * a run's token count would be a guess dressed as a number, and this fork's cost
 * surfaces (FORK.md §7) only ever report money that was actually spent. A
 * multiple is computable from data already on `/api/models` and is the thing the
 * user actually needs to know before clicking — that this costs several times
 * what the same question costs an ordinary chat.
 *
 * Unpriced (local) models contribute zero, matching every other cost surface in
 * this fork, and are named so a suspiciously low multiple explains itself.
 */
export function estimateDemocracyCost(
  launch: Pick<DemocracyLaunch, "organizer" | "participants">,
  models: readonly Model[],
): DemocracyCostEstimate {
  const byName = new Map(models.map((model) => [model.name, model]));
  const organizerRate = blendedRate(byName.get(launch.organizer));
  const unpricedParticipants: string[] = [];
  let panelRate = 0;
  for (const name of launch.participants) {
    const rate = blendedRate(byName.get(name));
    if (rate === null) {
      unpricedParticipants.push(name);
      continue;
    }
    panelRate += rate;
  }
  return {
    runs: launch.participants.length * DEMOCRACY_PHASES,
    rateMultiple:
      organizerRate === null || panelRate === 0
        ? null
        : Math.round((panelRate / organizerRate) * 10) / 10,
    unpricedParticipants,
  };
}

/**
 * The run context a Democracy launch contributes.
 *
 * `max_total_subagents` is the load-bearing part: without it the run-wide
 * delegation ledger silently truncates the panel partway through phase two, and
 * the organizer synthesizes from whichever panelists happened to fit.
 */
export function democracyRunContext(launch: DemocracyLaunch): {
  model_name: string;
  democracy_participants: string[];
  democracy_grading: DemocracyGrading | undefined;
  max_total_subagents: number;
  max_concurrent_subagents: number;
} {
  return {
    model_name: launch.organizer,
    democracy_participants: [...launch.participants],
    // "off" is sent as absent rather than as a value: the backend's own rule is
    // that an unrecognized scale means no grading, so the two agree by default
    // instead of by a shared magic string.
    democracy_grading: launch.grading === "off" ? undefined : launch.grading,
    max_total_subagents: democracyDelegationBudget(launch.participants.length),
    // Asking for the whole panel at once is the point — they are independent by
    // construction. The backend still clamps this to the process-wide execution
    // pool, so a larger panel queues rather than over-subscribing.
    max_concurrent_subagents: launch.participants.length,
  };
}

/**
 * Files the setup page attached to the task, carried to the chat it opens.
 *
 * Deliberately **in memory**, not in the stash beside the rest of the launch:
 * a `File` is a handle to browser-held bytes and does not survive
 * `JSON.stringify`, so the alternatives were reading every attachment into a
 * data URL (blowing the localStorage quota on the first PDF) or uploading before
 * a thread exists to upload to. The setup page navigates client-side, so the
 * module lives across that hop.
 *
 * The cost is honest and bounded: a hard reload between setup and chat loses the
 * attachments while the text half of the launch survives. That degrades to a
 * panel with no files rather than to a broken one, and the user can re-attach in
 * the composer — which is where the files end up anyway.
 */
let pendingDemocracyFiles: File[] = [];

export function stashDemocracyFiles(files: readonly File[]): void {
  pendingDemocracyFiles = [...files];
}

/** Take the pending attachments, clearing them so they are used exactly once. */
export function consumeDemocracyFiles(): File[] {
  const files = pendingDemocracyFiles;
  pendingDemocracyFiles = [];
  return files;
}

const DEMOCRACY_LAUNCH_KEY = "deerflow.democracy-launch";

/**
 * Fired when a launch is stashed, so an already-open new chat can claim it.
 *
 * Navigating to `/workspace/chats/new` from a chat that is already `/new` does
 * not remount anything, so the receiving side cannot rely on mounting to notice
 * a new launch. Same pattern as `THREAD_CHAT_RESET_EVENT`.
 */
export const DEMOCRACY_LAUNCH_EVENT = "deer-flow:democracy-launch";

/**
 * Hand a launch from the setup dialog to the new chat it opens.
 *
 * The dialog cannot write the thread's context directly: a new chat mints its
 * thread id inside the chat instance, after navigation. So the spec is stashed
 * under a single well-known key and **consumed once** on the other side — a
 * leftover stash would otherwise turn the user's next ordinary new chat into a
 * surprise panel.
 */
export function stashDemocracyLaunch(launch: DemocracyLaunch): void {
  safeLocalStorage.setItem(DEMOCRACY_LAUNCH_KEY, JSON.stringify(launch));
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(DEMOCRACY_LAUNCH_EVENT));
  }
}

/** Read and clear the pending launch. Returns null when there is none. */
export function consumeDemocracyLaunch(): DemocracyLaunch | null {
  const raw = safeLocalStorage.getItem(DEMOCRACY_LAUNCH_KEY);
  if (!raw) {
    // No launch to claim means any files still sitting here belong to an
    // abandoned setup; drop them rather than let them ride along with whatever
    // panel is started next.
    pendingDemocracyFiles = [];
    return null;
  }
  safeLocalStorage.removeItem(DEMOCRACY_LAUNCH_KEY);
  return parseDemocracyLaunch(raw);
}

/**
 * Parse a stashed launch, rejecting anything that is not a dispatchable panel.
 *
 * Storage is shared with other tabs and survives upgrades, so a malformed or
 * stale blob must degrade to "no panel" rather than starting a run with a
 * half-built roster.
 */
export function parseDemocracyLaunch(raw: string): DemocracyLaunch | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== "object") return null;
  const { organizer, participants, task, grading } = parsed as Record<
    string,
    unknown
  >;
  if (typeof organizer !== "string" || organizer.length === 0) return null;
  if (typeof task !== "string") return null;
  if (!Array.isArray(participants)) return null;
  const roster = participants.filter(
    (name): name is string => typeof name === "string" && name.length > 0,
  );
  if (!isValidDemocracyPanel(roster)) return null;
  return {
    organizer,
    participants: roster,
    task,
    // An unrecognized or missing scale degrades to no grading rather than
    // failing the whole launch — a stash written by an older build still starts
    // a usable panel, it just does not score it.
    grading: isDemocracyGrading(grading) ? grading : "off",
  };
}

function isDemocracyGrading(value: unknown): value is DemocracyGrading {
  return (
    typeof value === "string" &&
    (DEMOCRACY_GRADING_OPTIONS as readonly string[]).includes(value)
  );
}
