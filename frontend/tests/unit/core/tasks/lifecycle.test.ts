import { describe, expect, it } from "@rstest/core";

import { taskEventToSubtaskUpdate } from "@/core/tasks/lifecycle";

describe("taskEventToSubtaskUpdate", () => {
  it("maps a task-start event to the effective model for that task", () => {
    expect(
      taskEventToSubtaskUpdate({
        type: "task_started",
        task_id: "call-1",
        description: "Research auth",
        model_name: "claude-3-7-sonnet",
      }),
    ).toEqual({
      id: "call-1",
      modelName: "claude-3-7-sonnet",
    });
  });

  it("maps a running event to its cumulative token snapshot", () => {
    expect(
      taskEventToSubtaskUpdate({
        type: "task_running",
        task_id: "call-1",
        model_name: "claude-3-7-sonnet",
        usage: {
          input_tokens: 100,
          output_tokens: 20,
          total_tokens: 120,
        },
      }),
    ).toEqual({
      id: "call-1",
      modelName: "claude-3-7-sonnet",
      usage: {
        inputTokens: 100,
        outputTokens: 20,
        totalTokens: 120,
      },
    });
  });
  // Fork feature (roadmap item 5): the cost-aware routing policy attaches its
  // decision to task_started so the card can explain which model it picked and
  // why. It is additive metadata, so every malformed shape must degrade to
  // "no routing shown" rather than dropping the model name with it.
  describe("routing decision", () => {
    it("carries the rule and reason through", () => {
      expect(
        taskEventToSubtaskUpdate({
          type: "task_started",
          task_id: "call-1",
          model_name: "local-tools",
          routing: {
            model_name: "local-tools",
            rule: "tool-free-extraction",
            reason: "rule 'tool-free-extraction' matched",
          },
        }),
      ).toEqual({
        id: "call-1",
        modelName: "local-tools",
        routing: {
          rule: "tool-free-extraction",
          reason: "rule 'tool-free-extraction' matched",
        },
      });
    });

    it("omits routing when the backend did not send one", () => {
      expect(
        taskEventToSubtaskUpdate({
          type: "task_started",
          task_id: "call-1",
          model_name: "premium",
        }),
      ).toEqual({ id: "call-1", modelName: "premium" });
    });

    it("keeps a decision that has a reason but no rule", () => {
      expect(
        taskEventToSubtaskUpdate({
          type: "task_started",
          task_id: "call-1",
          model_name: "premium",
          routing: { reason: "no rule matched" },
        }),
      ).toEqual({
        id: "call-1",
        modelName: "premium",
        routing: { reason: "no rule matched" },
      });
    });

    it("drops a malformed decision without losing the model name", () => {
      for (const routing of [null, "routed", 42, {}, { rule: "x" }]) {
        expect(
          taskEventToSubtaskUpdate({
            type: "task_started",
            task_id: "call-1",
            model_name: "premium",
            routing,
          }),
        ).toEqual({ id: "call-1", modelName: "premium" });
      }
    });
  });
});
