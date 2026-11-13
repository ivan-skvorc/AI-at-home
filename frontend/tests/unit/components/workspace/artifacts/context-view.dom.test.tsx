import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

rs.mock("next/navigation", () => ({
  usePathname: () => "/workspace/chats/a",
}));
rs.mock("@/components/ui/sidebar", () => ({
  useSidebar: () => ({ setOpen: rs.fn() }),
}));
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: { id: "account-a" } }),
}));
rs.mock("@/env", () => ({
  env: { NEXT_PUBLIC_STATIC_WEBSITE_ONLY: "false" },
}));

import { ArtifactTrigger } from "@/components/workspace/artifacts/artifact-trigger";
import {
  ArtifactsProvider,
  useArtifacts,
} from "@/components/workspace/artifacts/context";
import { ArtifactDraftsProvider } from "@/core/artifacts/draft-context";
import { I18nProvider } from "@/core/i18n/context";

const STORAGE_KEY = `deerflow:artifacts:v1:${encodeURIComponent(
  "/workspace/chats/a",
)}`;
const FILE = "/mnt/user-data/workspace/notes.md";

function Probe() {
  const { view, open, selectedArtifact, select, setOpen, setView, showFiles } =
    useArtifacts();
  return (
    <>
      <output data-testid="state">
        {JSON.stringify({ view, open, selectedArtifact })}
      </output>
      <button onClick={() => select(FILE)}>Open file</button>
      <button onClick={showFiles}>Show files</button>
      <button onClick={() => setView("artifacts")}>Show artifacts</button>
      <button onClick={() => setOpen(false)}>Close panel</button>
      <button
        onClick={() => {
          // What a file card in the conversation does.
          select(FILE);
          setOpen(true);
        }}
      >
        Open from chat
      </button>
    </>
  );
}

function renderProvider() {
  return render(
    <I18nProvider initialLocale="en-US">
      <ArtifactDraftsProvider>
        <ArtifactsProvider>
          <Probe />
          <ArtifactTrigger />
        </ArtifactsProvider>
      </ArtifactDraftsProvider>
    </I18nProvider>,
  );
}

function state() {
  return JSON.parse(screen.getByTestId("state").textContent ?? "{}") as {
    view: string;
    open: boolean;
    selectedArtifact: string | null;
  };
}

afterEach(() => {
  cleanup();
  window.sessionStorage.clear();
});

describe("artifacts panel view", () => {
  it("reads panel state saved before the Files view as the Artifacts view", () => {
    window.sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ artifacts: [], selectedArtifact: FILE, open: true }),
    );
    renderProvider();

    expect(state()).toEqual({
      view: "artifacts",
      open: true,
      selectedArtifact: FILE,
    });
  });

  it("opens the explorer over an open file and restores the view", () => {
    const view = renderProvider();
    fireEvent.click(screen.getByText("Open file"));
    fireEvent.click(screen.getByText("Show files"));

    expect(state()).toEqual({
      view: "files",
      open: true,
      selectedArtifact: null,
    });
    view.unmount();
    renderProvider();
    expect(state().view).toBe("files");

    fireEvent.click(screen.getByText("Show artifacts"));
    expect(
      JSON.parse(window.sessionStorage.getItem(STORAGE_KEY) ?? "{}"),
    ).toMatchObject({ view: "artifacts" });
  });

  it("shows the artifact list from the header over a file the explorer opened", () => {
    window.sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        artifacts: ["/mnt/user-data/outputs/report.md"],
        selectedArtifact: FILE,
        open: false,
        view: "files",
      }),
    );
    renderProvider();

    fireEvent.click(screen.getByTestId("artifact-trigger"));

    expect(state()).toEqual({
      view: "artifacts",
      open: true,
      selectedArtifact: null,
    });
  });

  it("ends a Files session when the panel closes, so a file opened from the chat closes the panel again", () => {
    renderProvider();
    fireEvent.click(screen.getByRole("button", { name: "Show files" }));
    fireEvent.click(screen.getByRole("button", { name: "Close panel" }));
    fireEvent.click(screen.getByRole("button", { name: "Open from chat" }));

    // The detail's Close falls back to the explorer only in the Files view.
    expect(JSON.parse(screen.getByTestId("state").textContent ?? "{}")).toEqual(
      { view: "artifacts", open: true, selectedArtifact: FILE },
    );
  });
});
