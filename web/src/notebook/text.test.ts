// The notebook's text rules. Made-up text and tickers built from letters.
import { describe, expect, it } from "vitest";
import {
  cashtags, continuation, detectTrigger, fenceStates, hashtags, isBareMarker, parseInline, parseLine, shorthand,
  snippet, stocksIn, toggleTask, withoutTag, withTag,
} from "./text";

const T = ["W", "Z", "Q", "W"].join("");

describe("lines", () => {
  it("reads headings, lists, checklists, quotes, rules and images", () => {
    expect(parseLine("# Title")).toMatchObject({ kind: "h1", body: "Title" });
    expect(parseLine("### Small")).toMatchObject({ kind: "h3" });
    expect(parseLine("#tag is not a heading").kind).toBe("p");
    expect(parseLine("- item")).toMatchObject({ kind: "bullet", body: "item" });
    expect(parseLine("  - nested")).toMatchObject({ kind: "bullet", indent: 2 });
    expect(parseLine("3. third")).toMatchObject({ kind: "number", marker: "3. " });
    expect(parseLine("- [ ] todo")).toMatchObject({ kind: "task", checked: false, body: "todo" });
    expect(parseLine("- [x] done")).toMatchObject({ kind: "task", checked: true });
    expect(parseLine("> said")).toMatchObject({ kind: "quote", body: "said" });
    expect(parseLine("---").kind).toBe("rule");
    expect(parseLine("![shot](/api/attachments/a.png)").kind).toBe("image");
    expect(parseLine("").kind).toBe("blank");
  });

  it("draws lines inside a fence as code", () => {
    const lines = ["before", "```", "# not a heading", "```", "after"];
    const inside = fenceStates(lines);
    expect(inside).toEqual([false, true, true, true, false]);
    expect(parseLine(lines[2], inside[2]).kind).toBe("code");
    expect(parseLine(lines[1], inside[1]).kind).toBe("fence");
  });

  it("continues a list on Enter and ends it on an empty item", () => {
    expect(continuation("- one")).toBe("- ");
    expect(continuation("  * nested")).toBe("  * ");
    expect(continuation("4. four")).toBe("5. ");
    expect(continuation("- [x] done")).toBe("- [ ] ");
    expect(continuation("> quoted")).toBe("> ");
    expect(continuation("- ")).toBe("");
    expect(continuation("- [ ] ")).toBe("");
    expect(continuation("plain")).toBeNull();
    expect(isBareMarker("- [ ] ")).toBe(true);
    expect(isBareMarker("- a")).toBe(false);
  });

  it("turns `[ ] ` into a checklist item and toggles it", () => {
    expect(shorthand("[ ] buy")).toBe("- [ ] buy");
    expect(shorthand("[x] bought")).toBe("- [x] bought");
    expect(shorthand("[link](x)")).toBe("[link](x)");
    expect(toggleTask("- [ ] a")).toBe("- [x] a");
    expect(toggleTask("  - [x] a")).toBe("  - [ ] a");
  });
});

describe("tags and stocks", () => {
  it("finds #tags like the server does: lowercase, not in code, not headings", () => {
    expect(hashtags("# Heading\nGood #Setup and #late-entry, not #1 or a#b or `#code`\n#setup")).toEqual(["setup", "late-entry"]);
    expect(hashtags("```\n#fenced\n```\n#open_tag")).toEqual(["open_tag"]);
  });

  it("finds $TICKER and [[TICKER]] but not prices", () => {
    expect(cashtags(`Held $${T} and $${T.toLowerCase()}, paid $100 and US$x`)).toEqual([T]);
    expect(stocksIn(`See [[${T}]] and [[Some page]] and $${T}`)).toEqual([T]);
  });

  it("adds and removes a #tag in the text", () => {
    expect(withTag("note", "Ep")).toBe("note\n#ep");
    expect(withTag("note #ep", "ep")).toBe("note #ep");
    expect(withoutTag("note #ep and more\n#ep", "ep")).toBe("note and more");
    expect(withoutTag("keep #epic", "ep")).toBe("keep #epic");
  });

  it("suggests what is being typed", () => {
    expect(detectTrigger("/he", 3)).toEqual({ kind: "slash", query: "he", start: 0 });
    expect(detectTrigger("text /", 6)).toMatchObject({ kind: "slash" });
    expect(detectTrigger("http://x", 8)).toBeNull();
    expect(detectTrigger("a #ep", 5)).toEqual({ kind: "tag", query: "ep", start: 2 });
    expect(detectTrigger("a $WZ", 5)).toEqual({ kind: "ticker", query: "WZ", start: 2 });
    expect(detectTrigger("see [[Pl", 8)).toEqual({ kind: "wiki", query: "Pl", start: 4 });
    expect(detectTrigger("# Title", 7)).toBeNull();
  });
});

describe("inline", () => {
  it("parses bold, italic, code, strike, tags, tickers, wiki links and links", () => {
    const parts = parseInline(`**b** *i* \`c\` ~~s~~ #tag $${T} [[Page]] [x](https://a.b)`);
    expect(parts.filter((p) => p.t !== "text").map((p) => p.t)).toEqual(["bold", "italic", "code", "strike", "tag", "ticker", "wiki", "link"]);
    expect(parts.find((p) => p.t === "ticker")).toMatchObject({ ticker: T });
  });

  it("leaves unsafe links and half-written marks as text", () => {
    expect(parseInline("[x](javascript:alert(1))").map((p) => p.t)).not.toContain("link");
    expect(parseInline("**open").every((p) => p.t === "text")).toBe(true);
    expect(parseInline("a#b and 5*3*2 x").map((p) => p.t)).not.toContain("tag");
  });

  it("keeps the words of a snippet and drops the marks", () => {
    expect(snippet("\n## **Plan** for [the week](x) #ep")).toBe("Plan for the week #ep");
    expect(snippet("![a](b)")).toBe("[image]");
    expect(snippet("x".repeat(200), 10)).toHaveLength(10);
  });
});
