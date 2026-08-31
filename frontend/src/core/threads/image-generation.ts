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

export type ImageLaunch = {
  kind: ImageLaunchKind;
  prompt: string;
  aspect: ImageLaunchAspect;
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

/**
 * Pixel sizes per aspect, sized for what a 24 GB consumer card actually runs —
 * the same reasoning as `media.image` / `media.video` in config.yaml. Video is
 * deliberately much smaller: frames multiply, so a clip at image resolution is
 * how a generation runs out of VRAM after several minutes rather than at once.
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

/** A launch needs something to draw; everything else has a default. */
export function isValidImageLaunch(launch: { prompt: string }): boolean {
  return launch.prompt.trim().length > 0;
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
 */
export function buildImageLaunchMessage(launch: ImageLaunch): string {
  const { width, height } = launchDimensions(launch.kind, launch.aspect);
  const subject = launch.prompt.trim();
  const lines: string[] = [];

  lines.push(
    launch.kind === "video"
      ? `Generate a short video clip: ${subject}`
      : `Generate an image: ${subject}`,
  );
  lines.push("");
  lines.push(`Size: ${width}x${height} (${launch.aspect}).`);
  if (launch.checkpoint?.trim()) {
    lines.push(`Use the ${launch.checkpoint.trim()} checkpoint.`);
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
 * half-built request.
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
  return {
    kind,
    prompt,
    aspect,
    checkpoint:
      typeof candidate.checkpoint === "string" && candidate.checkpoint.trim()
        ? candidate.checkpoint.trim()
        : undefined,
    refine: candidate.refine === true,
  };
}
