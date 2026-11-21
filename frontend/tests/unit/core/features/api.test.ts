import { describe, expect, it } from "@rstest/core";

import {
  type FeaturesResponse,
  selectConversationReferencesCapability,
  selectScheduledTasksFeature,
  selectSubagentBatchesCapability,
} from "@/core/features/api";

// The selectors read the parsed `/api/features` body; malformed fields arrive
// as whatever JSON the backend sent, hence the cast.
const features = (body: unknown) => body as FeaturesResponse;

describe("subagent batch feature capability", () => {
  it("keeps repository and worker availability independent", () => {
    expect(
      selectSubagentBatchesCapability(
        features({
          agents_api: { enabled: true },
          subagent_batches: {
            enabled: false,
            repository_available: true,
            worker_running: false,
            max_running: 3,
          },
        }),
      ),
    ).toEqual({
      repositoryAvailable: true,
      workerRunning: false,
      maxRunning: 3,
    });
  });

  it("falls back to the legacy enabled flag during rolling upgrades", () => {
    expect(
      selectSubagentBatchesCapability(
        features({
          agents_api: { enabled: true },
          subagent_batches: { enabled: true, max_running: 4 },
        }),
      ),
    ).toEqual({
      repositoryAvailable: true,
      workerRunning: true,
      maxRunning: 4,
    });
  });
});

describe("conversation references feature capability", () => {
  it("reports the flag and the per-run cap", () => {
    expect(
      selectConversationReferencesCapability(
        features({
          agents_api: { enabled: true },
          conversation_references: { enabled: true, max_references: 3 },
        }),
      ),
    ).toEqual({
      enabled: true,
      maxReferences: 3,
    });
  });

  it("treats a backend without the field as disabled", () => {
    expect(
      selectConversationReferencesCapability(
        features({ agents_api: { enabled: true } }),
      ),
    ).toEqual({
      enabled: false,
      maxReferences: 0,
    });
  });

  it("never reports a cap below zero or a non-numeric one", () => {
    expect(
      selectConversationReferencesCapability(
        features({
          agents_api: { enabled: true },
          conversation_references: { enabled: true, max_references: "3" },
        }),
      ),
    ).toEqual({
      enabled: true,
      maxReferences: 0,
    });
  });
});

describe("scheduled tasks feature", () => {
  it("reads the scheduled_tasks block", () => {
    expect(
      selectScheduledTasksFeature(
        features({
          agents_api: { enabled: true },
          scheduled_tasks: {
            available: true,
            running: false,
            tool_enabled: false,
            group_notifications: true,
            min_interval_seconds: 30,
          },
        }),
      ),
    ).toEqual({
      available: true,
      running: false,
      toolEnabled: false,
      groupNotifications: true,
      minIntervalSeconds: 30,
    });
  });

  it("assumes a working page without the chat tool when the block is missing", () => {
    expect(
      selectScheduledTasksFeature(features({ agents_api: { enabled: true } })),
    ).toEqual({
      available: true,
      running: true,
      toolEnabled: false,
      groupNotifications: false,
      minIntervalSeconds: 60,
    });
  });

  it("fills missing or malformed fields with the defaults", () => {
    expect(
      selectScheduledTasksFeature(
        features({
          agents_api: { enabled: true },
          scheduled_tasks: {
            available: false,
            min_interval_seconds: "10",
            group_notifications: "true",
          },
        }),
      ),
    ).toEqual({
      available: false,
      running: true,
      toolEnabled: false,
      groupNotifications: false,
      minIntervalSeconds: 60,
    });
  });
});
