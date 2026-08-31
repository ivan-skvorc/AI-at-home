import { safeLocalStorage } from "../settings/local";

/**
 * Image / video generation launches — the setup page's handoff to a new chat.
 *
 * Generating a picture is the same *kind* of act as starting a Democracy panel:
 * it begins a conversation, and it needs a few decisions (subject, shape, image
 * or clip) made before the first model call rather than negotiated in chat. So
 * it gets the same shape — a sidebar entry, its own setup page, and a one-shot
 * stash claimed by the new chat — instead of a modal or a hidden mode flag.
 *
 * What this module does NOT do is call the tools. The composer is *seeded*, not
 * sent: the run is an ordinary turn against the ordinary agent, which is what
 * keeps every path (local ComfyUI tools, the cloud image-generation skill, the
 * refine loop) reachable from one page. A dedicated endpoint would have had to
 * pick one of them at build time, and would silently do nothing on a machine
 * where that one is unavailable.
 *
 * Free of React and of `window` beyond the guarded storage facade, so the seed
 * text — the part that decides what the model is actually asked — is testable
 * on its own.
 */

export type ImageLaunchKind = "image" | "video";

/** Shape of the output, named the way a person asks for it. */
export type ImageLaunchAspect = "square" | "landscape" | "portrait" | "wide";

/**
 * Who writes the prompt the diffusion model actually receives.
 *
 * These are two different jobs, and merging them is how both are done badly.
 * `direct` is for someone who already has a prompt — the exact token string,
 * weights and all — and wants it submitted **unchanged**; a helpful rewrite
 * there destroys the thing being tested. `assisted` is for a description of the
 * *picture*, which a language model then turns into the prompt vocabulary a
 * diffusion model rewards (subject, composition, lens, lighting, style) plus
 * the negative prompt naming what to keep out.
 */
export type ImagePromptMode = "direct" | "assisted";

export type ImageLaunch = {
  kind: ImageLaunchKind;
  promptMode: ImagePromptMode;
  /** In `direct` mode the prompt verbatim; in `assisted` mode the brief. */
  prompt: string;
  /** Verbatim negative prompt. `direct` mode only — assisted writes its own. */
  negativePrompt?: string;
  /** The preset the numbers below were last seeded from. */
  aspect: ImageLaunchAspect;
  /** Output width in pixels. Explicit, because the run commits to it. */
  width: number;
  /** Output height in pixels. */
  height: number;
  /** Optional checkpoint name; empty means "whatever is configured". */
  checkpoint?: string;
  /** Run the refine loop (generate → look → judge → change one thing). */
  refine: boolean;
};

export const IMAGE_LAUNCH_ASPECTS: readonly ImageLaunchAspect[] = [
  "square",
  "landscape",
  "portrait",
  "wide",
];

export const IMAGE_PROMPT_MODES: readonly ImagePromptMode[] = [
  "assisted",
  "direct",
];

/**
 * Pixel sizes per aspect, sized for what a 24 GB consumer card actually runs —
 * the same reasoning as `media.image` / `media.video` in config.yaml. Video is
 * deliberately much smaller: frames multiply, so a clip at image resolution is
 * how a generation runs out of VRAM after several minutes rather than at once.
 *
 * These are **presets that seed the numbers**, not the numbers themselves. The
 * resolution is its own field because "landscape" is not a resolution: a person
 * who has a target size (a print, a wallpaper, a thumbnail sheet) had no way to
 * ask for it, and the aspect names cannot grow one entry per size without
 * becoming a worse number field.
 */
const IMAGE_DIMENSIONS: Record<
  ImageLaunchAspect,
  { width: number; height: number }
> = {
  square: { width: 1024, height: 1024 },
  landscape: { width: 1344, height: 768 },
  portrait: { width: 768, height: 1344 },
  wide: { width: 1536, height: 640 },
};

const VIDEO_DIMENSIONS: Record<
  ImageLaunchAspect,
  { width: number; height: number }
> = {
  square: { width: 640, height: 640 },
  landscape: { width: 832, height: 480 },
  portrait: { width: 480, height: 832 },
  wide: { width: 960, height: 416 },
};

export function launchDimensions(
  kind: ImageLaunchKind,
  aspect: ImageLaunchAspect,
): { width: number; height: number } {
  const table = kind === "video" ? VIDEO_DIMENSIONS : IMAGE_DIMENSIONS;
  return table[aspect] ?? table.landscape;
}

/**
 * Latent size is pixels / 8, so a dimension that is not a multiple of 8 is not
 * the size that runs — ComfyUI rounds it down inside the graph and the output
 * quietly differs from what was asked for.
 */
export const DIMENSION_STEP = 8;
export const MIN_DIMENSION = 64;

/**
 * Upper bounds are per-kind because the failure is per-kind. An oversized image
 * fails in seconds and costs nothing; frames multiply, so an oversized clip
 * runs for minutes before it runs out of VRAM. The video cap is above the 24 GB
 * preset (someone with a bigger card may legitimately want 1280×720) and well
 * below the image cap, which is the point.
 */
