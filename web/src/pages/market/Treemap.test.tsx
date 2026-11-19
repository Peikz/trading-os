import { render, screen } from "@testing-library/react";
import { heat, layout, Treemap } from "./Treemap";

describe("Treemap", () => {
  it("fills the box with equal tiles that do not overlap", () => {
    for (const n of [1, 3, 7, 11, 30]) {
      const rects = layout(n);
      expect(rects).toHaveLength(n);
      const area = rects.reduce((sum, r) => sum + r.w * r.h, 0);
      expect(area).toBeCloseTo(10000, 3);
      const first = rects[0].w * rects[0].h;
      for (const r of rects) expect(r.w * r.h).toBeCloseTo(first, 3);
    }
  });

  it("colours red below zero, grey at zero and green above", () => {
    const rgb = (s: string) => s.match(/\d+/g)!.map(Number);
    const [r0, g0] = rgb(heat(0, 5));
    const [rUp, gUp] = rgb(heat(5, 5));
    const [rDn, gDn] = rgb(heat(-5, 5));
    expect(gUp).toBeGreaterThan(g0);
    expect(rUp).toBeLessThan(r0 + 1);
    expect(rDn).toBeGreaterThan(r0);
    expect(gUp).toBeGreaterThan(gDn);
  });

  it("opens a sector in the Screener and leaves themes unclickable", () => {
    render(
      <Treemap
        period="1M"
        scale={10}
        items={[
          { key: "a", name: "Energy", ticker: "AAA", group: "Sector", value: -3.3 },
          { key: "b", name: "Solar", ticker: "BBB", group: "Theme", value: 1 },
        ]}
      />,
    );
    const energy = screen.getByRole("listitem", { name: /Energy -3.3%/ });
    expect(energy).toBeEnabled();
    energy.click();
    expect(window.location.hash).toBe("#/screener/screen?sector=Energy+Minerals");
    expect(screen.getByRole("listitem", { name: /Solar \+1.0%/ })).toBeDisabled();
  });
});
