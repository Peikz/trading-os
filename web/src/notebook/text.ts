// The notebook's text rules, pure and tested: what a line of markdown is, the inline pieces in it
// (bold, #tag, $TICKER, [[link]]), the tags and stocks written in a text, and what Enter does in a
// list. The stored text is plain markdown; nothing here changes it except the small helpers the
// editor calls on purpose (continuing a list, toggling a checkbox).

export type LineKind =
  | "h1" | "h2" | "h3" | "bullet" | "number" | "task" | "quote" | "rule" | "image" | "fence" | "code" | "p" | "blank";

export interface LineInfo {
  kind: LineKind;
  /** Leading spaces of a list item (two per level) */
  indent: number;
  /** What the line starts with that the editor draws as a marker (`- `, `1. `, `> `) */
  marker: string;
  body: string;
  checked: boolean;
}

const rule = /^\s{0,3}([-*_])(\s*\1){2,}\s*$/;

/** Which lines sit inside a ``` fence (the fence lines included): they are drawn as code. */
export function fenceStates(lines: string[]): boolean[] {
  let open = false;
  return lines.map((l) => {
    if (/^\s*```/.test(l)) {
      open = !open;
      return true;
    }
    return open;
  });
}

export function parseLine(line: string, inFence = false): LineInfo {
  const at = (kind: LineKind, marker = "", checked = false): LineInfo => {
    const indent = /^ */.exec(line)![0].length;
    return { kind, indent, marker, body: line.slice(marker.length), checked };
  };
  if (inFence) return /^\s*```/.test(line) ? at("fence") : at("code");
  if (!line.trim()) return { kind: "blank", indent: 0, marker: "", body: "", checked: false };
  let m: RegExpExecArray | null;
  if ((m = /^(#{1,3}) +/.exec(line))) return at(`h${m[1].length}` as LineKind, m[0]);
  if (rule.test(line)) return at("rule");
  if ((m = /^( *)[-*+] \[([ xX])\] /.exec(line))) {
    return { ...at("task", m[0], m[2] !== " "), indent: m[1].length };
  }
  if ((m = /^( *)[-*+] /.exec(line))) return { ...at("bullet", m[0]), indent: m[1].length };
  if ((m = /^( *)\d+[.)] /.exec(line))) return { ...at("number", m[0]), indent: m[1].length };
  if ((m = /^> ?/.exec(line))) return at("quote", m[0]);
  if (/^!\[[^\]]*\]\([^)]+\)\s*$/.test(line.trim())) return at("image");
  return at("p");
}

/** What a new line starts with when Enter is pressed at the end of `line` (a list item continues;
 *  an empty one ends the list: the empty string). null: not a list line. */
export function continuation(line: string): string | null {
  let m: RegExpExecArray | null;
  if ((m = /^( *)([-*+]) \[[ xX]\] (.*)$/.exec(line))) return m[3].trim() ? `${m[1]}${m[2]} [ ] ` : "";
  if ((m = /^( *)([-*+]) (.*)$/.exec(line))) return m[3].trim() ? `${m[1]}${m[2]} ` : "";
  if ((m = /^( *)(\d+)([.)]) (.*)$/.exec(line))) return m[4].trim() ? `${m[1]}${Number(m[2]) + 1}${m[3]} ` : "";
  if ((m = /^(> ?)(.*)$/.exec(line))) return m[2].trim() ? m[1] : "";
  return null;
}

/** A line that is only a list marker (Backspace there removes the marker). */
export const isBareMarker = (line: string) => /^( *)([-*+] (\[[ xX]\] )?|\d+[.)] |> ?)$/.test(line);

/** `[ ] ` typed at the start of a line is a checklist item. */
export function shorthand(line: string): string {
  const m = /^\[( |x|X)?\] (.*)$/.exec(line);
  return m ? `- [${m[1] === "x" || m[1] === "X" ? "x" : " "}] ${m[2]}` : line;
}

export function toggleTask(line: string): string {
  return line.replace(/^( *[-*+] )\[([ xX])\]/, (_, head: string, c: string) => `${head}[${c === " " ? "x" : " "}]`);
}

export const indentLine = (line: string) => `  ${line}`;
export const outdentLine = (line: string) => line.replace(/^ {1,2}/, "");

// --- tags and stocks written in a text (the same rules as trading_os/pages.py and daily_notes.py)

const CODE = /```[\s\S]*?```|`[^`\n]*`/g;
const HASHTAG = /(?<![\w&/#[])#([A-Za-z][A-Za-z0-9_-]{0,39})(?![\w-]*\])/g;
const CASHTAG = /(?<![\w$])\$([A-Za-z][A-Za-z0-9.-]{0,9})\b/g;

export const normalizeTag = (raw: string): string => {
  const tag = raw.trim().replace(/^#/, "").toLowerCase();
  return /^[a-z][a-z0-9_-]{0,39}$/.test(tag) ? tag : "";
};

/** The `#tags` in a text, lowercase, in order, no repeats (code left out). */
export function hashtags(text: string): string[] {
  const plain = (text || "").replace(CODE, " ");
  const out: string[] = [];
  for (const m of plain.matchAll(HASHTAG)) {
    const tag = normalizeTag(m[1]);
    if (tag && !out.includes(tag)) out.push(tag);
  }
  return out;
}