export function maxDimension(kind: ImageLaunchKind): number {
  return kind === "video" ? 1920 : 4096;
}

/** Is this a number a generation can actually be asked for? */
export function isValidDimension(
  value: unknown,
  kind: ImageLaunchKind = "image",
): value is number {
  return (
    typeof value === "number" &&
    Number.isFinite(value) &&
    value >= MIN_DIMENSION &&
    value <= maxDimension(kind)
  );
}

/** Clamp into range and snap to the latent grid. Reported, never silent. */
export function normalizeDimension(
  value: number,
  kind: ImageLaunchKind = "image",
): number {
  const clamped = Math.min(
    Math.max(Math.round(value), MIN_DIMENSION),
    maxDimension(kind),
  );
  const snapped = Math.round(clamped / DIMENSION_STEP) * DIMENSION_STEP;
  return Math.max(snapped, MIN_DIMENSION);
}

/**
 * The size the run will actually use: the entered numbers, snapped, with the
 * aspect preset as the fallback for a launch that carries none (a stash written
 * by a build from before the resolution was a field).
 */
export function resolveLaunchSize(launch: {
  kind: ImageLaunchKind;
  aspect: ImageLaunchAspect;
  width?: number;
  height?: number;
}): { width: number; height: number } {
  const preset = launchDimensions(launch.kind, launch.aspect);
  return {
    width: isValidDimension(launch.width, launch.kind)
      ? normalizeDimension(launch.width, launch.kind)
      : preset.width,
    height: isValidDimension(launch.height, launch.kind)
      ? normalizeDimension(launch.height, launch.kind)
      : preset.height,
  };
}

/**
 * Model families whose sampling runs at CFG 1.0 — guidance-distilled (Flux
 * dev/schnell) or step-distilled (turbo, lightning, LCM, Hyper-SD). The
 * negative branch is never evaluated there, so a negative prompt is not
 * *rejected*, it is silently ignored, which is the worst of the three outcomes.
 *
 * The name is the only signal this page has: it does not call the tools (that
 * is the whole seed-don't-send design), so it cannot ask ComfyUI what the file
 * is. The rule therefore errs toward **offering** the field — an unmatched name
 * counts as supported — because a wrongly hidden field removes a capability
 * outright, while a wrongly offered one is caught by the agent, which does have
 * `list_media_models` and is asked in the seed to say so.
 */
const CFG_ONE_MODEL_MARKERS = [
  "flux",
  "schnell",
  "turbo",
  "lightning",
  "lcm",
  "hyper",
];

/** Split a model filename into words: separators *and* camel-case humps. */
function modelNameTokens(raw: string): string[] {
  return raw
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .split(/[^A-Za-z0-9]+/)
    .map((token) => token.toLowerCase())
    .filter(Boolean);
}

/**
 * Does the selected model take a negative prompt at all?
 *
 * A marker matches a whole word (`turbo`, `lightning`) or a word the version
 * digits are glued onto (`flux1`) — never a word that merely starts with it, so
 * `hyperrealism` stays a normal checkpoint.
 */
export function supportsNegativePrompt(checkpoint?: string): boolean {
  const name = (checkpoint ?? "").trim();
  if (!name) return true;
  return !modelNameTokens(name).some((token) =>
    CFG_ONE_MODEL_MARKERS.some(
      (marker) =>
        token === marker ||
        (token.startsWith(marker) && /^\d/.test(token.slice(marker.length))),
    ),
  );
}

/** A launch needs something to draw and a size that can be rendered. */
export function isValidImageLaunch(launch: {
  kind?: ImageLaunchKind;
  prompt: string;
  width?: number;
  height?: number;
}): boolean {
  const kind = launch.kind ?? "image";
  if (launch.prompt.trim().length === 0) return false;
  if (launch.width !== undefined && !isValidDimension(launch.width, kind)) {
    return false;
  }
  if (launch.height !== undefined && !isValidDimension(launch.height, kind)) {
    return false;
  }
  return true;
}

/**
 * The message the composer is seeded with.
 *
 * Written as an instruction to the agent rather than as tool arguments, because
 * which tool can serve it is a runtime fact: `generate_image` when a local
 * ComfyUI is reachable, the cloud `image-generation` skill when it is not. The
 * dimensions are stated explicitly (a model asked for "landscape" picks its own
 * numbers, and they are usually the ones that do not fit in VRAM), and the
 * refine sentence names the loop by the criteria rule that makes it converge.
 *
 * The prompt mode is the load-bearing half. `direct` has to forbid the rewrite
 * a helpful assistant would otherwise perform — a prompt handed over verbatim
 * and then "improved" is a different experiment, and the user cannot see that
 * it happened. `assisted` has to *ask* for both halves and to require them in
 * the reply, because a negative prompt the agent invented and never showed
 * cannot be corrected.
 */
