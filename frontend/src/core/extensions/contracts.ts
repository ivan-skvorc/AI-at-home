import type { Message } from "@langchain/langgraph-sdk";

import type { Translations } from "@/core/i18n";
import type { AgentThread } from "@/core/threads/types";

import type { ExtensionDocumentation } from "./documentation";

export type ExtensionSettings = Readonly<
  Record<string, boolean | number | string>
>;
export type SurfaceSlot = "page";
export type ExtensionRequestOptions = Pick<
  RequestInit,
  "method" | "headers" | "body" | "signal"
>;
/** One server-sent event of a joined run; `data` is parsed JSON, or the raw text. */
export type RunStreamEvent = { event: string; data: unknown };
/** Names of the models this user can pick; `defaultName` is the user's current choice. */
export type SurfaceModels = {
  list: Array<{ name: string; display_name?: string }>;
  defaultName?: string;
};
/** One entry of a listed thread outputs folder; links are reported, never followed. */
export type SurfaceThreadFileEntry = {
  name: string;
  /** Virtual path: the listed folder, `/`, then `name`. */
  path: string;
  kind: "directory" | "file" | "symlink" | "other";
  /** Bytes for regular files, otherwise null. */
  size: number | null;
  modified_at: string | null;
};
/**
 * Read-only access to a thread's `/mnt/user-data/outputs/` tree through the
 * host's authenticated, owner-checked file routes; usable while a run is active.
 */
export type SurfaceThreadFiles = {
  /** One folder, directories first. Rejects with `status` 404 when it does not exist. */
  list: (
    threadId: string,
    virtualPath: string,
    options?: { signal?: AbortSignal },
  ) => Promise<SurfaceThreadFileEntry[]>;
  /** The file's bytes, at most `maxBytes` (default and ceiling 25 MiB). */
  read: (
    threadId: string,
    virtualPath: string,
    options?: { signal?: AbortSignal; maxBytes?: number },
  ) => Promise<ArrayBuffer>;
  /** The authenticated artifact URL, for a link or an `<img>`. */
  url: (
    threadId: string,
    virtualPath: string,
    options?: { download?: boolean },
  ) => string;
};
/** The modes the composer's dropdown offers; Democracy is launched from its own dialog. */
export type SurfaceComposerMode =
  | "flash"
  | "thinking"
  | "pro"
  | "ultra"
  | "ultracode"
  | "double_ultracode";
/**
 * What the main chat sends with a run for the controls' selection: pass it
 * as the run's context. The Gateway still enforces model access and clamps
 * the limits; `plugin_options` carries only other plugins' entries.
 */
export type SurfaceRunContext = {
  model_name?: string;
  mode: SurfaceComposerMode;
  thinking_enabled: boolean;
  is_plan_mode: boolean;
  subagent_enabled: boolean;
  reasoning_effort?: string;
  subagent_model_name?: string;
  max_total_subagents?: number;
  max_concurrent_subagents?: number;
  plugin_options?: Record<string, Record<string, unknown>>;
};
export type SurfaceComposerControlsOptions = {
  /** Keeps a separate selection per control set on one page; 1-64 of `A-Za-z0-9._-`. */
  storageKey?: string;
  /** Called with the new run context each time the selection changes. */
  onChange?: (context: SurfaceRunContext) => void;
};
export type SurfaceComposerControlsHandle = {
  /** A fresh copy of the run context for the current selection. */
  runContext: () => SurfaceRunContext;
  /** Unmounts the controls; the page's own cleanup also disposes them. */
  dispose: () => void;
};
/**
 * The main chat's model picker, mode menu and reasoning-effort menu, rendered
 * by the host inside a plugin element (in a shadow root of their own). The
 * selection persists per page in this browser.
 */
