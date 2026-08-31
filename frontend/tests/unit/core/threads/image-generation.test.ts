import { describe, expect, test } from "@rstest/core";

import {
  buildImageLaunchMessage,
  type ImageLaunch,
  isValidImageLaunch,
  launchDimensions,
  maxDimension,
  normalizeDimension,
  parseImageLaunch,
  resolveLaunchSize,
  supportsNegativePrompt,
} from "@/core/threads/image-generation";

/**
 * The pure half of the generation launch: the numbers a click commits to, and
 * the sentence the model is actually asked.
 *
 * Both are load-bearing and neither is visible at review time. The dimensions
 * decide whether a run fits in VRAM (a video at image resolution does not, and
 * fails minutes in); the seed text decides which tool path is taken, whether
 * the prompt survives unedited, and whether a negative prompt is written at
 * all.
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

  test("a clip may not be asked for at image resolution", () => {
    // The cap is per-kind because the failure is per-kind: an oversized image
    // fails in seconds, an oversized clip after minutes of rendering.
    expect(maxDimension("video")).toBeLessThan(maxDimension("image"));
    expect(isValidDimensionsFor("video", 3840, 480)).toBe(false);
    expect(isValidDimensionsFor("image", 3840, 480)).toBe(true);
  });

  test("an entered number is snapped to the latent grid, not silently floored", () => {
    // ComfyUI's latent is pixels / 8; an unsnapped value renders at a size the
    // user never asked for and never sees.
    expect(normalizeDimension(1001)).toBe(1000);
    expect(normalizeDimension(1005)).toBe(1008);
    expect(normalizeDimension(10)).toBe(64);
    expect(normalizeDimension(99999)).toBe(4096);
    expect(normalizeDimension(99999, "video")).toBe(1920);
  });

  test("a launch carrying no numbers falls back to its shape preset", () => {
    // A stash written before the resolution was a field must still be runnable.
    expect(resolveLaunchSize({ kind: "image", aspect: "square" })).toEqual({
      width: 1024,
      height: 1024,
    });
    expect(
      resolveLaunchSize({
        kind: "image",
        aspect: "square",
        width: 1600,
        height: 900,
      }),
    ).toEqual({ width: 1600, height: 904 });
  });
});

function isValidDimensionsFor(
  kind: "image" | "video",
  width: number,
  height: number,
): boolean {
  return isValidImageLaunch({ kind, prompt: "a cat", width, height });
}

describe("launch validity", () => {
  test("a launch with nothing to draw is not dispatchable", () => {
    expect(isValidImageLaunch({ prompt: "   " })).toBe(false);
    expect(isValidImageLaunch({ prompt: "a red bicycle" })).toBe(true);
  });

  test("a resolution outside what can be rendered blocks the launch", () => {
    // Cleared box → NaN. Rejecting it is the point: falling back to the preset
    // would generate at a size the user just deleted.
    expect(isValidDimensionsFor("image", Number.NaN, 768)).toBe(false);
    expect(isValidDimensionsFor("image", 32, 768)).toBe(false);
    expect(isValidDimensionsFor("image", 1344, 99999)).toBe(false);
    expect(isValidDimensionsFor("image", 1344, 768)).toBe(true);
  });
});

describe("negative prompt support", () => {
  test("an ordinary checkpoint, and none at all, take a negative prompt", () => {
    expect(supportsNegativePrompt(undefined)).toBe(true);
    expect(supportsNegativePrompt("   ")).toBe(true);
    expect(supportsNegativePrompt("sd_xl_base_1.0.safetensors")).toBe(true);
    expect(supportsNegativePrompt("juggernautXL_v9.safetensors")).toBe(true);
  });

  test("guidance- and step-distilled families do not", () => {
    // These sample at CFG 1, where the negative branch is never evaluated: the
    // prompt is not rejected, it is silently ignored.
    for (const name of [
      "flux1-dev-fp8.safetensors",
      "flux1-schnell.safetensors",
      "sd_xl_turbo_1.0_fp16.safetensors",
      "SDXL-Lightning-4step.safetensors",
      "dreamshaperXL_lightningDPMSDE.safetensors",
      "lcm_lora_sdxl.safetensors",
      "Hyper-SDXL-1step.safetensors",
    ]) {
      expect(supportsNegativePrompt(name)).toBe(false);
    }
  });

  test("a marker must be a whole word, so a normal model is not misread", () => {
    // The rule errs toward offering the field: a wrongly hidden one removes a
    // capability outright, a wrongly offered one is caught by the agent.
    expect(supportsNegativePrompt("hyperrealism_v3.safetensors")).toBe(true);
    expect(supportsNegativePrompt("fluxeon_mix.safetensors")).toBe(true);
  });
});

describe("the seeded message", () => {
  const base: ImageLaunch = {
    kind: "image",
    promptMode: "direct",
    prompt: "a rain-slick Tokyo street at night",
    aspect: "landscape",
    width: 1344,
    height: 768,
    refine: false,
  };

  test("states the pixel size, because a model asked for 'landscape' picks its own", () => {
    expect(buildImageLaunchMessage(base)).toContain("1344x768");
  });

  test("the entered resolution is the one the run is asked for", () => {
    const message = buildImageLaunchMessage({
      ...base,
      width: 1600,
      height: 900,
    });
    // Snapped to the latent grid, and stated — so the number that runs is the
    // number on the screen.
    expect(message).toContain("1600x904");
    expect(message).not.toContain("1344x768");
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
    const message = buildImageLaunchMessage({
      ...base,
      kind: "video",
      width: 832,
      height: 480,
    });
    expect(message).toContain("video clip");
    expect(message).toContain("832x480");
  });

  test("a checkpoint is named only when one was chosen", () => {
    expect(buildImageLaunchMessage(base)).not.toContain("checkpoint");
    expect(
      buildImageLaunchMessage({ ...base, checkpoint: "sdxl_base.safetensors" }),
    ).toContain("sdxl_base.safetensors");
  });

  describe("direct mode", () => {
    test("forbids the rewrite a helpful assistant would otherwise perform", () => {
      const message = buildImageLaunchMessage(base);
      // The whole point of the mode: an "improved" prompt is a different
      // experiment, and nothing on screen would show that it happened.
      expect(message).toContain("exactly as written");
      expect(message).toContain("do not rewrite");
      expect(message).toContain("a rain-slick Tokyo street at night");
      expect(message).not.toContain("Write the prompt");
    });

    test("passes a negative prompt through verbatim too", () => {
      const message = buildImageLaunchMessage({
        ...base,
        negativePrompt: "blurry, watermark",
      });
      expect(message).toContain("negative prompt, also verbatim");
      expect(message).toContain("blurry, watermark");
    });

    test("drops a negative prompt the chosen model would ignore", () => {
      const message = buildImageLaunchMessage({
        ...base,
        checkpoint: "flux1-dev.safetensors",
        negativePrompt: "blurry, watermark",
      });
      expect(message).not.toContain("blurry, watermark");
    });
  });

  describe("assisted mode", () => {
    const assisted: ImageLaunch = { ...base, promptMode: "assisted" };

    test("asks for both halves, and for them to be shown before the GPU is spent", () => {
      const message = buildImageLaunchMessage(assisted);
      expect(message).toContain("positive prompt");
      expect(message).toContain("negative prompt");
      // A prompt the agent invented and never showed cannot be corrected.
      expect(message).toContain("Show both in your reply before generating");
      expect(message).toContain("a rain-slick Tokyo street at night");
    });

    test("hedges on the model check it cannot make from a filename", () => {
      // The page reads a name; the agent can read /object_info. It gets the
      // last word, out loud, rather than the ignored prompt going unmentioned.
      expect(buildImageLaunchMessage(assisted)).toContain(
        "turns out to ignore negative prompts",
      );
    });

    test("asks for no negative prompt when the model is one that ignores it", () => {
      const message = buildImageLaunchMessage({
        ...assisted,
        checkpoint: "flux1-dev.safetensors",
      });
      expect(message).toContain("Do not write a negative prompt");
      expect(message).toContain("CFG 1");
      expect(message).toContain("positive prompt");
      expect(message).not.toContain("Show both in your reply");
    });
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
          promptMode: "telepathy",
        }),
      ),
    ).toEqual({
      kind: "image",
      promptMode: "direct",
      prompt: "a cat",
      negativePrompt: undefined,
      aspect: "landscape",
      width: 1344,
      height: 768,
      checkpoint: undefined,
      refine: false,
    });
  });

  test("a stash from before the resolution was a field still runs", () => {
    const parsed = parseImageLaunch(
      JSON.stringify({ kind: "video", prompt: "a cat", aspect: "portrait" }),
    );
    expect(parsed).toMatchObject({ width: 480, height: 832 });
  });

  test("an unrenderable resolution falls back to the preset rather than failing", () => {
    const parsed = parseImageLaunch(
      JSON.stringify({
        kind: "image",
        prompt: "a cat",
        aspect: "square",
        width: 0,
        height: 99999,
      }),
    );
    expect(parsed).toMatchObject({ width: 1024, height: 1024 });
  });

  test("a negative prompt is kept only where it is actually used", () => {
    const assisted = parseImageLaunch(
      JSON.stringify({
        promptMode: "assisted",
        prompt: "a cat",
        negativePrompt: "blurry",
      }),
    );
    // Assisted writes its own, so a stale verbatim one must not travel with it.
    expect(assisted?.negativePrompt).toBeUndefined();

    const ignored = parseImageLaunch(
      JSON.stringify({
        promptMode: "direct",
        prompt: "a cat",
        checkpoint: "flux1-dev.safetensors",
        negativePrompt: "blurry",
      }),
    );
    expect(ignored?.negativePrompt).toBeUndefined();

    const kept = parseImageLaunch(
      JSON.stringify({
        promptMode: "direct",
        prompt: "a cat",
        negativePrompt: " blurry ",
      }),
    );
    expect(kept?.negativePrompt).toBe("blurry");
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
