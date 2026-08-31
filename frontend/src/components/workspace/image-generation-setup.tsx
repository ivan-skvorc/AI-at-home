"use client";

import { ImageIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";
import {
  buildImageLaunchMessage,
  DIMENSION_STEP,
  IMAGE_LAUNCH_ASPECTS,
  type ImageLaunch,
  type ImageLaunchAspect,
  type ImageLaunchKind,
  type ImagePromptMode,
  isValidDimension,
  isValidImageLaunch,
  launchDimensions,
  maxDimension,
  MIN_DIMENSION,
  resolveLaunchSize,
  stashImageLaunch,
  supportsNegativePrompt,
} from "@/core/threads/image-generation";

/**
 * Setup for a generation run: who writes the prompt, what to make, at what
 * resolution, with which model, and whether to iterate on it.
 *
 * A **full page**, not a modal, for the same reason Democracy is one: this is
 * the start of a conversation rather than a preference being adjusted. It seeds
 * the composer instead of sending, so the request is visible and editable
 * before anything spends GPU minutes on it — which matters more here than for a
 * chat message, because a video is minutes per attempt.
 *
 * Two of the controls are the ones that decide whether the run is the run that
 * was asked for. The prompt-mode toggle picks between a prompt submitted
 * **verbatim** and a brief the assistant turns into a positive/negative pair —
 * one page cannot serve both silently, because the helpful rewrite that makes
 * the second work destroys the first. And the resolution is two numbers rather
 * than a shape name, because a shape name is not a size: the preset fills the
 * numbers in, and anyone with a target size can overwrite them.
 */
export function ImageGenerationSetup() {
  const { t } = useI18n();
  const router = useRouter();

  const [kind, setKind] = useState<ImageLaunchKind>("image");
  const [promptMode, setPromptMode] = useState<ImagePromptMode>("assisted");
  const [prompt, setPrompt] = useState("");
  const [negativePrompt, setNegativePrompt] = useState("");
  const [aspect, setAspect] = useState<ImageLaunchAspect>("landscape");
  const [widthText, setWidthText] = useState(() =>
    String(launchDimensions("image", "landscape").width),
  );
  const [heightText, setHeightText] = useState(() =>
    String(launchDimensions("image", "landscape").height),
  );
  const [checkpoint, setCheckpoint] = useState("");
  const [refine, setRefine] = useState(false);

  // An empty or non-numeric box is NaN, which fails validation rather than
  // quietly falling back to the preset the user just cleared.
  const width = Number.parseInt(widthText, 10);
  const height = Number.parseInt(heightText, 10);
  const negativesSupported = supportsNegativePrompt(checkpoint);

  /** Presets seed the numbers; they do not replace them. */
  const seedSize = useCallback(
    (nextKind: ImageLaunchKind, nextAspect: ImageLaunchAspect) => {
      const preset = launchDimensions(nextKind, nextAspect);
      setWidthText(String(preset.width));
      setHeightText(String(preset.height));
    },
    [],
  );

  const launch: ImageLaunch = {
    kind,
    promptMode,
    prompt,
    negativePrompt:
      promptMode === "direct" && negativesSupported
        ? negativePrompt.trim() || undefined
        : undefined,
    aspect,
    width,
    height,
    checkpoint: checkpoint.trim() || undefined,
    refine,
  };
  const hasPrompt = prompt.trim().length > 0;
  const isValid = isValidImageLaunch(launch);
  const sizeIsValid =
    isValidDimension(width, kind) && isValidDimension(height, kind);
  const effectiveSize = resolveLaunchSize(launch);

  const handleStart = useCallback(() => {
    if (!isValid) return;
    stashImageLaunch({ ...launch, prompt: prompt.trim() });
    router.push("/workspace/chats/new");
    // `launch` is derived per render; the fields it is built from are the deps.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    aspect,
    checkpoint,
    height,
    isValid,
    kind,
    negativePrompt,
    prompt,
    promptMode,
    refine,
    router,
    width,
  ]);

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className="overflow-y-auto">
        <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 p-4 sm:p-6">
          <div>
            <h1 className="flex items-center gap-2 text-xl font-semibold">
              <ImageIcon className="size-5" />
              {t.imageGeneration.title}
            </h1>
            <p className="text-muted-foreground mt-1 text-sm">
              {t.imageGeneration.description}
            </p>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium" htmlFor="image-kind">
              {t.imageGeneration.kind}
            </label>
            <Select
              value={kind}
              onValueChange={(next) => {
                const nextKind = next as ImageLaunchKind;
                setKind(nextKind);
                seedSize(nextKind, aspect);
              }}
            >
              <SelectTrigger id="image-kind" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="image">
                  {t.imageGeneration.kindImage}
                </SelectItem>
                <SelectItem value="video">
                  {t.imageGeneration.kindVideo}
                </SelectItem>
              </SelectContent>
            </Select>
            {kind === "video" && (
              <p className="text-muted-foreground text-xs">
                {t.imageGeneration.videoHint}
              </p>
            )}
          </div>

          <div className="flex flex-col gap-1.5">
            <span className="text-sm font-medium">
              {t.imageGeneration.promptMode}
            </span>
            <ToggleGroup
              type="single"
              variant="outline"
              value={promptMode}
              onValueChange={(next) => {
                // Radix allows deselecting the active item; there is no third
                // mode, so an empty value keeps the current one.
                if (next) setPromptMode(next as ImagePromptMode);
              }}
              className="w-full"
            >
              <ToggleGroupItem value="assisted" className="flex-1">
                {t.imageGeneration.promptModeAssisted}
              </ToggleGroupItem>
              <ToggleGroupItem value="direct" className="flex-1">
                {t.imageGeneration.promptModeDirect}
              </ToggleGroupItem>
            </ToggleGroup>
            <p className="text-muted-foreground text-xs">
              {t.imageGeneration.promptModeHint(promptMode)}
            </p>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium" htmlFor="image-prompt">
              {promptMode === "direct"
                ? t.imageGeneration.prompt
                : t.imageGeneration.brief}
            </label>
            <Textarea
              id="image-prompt"
              rows={5}
              value={prompt}
              placeholder={
                promptMode === "direct"
                  ? t.imageGeneration.promptPlaceholder
                  : t.imageGeneration.briefPlaceholder
              }
              onChange={(event) => setPrompt(event.target.value)}
            />
            <p className="text-muted-foreground text-xs">
              {promptMode === "direct"
                ? t.imageGeneration.promptHint
                : t.imageGeneration.briefHint}
            </p>
          </div>

          {/*
            The negative prompt is offered, written, or explained away — never
            silently absent. A distilled checkpoint sampled at CFG 1 ignores it,
            and an ignored field that still accepts text is the failure this
            branch exists to prevent.
          */}
          {!negativesSupported ? (
            <p className="text-muted-foreground text-xs">
              {t.imageGeneration.negativePromptUnsupported(checkpoint.trim())}
            </p>
          ) : promptMode === "direct" ? (
            <div className="flex flex-col gap-1.5">
              <label
                className="text-sm font-medium"
                htmlFor="image-negative-prompt"
              >
                {t.imageGeneration.negativePrompt}
              </label>
              <Textarea
                id="image-negative-prompt"
                rows={2}
                value={negativePrompt}
                placeholder={t.imageGeneration.negativePromptPlaceholder}
                onChange={(event) => setNegativePrompt(event.target.value)}
              />
              <p className="text-muted-foreground text-xs">
                {t.imageGeneration.negativePromptHint}
              </p>
            </div>
          ) : (
            <p className="text-muted-foreground text-xs">
              {t.imageGeneration.negativePromptWritten}
            </p>
          )}

          <div className="flex flex-col gap-1.5">
            <span className="text-sm font-medium">
              {t.imageGeneration.resolution}
            </span>
            <div className="flex flex-col gap-2 sm:flex-row">
              <div className="flex flex-1 flex-col gap-1.5">
                <label
                  className="text-muted-foreground text-xs"
                  htmlFor="image-width"
                >
                  {t.imageGeneration.width}
                </label>
                <Input
                  id="image-width"
                  type="number"
                  inputMode="numeric"
                  min={MIN_DIMENSION}
                  max={maxDimension(kind)}
                  step={DIMENSION_STEP}
                  value={widthText}
                  onChange={(event) => setWidthText(event.target.value)}
                />
              </div>
              <div className="flex flex-1 flex-col gap-1.5">
                <label
                  className="text-muted-foreground text-xs"
                  htmlFor="image-height"
                >
                  {t.imageGeneration.height}
                </label>
                <Input
                  id="image-height"
                  type="number"
                  inputMode="numeric"
                  min={MIN_DIMENSION}
                  max={maxDimension(kind)}
                  step={DIMENSION_STEP}
                  value={heightText}
                  onChange={(event) => setHeightText(event.target.value)}
                />
              </div>
              <div className="flex flex-1 flex-col gap-1.5">
                <label
                  className="text-muted-foreground text-xs"
                  htmlFor="image-aspect"
                >
                  {t.imageGeneration.aspect}
                </label>
                <Select
                  value={aspect}
                  onValueChange={(next) => {
                    const nextAspect = next as ImageLaunchAspect;
                    setAspect(nextAspect);
                    seedSize(kind, nextAspect);
                  }}
                >
                  <SelectTrigger id="image-aspect" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {IMAGE_LAUNCH_ASPECTS.map((option) => (
                      <SelectItem key={option} value={option}>
                        {t.imageGeneration.aspectOption(option)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <p className="text-muted-foreground text-xs">
              {t.imageGeneration.resolutionHint(
                MIN_DIMENSION,
                maxDimension(kind),
                DIMENSION_STEP,
              )}
            </p>
            <p className="text-muted-foreground text-xs">
              {sizeIsValid
                ? t.imageGeneration.size(
                    effectiveSize.width,
                    effectiveSize.height,
                  )
                : t.imageGeneration.resolutionWarning(
                    MIN_DIMENSION,
                    maxDimension(kind),
                  )}
            </p>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium" htmlFor="image-checkpoint">
              {t.imageGeneration.checkpoint}
            </label>
            <Input
              id="image-checkpoint"
              value={checkpoint}
              placeholder={t.imageGeneration.checkpointPlaceholder}
              onChange={(event) => setCheckpoint(event.target.value)}
            />
            <p className="text-muted-foreground text-xs">
              {t.imageGeneration.checkpointHint}
            </p>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="flex items-center gap-2 text-sm font-medium">
              <input
                type="checkbox"
                checked={refine}
                onChange={(event) => setRefine(event.target.checked)}
              />
              {t.imageGeneration.refine}
            </label>
            <p className="text-muted-foreground text-xs">
              {t.imageGeneration.refineHint}
            </p>
          </div>

          {!hasPrompt && (
            <p className="text-muted-foreground text-xs">
              {t.imageGeneration.promptWarning}
            </p>
          )}

          <div className="flex items-center gap-2 pb-6">
            <Button onClick={handleStart} disabled={!isValid}>
              {t.imageGeneration.start}
            </Button>
            <Button variant="ghost" onClick={() => router.back()}>
              {t.imageGeneration.cancel}
            </Button>
          </div>

          {isValid && (
            <div className="text-muted-foreground rounded-md border p-3 text-xs whitespace-pre-wrap">
              {buildImageLaunchMessage({ ...launch, prompt: prompt.trim() })}
            </div>
          )}
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
