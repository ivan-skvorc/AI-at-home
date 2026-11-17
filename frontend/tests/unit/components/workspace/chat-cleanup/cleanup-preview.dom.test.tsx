import { afterEach, describe, expect, it } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";

import {
  CleanupPreview,
  type PlanUpdate,
} from "@/components/workspace/chat-cleanup/cleanup-preview";
import { I18nProvider } from "@/core/i18n/context";
import type { OrganizePlan } from "@/core/threads/chat-organize";

/**
 * The preview's "No changes" empty state means the model proposed nothing. An
 * edit that takes back the last pending change must not swap the rows (and the
 * field being typed in) for it: the edit could then only be undone by going
 * Back and paying for the whole pass again.
 */

const RENAME_ONLY: OrganizePlan = {
  items: [
    {
      threadId: "t1",
      currentTitle: "Tax stuff",
      currentFolderId: null,
      suggestedTitle: "Tax filing",
      title: "Tax filing",
      target: { kind: "keep" },
      include: true,
    },
  ],
  proposedFolders: [],
};

function Preview({ initial }: { initial: OrganizePlan }) {
  const [plan, setPlan] = useState(initial);
  const onUpdate: PlanUpdate = (update) =>
    setPlan((current) => update(current));
  return (
    <I18nProvider initialLocale="en-US">
      <CleanupPreview
        plan={plan}
        folders={[]}
        threadTitles={new Map()}
        failures={[]}
        results={null}
        disabled={false}
        onUpdate={onUpdate}
      />
    </I18nProvider>
  );
}

afterEach(cleanup);

describe("clean-up preview", () => {
  it("keeps the rows while an edit leaves nothing to apply", () => {
    render(<Preview initial={RENAME_ONLY} />);
    const input = screen.getByTestId<HTMLInputElement>(
      "chat-cleanup-row-title",
    );

    // Select all and delete, to type an own title: nothing is pending now.
    fireEvent.change(input, { target: { value: "" } });
    expect(screen.getByTestId("chat-cleanup-row-title")).toBe(input);
    expect(screen.queryByText("No changes to apply.")).toBeNull();
    expect(screen.getByText("No change")).toBeTruthy();

    fireEvent.change(input, { target: { value: "Taxes 2026" } });
    expect(input.value).toBe("Taxes 2026");
    expect(screen.queryByText("No change")).toBeNull();
  });

  it("shows the empty state when the pass proposed nothing", () => {
    render(
      <Preview
        initial={{
          ...RENAME_ONLY,
          items: [
            { ...RENAME_ONLY.items[0]!, suggestedTitle: null, title: "" },
          ],
        }}
      />,
    );
    expect(screen.getByText("No changes to apply.")).toBeTruthy();
    expect(screen.queryByTestId("chat-cleanup-rows")).toBeNull();
  });
});
