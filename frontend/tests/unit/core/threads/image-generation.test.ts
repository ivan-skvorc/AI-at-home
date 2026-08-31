import { describe, expect, test } from "@rstest/core";

import {
  buildImageLaunchMessage,
  isValidImageLaunch,
  launchDimensions,
  parseImageLaunch,
} from "@/core/threads/image-generation";

/**
 * The pure half of the generation launch: the numbers a click commits to, and
 * the sentence the model is actually asked.
 *
 * Both are load-bearing and neither is visible at review time. The dimensions
 * decide whether a run fits in VRAM (a video at image resolution does not, and
 * fails minutes in); the seed text decides which tool path is taken and whether
 * the refine loop's rules travel with the request.
 */
describe("launch dimensions", () => {
  test("video is sized far smaller than an image of the same shape", () => {
    const image = launchDimensions("image", "landscape");
    const video = launchDimensions("video", "landscape");
    expect(image).toEqual({ width: 1344, height: 768 });
    expect(video).toEqual({ width: 832, height: 480 });
    // Frames multiply: a clip at image resolution is how a generation runs out
    // of VRAM after several minutes rather than immediately.
    expect(video.width * video.height).toBeLessThan(image.width * image.height);
  });

  test("portrait is the landscape pair swapped, for both kinds", () => {
    for (const kind of ["image", "video"] as const) {
      const landscape = launchDimensions(kind, "landscape");
      const portrait = launchDimensions(kind, "portrait");
      expect(portrait.width).toBe(landscape.height);
      expect(portrait.height).toBe(landscape.width);
    }
  });
});

describe("launch validity", () => {
  test("a launch with nothing to draw is not dispatchable", () => {
    expect(isValidImageLaunch({ prompt: "   " })).toBe(false);
    expect(isValidImageLaunch({ prompt: "a red bicycle" })).toBe(true);
  });
});

describe("the seeded message", () => {
  const base = {
    kind: "image" as const,
    prompt: "a rain-slick Tokyo street at night",
    aspect: "landscape" as const,
    refine: false,
  };

  test("states the pixel size, because a model asked for 'landscape' picks its own", () => {
    expect(buildImageLaunchMessage(base)).toContain("1344x768");
  });

  test("names the fallback, so an unreachable ComfyUI is reported instead of guessed at", () => {
    expect(buildImageLaunchMessage(base)).toContain("fall back to the cloud");
  });

  test("the refine option carries the rules that make the loop converge", () => {
    const message = buildImageLaunchMessage({ ...base, refine: true });
    expect(message).toContain("criteria");
    expect(message).toContain("one thing per iteration");
    // Off by default: an unrequested loop spends four times the GPU minutes.
    expect(buildImageLaunchMessage(base)).not.toContain("image-refine");
  });

  test("a clip asks for a clip", () => {
    const message = buildImageLaunchMessage({ ...base, kind: "video" });
    expect(message).toContain("video clip");
    expect(message).toContain("832x480");
  });

  test("a checkpoint is named only when one was chosen", () => {
    expect(buildImageLaunchMessage(base)).not.toContain("checkpoint");
    expect(
      buildImageLaunchMessage({ ...base, checkpoint: "sdxl_base.safetensors" }),
    ).toContain("sdxl_base.safetensors");
  });
});

describe("parsing a stashed launch", () => {
  test("a launch without a prompt is not a launch", () => {
    expect(
      parseImageLaunch(JSON.stringify({ kind: "image", prompt: " " })),
    ).toBeNull();
    expect(parseImageLaunch("{oops")).toBeNull();
    expect(parseImageLaunch("null")).toBeNull();
  });

  test("unknown fields from an older or newer build degrade to defaults", () => {
    expect(
      parseImageLaunch(
        JSON.stringify({
          kind: "hologram",
          prompt: "a cat",
          aspect: "octagonal",
        }),
      ),
    ).toEqual({
      kind: "image",
      prompt: "a cat",
      aspect: "landscape",
      checkpoint: undefined,
      refine: false,
    });
  });

  test("refine is only on when it was explicitly on", () => {
    const parsed = parseImageLaunch(
      JSON.stringify({
        kind: "video",
        prompt: "a cat",
        aspect: "portrait",
        refine: "yes",
      }),
    );
    expect(parsed?.refine).toBe(false);
    expect(parsed?.kind).toBe("video");
    expect(parsed?.aspect).toBe("portrait");
  });
});