/** The `$TICKER`s in a text, upper case, in order, no repeats. */
export function cashtags(text: string): string[] {
  const plain = (text || "").replace(CODE, " ");
  const out: string[] = [];
  for (const m of plain.matchAll(CASHTAG)) {
    const t = m[1].toUpperCase();
    if (!out.includes(t)) out.push(t);
  }
  return out;
}

/** `[[TICKER]]` is a stock; `[[Anything else]]` is a page. */
export const isTicker = (s: string) => /^[A-Z][A-Z0-9.-]{0,9}$/.test(s);

/** The page titles and stocks written as [[...]] in a text. */
export function wikilinks(text: string): string[] {
  const out: string[] = [];
  for (const m of (text || "").replace(CODE, " ").matchAll(/\[\[([^\]\n]+)\]\]/g)) {
    const t = m[1].trim();
    if (t && !out.includes(t)) out.push(t);
  }
  return out;
}

/** The stocks a text is about: `$TICKER` and `[[TICKER]]`. */
export function stocksIn(text: string): string[] {
  const found = [...cashtags(text), ...wikilinks(text).filter(isTicker)];
  return found.filter((t, i) => found.indexOf(t) === i);
}

// --- inline pieces

export type Inline =
  | { t: "text"; v: string }
  | { t: "bold" | "italic" | "strike"; c: Inline[] }
  | { t: "code"; v: string }
  | { t: "tag"; tag: string; raw: string }
  | { t: "ticker"; ticker: string; raw: string }
  | { t: "wiki"; title: string }
  | { t: "link"; href: string; c: Inline[] }
  | { t: "image"; alt: string; src: string };

