import { dayOf, toSegment } from "./DrawChart";

describe("DrawChart helpers", () => {
  it("turns chart times into days and measures the distance to a line", () => {
    expect(dayOf("2026-06-01")).toBe("2026-06-01");
    expect(dayOf({ year: 2026, month: 6, day: 1 })).toBe("2026-06-01");
    expect(dayOf(undefined)).toBeNull();
    expect(toSegment([5, 5], [0, 0], [10, 0])).toBe(5);
    expect(toSegment([20, 0], [0, 0], [10, 0])).toBe(10); // past the end: to the end point
  });
});
