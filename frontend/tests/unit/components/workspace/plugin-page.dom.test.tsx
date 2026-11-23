import { afterEach, describe, expect, rs, test } from "@rstest/core";
import { cleanup, render, screen, waitFor } from "@testing-library/react";

import { PluginPage } from "@/components/workspace/plugin-page";
import type {
  PluginSurface,
  SurfaceContext,
} from "@/core/extensions/contracts";
import type { LoadedContribution } from "@/core/extensions/registry";

const state = rs.hoisted(() => ({
  entries: [] as unknown[],
  models: [] as { name: string; display_name: string }[],
  preferred: undefined as string | undefined,
}));

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn() }),
}));
rs.mock("@/components/workspace/workspace-sidebar-trigger", () => ({
  WorkspaceSidebarTrigger: () => null,
}));
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: { id: "alice" } }),
}));
rs.mock("@/core/extensions/hooks", () => ({
  useFrontendExtensions: () => ({ data: state.entries, isPending: false }),
  useFrontendServices: () => ({}),
}));
rs.mock("@/core/models/hooks", () => ({
  useModels: () => ({ models: state.models }),
}));
rs.mock("@/core/settings/hooks", () => ({
  useLocalSettings: () => [{ context: { model_name: state.preferred } }],
}));
rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    locale: "en-US",
    t: {
      breadcrumb: { workspace: "Workspace" },
      extensions: {
        pageUnavailable: "Unavailable",
        pageLoading: "Loading",
        viewFailed: "Failed",
      },
    },
  }),
}));

afterEach(() => {
  cleanup();
  state.entries = [];
  state.models = [];
  state.preferred = undefined;
});

function install(surface: Omit<PluginSurface, "mount" | "slot" | "id">) {
  const contexts: SurfaceContext[] = [];
  const entry: LoadedContribution = {
    namespace: "cad-design",
    module: "cad-design",
    entry: null,
    title: "CAD design",
    description: "",
    settings: { enabled: true },
    viewer_id: "viewer",
    extension: {
      apiVersion: 1,
      module: "cad-design",
      surfaces: [
        {
          id: "designs",
          slot: "page",
          ...surface,
          mount(root, context) {
            contexts.push(context);
            root.textContent = "PLUGIN";
            return { dispose: () => undefined };
          },
        },
      ],
    },
  };
  state.entries = [entry];
  return contexts;
}

describe("PluginPage layouts", () => {
  test("the default column layout keeps the centred column and title", async () => {
    const contexts = install({ title: "Designs" });
    const { container } = render(
      <PluginPage namespace="cad-design" surfaceId="designs" />,
    );
    await waitFor(() => expect(contexts).toHaveLength(1));
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
      "Designs",
    );
    expect(container.querySelector(".max-w-6xl")).not.toBeNull();
  });

  test("a full layout fills the space under the header without a title", async () => {
    const contexts = install({ title: "Designs", layout: "full" });
    const { container } = render(
      <PluginPage namespace="cad-design" surfaceId="designs" />,
    );
    await waitFor(() => expect(contexts).toHaveLength(1));
    expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
    expect(container.querySelector(".max-w-6xl")).toBeNull();
    expect(container.querySelector("main")?.className).toContain(
      "overflow-hidden",
    );
    const section = screen.getByRole("region", { name: "Designs" });
    expect(section.className).toContain("flex-1");
  });
});

test("the surface reads the host's current model list and preferred model", async () => {
  const contexts = install({ title: "Designs" });
  state.models = [
    { name: "fast", display_name: "Fast" },
    { name: "smart", display_name: "Smart" },
  ];
  state.preferred = "smart";
  render(<PluginPage namespace="cad-design" surfaceId="designs" />);
  await waitFor(() => expect(contexts).toHaveLength(1));
  const context = contexts[0]!;
  expect(context.models?.list).toEqual([
    { name: "fast", display_name: "Fast" },
    { name: "smart", display_name: "Smart" },
  ]);
  expect(context.models?.defaultName).toBe("smart");
  expect(typeof context.joinRunStream).toBe("function");
});