const SAFE_HREF = /^(https?:\/\/|\/|#|mailto:)/i;

export function parseInline(src: string): Inline[] {
  const out: Inline[] = [];
  let text = "";
  const flush = () => {
    if (text) out.push({ t: "text", v: text });
    text = "";
  };
  let i = 0;
  while (i < src.length) {
    const rest = src.slice(i);
    const prev = i > 0 ? src[i - 1] : " ";
    let m: RegExpExecArray | null;
    if ((m = /^!\[([^\]]*)\]\(([^)\s]+)\)/.exec(rest))) {
      flush();
      if (SAFE_HREF.test(m[2])) out.push({ t: "image", alt: m[1], src: m[2] });
      else text += m[0];
    } else if ((m = /^\[\[([^\]\n]+)\]\]/.exec(rest))) {
      flush();
      out.push({ t: "wiki", title: m[1].trim() });
    } else if ((m = /^\[([^\]\n]+)\]\(([^)\s]+)\)/.exec(rest))) {
      if (SAFE_HREF.test(m[2])) {
        flush();
        out.push({ t: "link", href: m[2], c: parseInline(m[1]) });
      } else text += m[0];
    } else if ((m = /^`([^`\n]+)`/.exec(rest))) {
      flush();
      out.push({ t: "code", v: m[1] });
    } else if ((m = /^\*\*(?!\s)([^\n]+?)(?<!\s)\*\*/.exec(rest))) {
      flush();
      out.push({ t: "bold", c: parseInline(m[1]) });
    } else if ((m = /^~~(?!\s)([^\n]+?)(?<!\s)~~/.exec(rest))) {
      flush();
      out.push({ t: "strike", c: parseInline(m[1]) });
    } else if ((m = /^\*(?![\s*])([^*\n]+?)(?<![\s*])\*/.exec(rest))) {
      flush();
      out.push({ t: "italic", c: parseInline(m[1]) });
    } else if (!/[\w]/.test(prev) && (m = /^#([A-Za-z][A-Za-z0-9_-]{0,39})(?![\w-])/.exec(rest))) {
      flush();
      out.push({ t: "tag", tag: normalizeTag(m[1]), raw: m[0] });
    } else if (!/[\w$]/.test(prev) && (m = /^\$([A-Za-z][A-Za-z0-9.-]{0,9})\b/.exec(rest))) {
      flush();
      out.push({ t: "ticker", ticker: m[1].toUpperCase(), raw: m[0] });
    } else {
      text += src[i];
      i += 1;
      continue;
    }
    i += m![0].length;
  }
  flush();
  return out;
}

// --- the page's own words

/** The first line that says something, without its markdown marks (a snippet for a list). */
export function snippet(text: string, max = 110): string {
  for (const line of (text || "").split("\n")) {
    const plain = line
      .replace(/^\s*(#{1,3} |[-*+] (\[[ xX]\] )?|\d+[.)] |> ?)/, "")
      .replace(/!\[[^\]]*\]\([^)]*\)/g, "[image]")
      .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
      .replace(/[*_`~]/g, "")
      .trim();
    if (plain && !/^```/.test(plain) && !rule.test(plain)) {
      return plain.length > max ? `${plain.slice(0, max - 1)}…` : plain;
    }
  }
  return "";
}

/** The text with `#tag` added at its end unless it is in there already. */
export function withTag(text: string, tag: string): string {
  const t = normalizeTag(tag);
  if (!t || hashtags(text).includes(t)) return text;
  return `${text.replace(/\s+$/, "")}${text.trim() ? "\n" : ""}#${t}`;
}

/** The text without the `#tag` written in it. */
export function withoutTag(text: string, tag: string): string {
  const re = new RegExp(`[ \\t]?(?<![\\w&/#[])#${tag.replace(/[-_]/g, (c) => `\\${c}`)}(?![\\w-])`, "gi");
  return text
    .replace(re, "")
    .replace(/[ \t]+$/gm, "")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/\s+$/, "");
}

export type Trigger = { kind: "slash" | "tag" | "ticker" | "wiki"; query: string; start: number } | null;

/** What the caret is in the middle of typing: a `/` command, a `#tag`, a `$TICKER` or a `[[link`. */
export function detectTrigger(value: string, caret: number): Trigger {
  const before = value.slice(0, caret);
  let m: RegExpExecArray | null;
  if ((m = /\[\[([^\]\n]*)$/.exec(before))) return { kind: "wiki", query: m[1], start: caret - m[0].length };
  if ((m = /(^|\s)\/([a-z0-9]*)$/i.exec(before))) {
    return { kind: "slash", query: m[2].toLowerCase(), start: caret - m[2].length - 1 };
  }
  if ((m = /(^|[^\w&/#[])#([A-Za-z0-9_-]*)$/.exec(before))) {
    return { kind: "tag", query: m[2].toLowerCase(), start: caret - m[2].length - 1 };
  }
  if ((m = /(^|[^\w$])\$([A-Za-z][A-Za-z0-9.-]{0,9}|)$/.exec(before))) {
    return { kind: "ticker", query: m[2].toUpperCase(), start: caret - m[2].length - 1 };
  }
  return null;
}
