import { describe, expect, it } from "@rstest/core";

import { isRecord } from "@/lib/utils";

describe("isRecord", () => {
  it("accepts plain objects, including empty and null-prototype ones", () => {
    expect(isRecord({ detail: "x" })).toBe(true);
    expect(isRecord({})).toBe(true);
    expect(isRecord(Object.create(null))).toBe(true);
  });

  it("rejects arrays, null and primitives", () => {
    expect(isRecord([])).toBe(false);
    expect(isRecord(null)).toBe(false);
    expect(isRecord(undefined)).toBe(false);
    expect(isRecord("detail")).toBe(false);
    expect(isRecord(0)).toBe(false);
  });
});
