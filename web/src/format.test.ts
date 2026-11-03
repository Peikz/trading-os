import { compact, deltaColour, formatValue } from "./format";

describe("formatValue", () => {
  it("formats each field kind", () => {
    expect(formatValue(3.456, "pct")).toBe("+3.5%");
    expect(formatValue(-1.2, "pct")).toBe("-1.2%");
    expect(formatValue(2_500_000_000, "money")).toBe("$2.5B");
    expect(formatValue(12.5, "money")).toBe("$12.50");
    expect(formatValue(1_200_000, "num")).toBe("1.2M");
    expect(formatValue(true, "bool")).toBe("yes");
    expect(formatValue(null, "num")).toBe("–");
    expect(formatValue("Software", "text")).toBe("Software");
  });

  it("compacts large numbers", () => {
    expect(compact(950)).toBe("950");
    expect(compact(12_300)).toBe("12.3k");
  });
});

describe("deltaColour", () => {
  it("is green up and red down, the other way round for VIX", () => {
    expect(deltaColour("SPY", "+0.5%")).toBe("var(--up)");
    expect(deltaColour("SPY", "-0.5%")).toBe("var(--down)");
    expect(deltaColour("VIX", "+3.0%")).toBe("var(--down)");
    expect(deltaColour("IBD market", "2 of 6 sell days")).toBeUndefined();
  });
});
