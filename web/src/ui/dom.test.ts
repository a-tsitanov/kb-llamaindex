import { describe, expect, it } from "vitest";
import { isNearBottom } from "./dom";

describe("isNearBottom", () => {
  it("is true exactly at the bottom and within the slack", () => {
    expect(isNearBottom({ scrollTop: 100, scrollHeight: 100, clientHeight: 100 })).toBe(true);
    expect(isNearBottom({ scrollTop: 80, scrollHeight: 120, clientHeight: 20 }, 32)).toBe(true);
  });

  it("is false when scrolled well above the bottom", () => {
    expect(isNearBottom({ scrollTop: 0, scrollHeight: 500, clientHeight: 100 })).toBe(false);
    expect(isNearBottom({ scrollTop: 80, scrollHeight: 120, clientHeight: 20 }, 10)).toBe(false);
  });
});