export type SurfaceComposerControls = {
  mount: (
    element: HTMLElement,
    options?: SurfaceComposerControlsOptions,
  ) => SurfaceComposerControlsHandle;
};
export type SurfaceContext = {
  namespace: string;
  locale: string;
  settings: ExtensionSettings;
  threadId?: string;
  signal: AbortSignal;
  callBackend: FrontendServices["callBackend"];
  /** Authenticated HTTP to contributed /api/extensions/ routes. Routes own authorization. */
  requestBackend?: (
    path: string,
    options?: ExtensionRequestOptions,
  ) => Promise<Response>;
  /** Host resolves current thread ownership before navigating; unavailable on older hosts. */
  openConversation?: (threadId: string) => Promise<void>;
  /**
   * Observe a run's SSE stream through the authenticated host join route. The
   * Gateway checks thread ownership; the page signal ends the stream on unmount.
   */
  joinRunStream?: (
    threadId: string,
    runId: string,
    options?: { signal?: AbortSignal },
  ) => AsyncIterable<RunStreamEvent>;
  /** A thread's output files; only paths under /mnt/user-data/outputs/. Older hosts omit it. */
  threadFiles?: SurfaceThreadFiles;
  /** The host's current model list, read live; empty while it is still loading. */
  models?: SurfaceModels;
  /** The chat composer's run controls for a plugin element. Older hosts omit it. */
  composerControls?: SurfaceComposerControls;
};
export type PluginSurface = {
  id: string;
  slot: SurfaceSlot;
  title: string;
  /** Optional sidebar entry for a page surface; the host owns its URL. */
  navigation?: { label: string; labelZh?: string; icon?: string };
  /** "full" mounts the page edge to edge under the header, without a title or page scroll. */
  layout?: "column" | "full";
  /** Mount synchronously; async work must observe context.signal. */
  mount: (
    root: HTMLElement,
    context: SurfaceContext,
  ) => { dispose: () => void };
};
export type FrontendContribution = {
  viewer_id?: string | null;
  namespace: string;
  module: string | null;
  entry: string | null;
  /** Known transports: inline-v1 and assets-v1; unknown values fail per plugin. */
  transport?: string | null;
  title: string;
  description: string;
  settings: ExtensionSettings;
  backend_actions?: string[];
  model_tools?: string[];
  documentation?: ExtensionDocumentation;
  runtime_only?: boolean;
};
export type ConversationActionContext = {
  thread: AgentThread;
  messages?: Message[];
};
export type FrontendServices = {
  callBackend: (
    action: string,
    payload: Record<string, unknown>,
  ) => Promise<unknown>;
  conversationText: (context: ConversationActionContext) => Promise<string>;
  latestVisibleAnswer?: (
    context: ConversationActionContext,
  ) => Promise<{ id: string; text: string } | null>;
  showMessage: (message: string) => void;
};
export type ConversationAction = {
  id: string;
  label: string;
  icon: string;
  available: (settings: ExtensionSettings) => boolean;
  execute: (
    context: ConversationActionContext,
    services: FrontendServices,
  ) => Promise<void>;
};
export type ConversationActionGroup = {
  label: string;
  icon: string;
  actions: ConversationAction[];
};

export type ExtensionMention = {
  namespace: string;
  provider: string;
  id: string;
  label: string;
};
export type MentionContext = Pick<
  SurfaceContext,
  "namespace" | "locale" | "settings" | "threadId" | "signal" | "callBackend"
>;
export type MentionProvider = {
  id: string;
  label: string;
  search: (
    query: string,
    context: MentionContext,
  ) => Promise<readonly { id: string; label: string; description?: string }[]>;
};

/** Optional file renderer. The host owns the URL, authorization and byte limit. */
export type ArtifactPreviewContext = {
  filename: string;
  locale: string;
  signal: AbortSignal;
  readFile: () => Promise<ArrayBuffer>;
  onError: () => void;
  /** Available after readFile; scoped to viewer, file bytes and renderer. In-memory only. */
  getReadingState?: () => unknown;
  saveReadingState?: (state: unknown) => void;
};
export type ArtifactPreviewRenderer = {
  id: string;
  /** Lowercase extensions without a dot; exact matches only. */
  extensions: string[];
  mount: (
    root: HTMLElement,
    context: ArtifactPreviewContext,
  ) => { dispose: () => void };
};

/** Browser package API v1. Modules are installed by trusted deployment operators. */
export interface FrontendExtension {
  apiVersion: 1;
  module: string;
  icon?: string;
  surfaces?: PluginSurface[];
  mentionProviders?: MentionProvider[];
  artifactPreviews?: ArtifactPreviewRenderer[];
  conversationActions?: (
    t: Translations,
    locale?: string,
  ) => ConversationActionGroup;
}
