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
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";
import {
  buildImageLaunchMessage,
  IMAGE_LAUNCH_ASPECTS,
  type ImageLaunch,
  type ImageLaunchAspect,
  type ImageLaunchKind,
  isValidImageLaunch,
  launchDimensions,
  stashImageLaunch,
} from "@/core/threads/image-generation";

/**
 * Setup for a generation run: what to make, image or clip, what shape, and
 * whether to iterate on it.
 *
 * A **full page**, not a modal, for the same reason Democracy is one: this is
 * the start of a conversation rather than a preference being adjusted. It seeds
 * the composer instead of sending, so the request is visible and editable
 * before anything spends GPU minutes on it — which matters more here than for a
 * chat message, because a video is minutes per attempt.
 */
export function ImageGenerationSetup() {
  const { t } = useI18n();
  const router = useRouter();

  const [kind, setKind] = useState<ImageLaunchKind>("image");
  const [prompt, setPrompt] = useState("");
  const [aspect, setAspect] = useState<ImageLaunchAspect>("landscape");
  const [checkpoint, setCheckpoint] = useState("");
  const [refine, setRefine] = useState(false);

  const launch: ImageLaunch = {
    kind,
    prompt,
    aspect,
    checkpoint: checkpoint.trim() || undefined,
    refine,
  };
  const isValid = isValidImageLaunch(launch);
  const { width, height } = launchDimensions(kind, aspect);

  const handleStart = useCallback(() => {
    if (!isValid) return;
    stashImageLaunch({ ...launch, prompt: prompt.trim() });
    router.push("/workspace/chats/new");
    // `launch` is derived per render; the fields it is built from are the deps.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aspect, checkpoint, isValid, kind, prompt, refine, router]);

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
              onValueChange={(next) => setKind(next as ImageLaunchKind)}
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
            <label className="text-sm font-medium" htmlFor="image-prompt">
              {t.imageGeneration.prompt}
            </label>
            <Textarea
              id="image-prompt"
              rows={5}
              value={prompt}
              placeholder={t.imageGeneration.promptPlaceholder}
              onChange={(event) => setPrompt(event.target.value)}
            />
            <p className="text-muted-foreground text-xs">
              {t.imageGeneration.promptHint}
            </p>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium" htmlFor="image-aspect">
              {t.imageGeneration.aspect}
            </label>
            <Select
              value={aspect}
              onValueChange={(next) => setAspect(next as ImageLaunchAspect)}
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
            <p className="text-muted-foreground text-xs">
              {t.imageGeneration.size(width, height)}
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

          {!isValid && (
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
