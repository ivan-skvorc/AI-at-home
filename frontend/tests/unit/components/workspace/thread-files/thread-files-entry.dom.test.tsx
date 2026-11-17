import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, render, screen, waitFor } from "@testing-library/react";

const nav = rs.hoisted(() => ({
  pathname: "/workspace/chats/t1",
  search: "panel=files&mock=true",
  replace: rs.fn(),
}));

rs.mock("next/navigation", () => ({
  usePathname: () => nav.pathname,
  useSearchParams: () => new URLSearchParams(nav.search),
  useRouter: () => ({ replace: nav.replace }),
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

import {
  ArtifactsProvider,
  useArtifacts,
} from "@/components/workspace/artifacts/context";
import { ThreadFilesDeepLink } from "@/components/workspace/thread-files/thread-files-deep-link";
import { ThreadFilesTrigger } from "@/components/workspace/thread-files/thread-files-trigger";
import { ArtifactDraftsProvider } from "@/core/artifacts/draft-context";
import { I18nProvider } from "@/core/i18n/context";

const SCOPE = "slot:t1";

function PanelState() {
  const { view, open } = useArtifacts();
  return <output data-testid="panel">{JSON.stringify({ view, open })}</output>;
}

function renderChat(children: React.ReactNode) {
  return render(
    <I18nProvider initialLocale="en-US">
      <ArtifactDraftsProvider>
        <ArtifactsProvider storageScope={SCOPE}>
          <PanelState />
          {children}
        </ArtifactsProvider>
      </ArtifactDraftsProvider>
    </I18nProvider>,
  );
}

function panel() {
  return JSON.parse(screen.getByTestId("panel").textContent ?? "{}") as {
    view: string;
    open: boolean;
  };
}

beforeEach(() => {
  nav.pathname = "/workspace/chats/t1";
  nav.search = "panel=files&mock=true";
  nav.replace.mockReset();
  // The panel was closed when this chat was last seen: the provider restores
  // that in the same commit that mounts the deep link.
  window.sessionStorage.setItem(
    `deerflow:artifacts:v1:${encodeURIComponent(SCOPE)}`,
    JSON.stringify({
      artifacts: [],
      selectedArtifact: null,
      open: false,
      view: "artifacts",
    }),
  );
});

afterEach(() => {
  cleanup();
  window.sessionStorage.clear();
});

describe("Files header button", () => {
  it("shows a visible label and keeps the accessible name", () => {
    renderChat(<ThreadFilesTrigger />);
    const button = screen.getByRole("button", { name: "Show files" });
    expect(button.textContent).toBe("Files");
    expect(screen.getByTestId("thread-files-trigger-label").textContent).toBe(
      "Files",
    );
  });

  it("shows the word only from a header width where the whole row fits", () => {
    // The controls row cannot shrink: a label shown any earlier would push
    // the last header controls (Artifacts first) off the edge.
    const view = renderChat(<ThreadFilesTrigger />);
    expect(
      screen.getByTestId("thread-files-trigger-label").className.split(" "),
    ).toEqual(["hidden", "@[48rem]/chat-header:inline"]);
    view.unmount();
    // An agent's header also carries its badge and New chat.
    renderChat(<ThreadFilesTrigger header="agent" />);
    expect(
      screen.getByTestId("thread-files-trigger-label").className.split(" "),
    ).toEqual(["hidden", "@[60rem]/chat-header:inline"]);
  });
});

describe("?panel=files", () => {
  it("opens the panel on the Files tab and strips only that parameter", async () => {
    renderChat(<ThreadFilesDeepLink threadId="t1" enabled />);
    await waitFor(() => expect(panel()).toEqual({ view: "files", open: true }));
    expect(nav.replace).toHaveBeenCalledTimes(1);
    expect(nav.replace).toHaveBeenCalledWith("/workspace/chats/t1?mock=true", {
      scroll: false,
    });
  });

  it("leaves a chat alone when the URL names another one", async () => {
    nav.pathname = "/workspace/chats/t2";
    renderChat(<ThreadFilesDeepLink threadId="t1" enabled />);
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(panel()).toEqual({ view: "artifacts", open: false });
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it("does nothing for a chat without a Files view or in the background", async () => {
    renderChat(<ThreadFilesDeepLink threadId="t1" enabled={false} />);
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(panel()).toEqual({ view: "artifacts", open: false });
    expect(nav.replace).not.toHaveBeenCalled();
  });
});