export function buildImageLaunchMessage(launch: ImageLaunch): string {
  const { width, height } = resolveLaunchSize(launch);
  const subject = launch.prompt.trim();
  const checkpoint = launch.checkpoint?.trim();
  const negatives = supportsNegativePrompt(checkpoint);
  const target = launch.kind === "video" ? "a short video clip" : "an image";
  const lines: string[] = [];

  if (launch.promptMode === "direct") {
    lines.push(
      `Generate ${target} from this prompt, exactly as written — do not rewrite, expand or improve it:`,
    );
    lines.push("");
    lines.push(subject);
    const negative = launch.negativePrompt?.trim();
    if (negatives && negative) {
      lines.push("");
      lines.push("Use this as the negative prompt, also verbatim:");
      lines.push("");
      lines.push(negative);
    }
  } else {
    lines.push(`Write the prompt for ${target}, then generate it. The brief:`);
    lines.push("");
    lines.push(subject);
    lines.push("");
    if (negatives) {
      lines.push(
        "Turn that into a detailed positive prompt (subject, composition, lens, lighting, style — diffusion models reward detail) and a matching negative prompt naming what to keep out. Show both in your reply before generating, so they can be judged and adjusted.",
      );
      lines.push(
        "If this checkpoint turns out to ignore negative prompts, say so and fold the exclusions into the positive prompt instead.",
      );
    } else {
      lines.push(
        "Turn that into a detailed positive prompt (subject, composition, lens, lighting, style — diffusion models reward detail). Show it in your reply before generating, so it can be judged and adjusted.",
      );
      lines.push(
        `Do not write a negative prompt: ${checkpoint} is a distilled model sampled at CFG 1, where the negative branch is never evaluated. Put the exclusions in the positive prompt instead.`,
      );
    }
  }

  lines.push("");
  lines.push(`Size: ${width}x${height} pixels.`);
  if (checkpoint) {
    lines.push(`Use the ${checkpoint} checkpoint.`);
  }
  if (launch.refine) {
    lines.push(
      "Use the image-refine loop: freeze 3-6 checkable criteria before the first attempt, look at each result, and change exactly one thing per iteration.",
    );
  }
  lines.push(
    "Prefer the local ComfyUI tools; if no local instance is reachable, say so and fall back to the cloud generation skill.",
  );
  return lines.join("\n");
}

const IMAGE_LAUNCH_KEY = "deerflow.image-launch";

/**
 * Fired the moment a launch is stashed, so a chat already sitting on
 * `/workspace/chats/new` claims it too. Navigating there from there is a no-op,
 * so a mount-only claim would silently drop the launch — the same trap the
 * Democracy handoff documents.
 */
export const IMAGE_LAUNCH_EVENT = "deer-flow:image-launch";

export function stashImageLaunch(launch: ImageLaunch): void {
  safeLocalStorage.setItem(IMAGE_LAUNCH_KEY, JSON.stringify(launch));
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(IMAGE_LAUNCH_EVENT));
  }
}

/** Read and clear the pending launch. Returns null when there is none. */
export function consumeImageLaunch(): ImageLaunch | null {
  const raw = safeLocalStorage.getItem(IMAGE_LAUNCH_KEY);
  if (!raw) return null;
  safeLocalStorage.removeItem(IMAGE_LAUNCH_KEY);
  return parseImageLaunch(raw);
}

/**
 * Parse a stashed launch, rejecting anything that is not dispatchable.
 *
 * Storage is shared with other tabs and survives upgrades, so a malformed or
 * stale blob must degrade to "no launch" rather than seeding a chat with a
 * half-built request. A blob from an older build is the ordinary case rather
 * than the exotic one — it carries no mode and no numbers — so those fall back
 * to `direct` (which is what the page used to do) and to the aspect preset.
 */
export function parseImageLaunch(raw: string): ImageLaunch | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof parsed !== "object" || parsed === null) return null;
  const candidate = parsed as Partial<ImageLaunch>;
  const prompt =
    typeof candidate.prompt === "string" ? candidate.prompt.trim() : "";
  if (!prompt) return null;
  const kind: ImageLaunchKind = candidate.kind === "video" ? "video" : "image";
  const aspect: ImageLaunchAspect =
    typeof candidate.aspect === "string" &&
    (IMAGE_LAUNCH_ASPECTS as readonly string[]).includes(candidate.aspect)
      ? candidate.aspect
      : "landscape";
  const promptMode: ImagePromptMode =
    candidate.promptMode === "assisted" ? "assisted" : "direct";
  const { width, height } = resolveLaunchSize({
    kind,
    aspect,
    width: typeof candidate.width === "number" ? candidate.width : undefined,
    height: typeof candidate.height === "number" ? candidate.height : undefined,
  });
  const checkpoint =
    typeof candidate.checkpoint === "string" && candidate.checkpoint.trim()
      ? candidate.checkpoint.trim()
      : undefined;
  const negativePrompt =
    promptMode === "direct" &&
    supportsNegativePrompt(checkpoint) &&
    typeof candidate.negativePrompt === "string" &&
    candidate.negativePrompt.trim()
      ? candidate.negativePrompt.trim()
      : undefined;
  return {
    kind,
    promptMode,
    prompt,
    negativePrompt,
    aspect,
    width,
    height,
    checkpoint,
    refine: candidate.refine === true,
  };
}
