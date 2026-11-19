// The notebook's editor: markdown with a live preview in the Obsidian sense. Every line is drawn
// as it will read (heading, list, checklist, quote, bold, #tag, $TICKER, [[link]]) except the line
// you are on, which shows its plain markdown; the stored text is that plain markdown, line by line.
//   `# `, `- `, `1. `, `[ ] `, `> `, `**b**`, `---`, `/` for the slash menu, `#` tags, `$` stocks,
//   `[[` pages. Paste or drop an image and it is saved as an attachment. Enter continues a list,
//   Tab indents it, arrows move between lines, Escape leaves the line.
import { type ClipboardEvent, type KeyboardEvent, type ReactNode, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { Icon } from "../ui/Icon";
import { PHONE, useMedia } from "../ui/kit";
import { useNbEnv } from "./env";
import { InlineText } from "./Inline";
import {
  continuation, detectTrigger, fenceStates, indentLine, isBareMarker, outdentLine, parseLine, shorthand,
  toggleTask, type Trigger,
} from "./text";

interface Item {
  id: string;
  label: string;
  hint?: string;
}

const SLASH: (Item & { words: string })[] = [
  { id: "h1", label: "Heading 1", hint: "#", words: "heading title h1" },
  { id: "h2", label: "Heading 2", hint: "##", words: "heading h2" },
  { id: "h3", label: "Heading 3", hint: "###", words: "heading h3" },
  { id: "task", label: "Checklist", hint: "[ ]", words: "checklist todo task check" },
  { id: "bullet", label: "Bulleted list", hint: "-", words: "bullet list" },
  { id: "number", label: "Numbered list", hint: "1.", words: "number list" },
  { id: "quote", label: "Quote", hint: ">", words: "quote" },
  { id: "rule", label: "Divider", hint: "---", words: "divider line rule" },
  { id: "image", label: "Image or screenshot", hint: "img", words: "image screenshot picture photo" },
  { id: "ticker", label: "Ticker", hint: "$", words: "ticker stock symbol" },
  { id: "tag", label: "Tag", hint: "#", words: "tag label" },
];

const PREFIX: Record<string, string> = {
  h1: "# ", h2: "## ", h3: "### ", task: "- [ ] ", bullet: "- ", number: "1. ", quote: "> ",
};

const split = (text: string) => (text === "" ? [""] : text.replace(/\r\n/g, "\n").split("\n"));

function asBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error ?? new Error("read failed"));
    reader.readAsDataURL(file);
  });
}

export interface EditorProps {
  value: string;
  onChange: (text: string) => void;
  /** The attachment folder pasted images go to (a trade id, a ticker, a page) */
  imageRef: string;
  label: string;
  placeholder?: string;
  autoFocus?: boolean;
}

export function Editor({ value, onChange, imageRef, label, placeholder, autoFocus }: EditorProps) {
  const env = useNbEnv();
  const phone = useMedia(PHONE);
  const [lines, setLines] = useState(() => split(value));
  const [active, setActive] = useState<number | null>(autoFocus ? 0 : null);
  const [caret, setCaret] = useState(0);
  const [pick, setPick] = useState(0);
  const [dismissed, setDismissed] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const area = useRef<HTMLTextAreaElement>(null);
  const file = useRef<HTMLInputElement>(null);
  const wants = useRef<number | "end" | null>(autoFocus ? "end" : null);
  const fences = useMemo(() => fenceStates(lines), [lines]);

  const commit = (next: string[], focus?: { idx: number; pos?: number | "end" }) => {
    const safe = next.length ? next : [""];
    setLines(safe);
    onChange(safe.join("\n"));
    if (focus) {
      wants.current = focus.pos ?? "end";
      setActive(focus.idx);
      setTick((t) => t + 1);
    }
  };
  const setLine = (idx: number, text: string, pos?: number | "end") =>
    commit(lines.map((l, i) => (i === idx ? text : l)), pos === undefined ? undefined : { idx, pos });

  // The line being typed grows with its text
  useLayoutEffect(() => {
    const el = area.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  });
  // Focus the line that became active, with the caret where it was asked for
  useLayoutEffect(() => {
    const el = area.current;
    if (!el || active === null || wants.current === null) return;
    el.focus();
    const at = wants.current === "end" ? el.value.length : Math.min(wants.current, el.value.length);
    el.setSelectionRange(at, at);
    setCaret(at);
    wants.current = null;
  }, [active, tick]);

  // The phone's format bar rides above the keyboard (the visual viewport shrinks when it opens)
  const typing = active !== null;
  useEffect(() => {
    const vv = window.visualViewport;
    if (!phone || !typing || !vv) return;
    const set = () =>
      document.documentElement.style.setProperty("--kb", `${Math.max(0, window.innerHeight - vv.height - vv.offsetTop)}px`);
    set();
    vv.addEventListener("resize", set);
    vv.addEventListener("scroll", set);
    return () => {
      vv.removeEventListener("resize", set);
      vv.removeEventListener("scroll", set);
      document.documentElement.style.removeProperty("--kb");
    };
  }, [phone, typing]);

  // --- the menu under the line being typed
  const line = active === null ? "" : (lines[active] ?? "");
  const trigger: Trigger = active === null ? null : detectTrigger(line, caret);
  const key = trigger ? `${active}:${trigger.kind}:${trigger.start}` : null;
  const items = useMemo<Item[]>(() => {
    if (!trigger) return [];
    const q = trigger.query;
    if (trigger.kind === "slash") return SLASH.filter((s) => !q || s.words.includes(q) || s.label.toLowerCase().includes(q));
    if (trigger.kind === "tag") {
      const have = env.tags.filter((t) => t.startsWith(q)).slice(0, 7).map((t) => ({ id: t, label: `#${t}` }));
      const fresh = q && /^[a-z][a-z0-9_-]*$/.test(q) && !env.tags.includes(q) ? [{ id: q, label: `#${q}`, hint: "new tag" }] : [];
      return [...have, ...fresh];
    }
    if (trigger.kind === "ticker") {
      const pool = [...new Set([...env.tickers, ...env.symbols])];
      return pool.filter((t) => t.startsWith(q)).slice(0, 8).map((t) => ({ id: t, label: `$${t}` }));
    }
    const titles = env.pages.filter((p) => p.title.toLowerCase().includes(q.toLowerCase())).slice(0, 6);
    const stocks = q ? env.tickers.filter((t) => t.startsWith(q.toUpperCase())).slice(0, 3) : [];
    const out: Item[] = [...titles.map((p) => ({ id: p.title, label: p.title })), ...stocks.map((t) => ({ id: t, label: t, hint: "stock" }))];
    if (q.trim() && !titles.some((p) => p.title.toLowerCase() === q.trim().toLowerCase())) {
      out.push({ id: q.trim(), label: `New page “${q.trim()}”`, hint: "create" });
    }
    return out;
  }, [trigger, env]);
  const menuOpen = !!trigger && items.length > 0 && key !== dismissed;
  useEffect(() => setPick(0), [key, items.length]);

  const upload = async (files: File[], at: number) => {
    const images = files.filter((f) => f.type.startsWith("image/"));
    if (!images.length) return;
    setNote("Saving the image…");
    try {
      const made: string[] = [];
      for (const f of images) {
        const name = /\.(png|jpe?g|gif|webp)$/i.test(f.name) ? f.name : `pasted.${f.type.split("/")[1] || "png"}`;
        const out = await api.noteImage(imageRef, name, await asBase64(f));
        made.push(`![${name.replace(/\.[^.]+$/, "")}](${out.url})`);
      }
      const here = lines[at] ?? "";
      const from = here.trim() ? at + 1 : at; // an empty line is replaced by the image, a written one keeps its place
      const next = [...lines.slice(0, from), ...made, "", ...lines.slice(at + 1)];
      commit(next, { idx: from + made.length, pos: 0 });
      setNote(null);
    } catch (e) {
      setNote(`Image not saved: ${(e as Error).message}`);
    }
  };

  const choose = (item: Item) => {
    if (!trigger || active === null) return;
    const before = line.slice(0, trigger.start);
    const after = line.slice(caret);
    if (trigger.kind === "slash") {
      const joined = (before + after).replace(/\s+$/, "");
      const rest = isBareMarker(`${joined} `) ? "" : joined; // an empty list item is replaced, not kept
      if (PREFIX[item.id]) return setLine(active, PREFIX[item.id] + rest.trimStart(), "end");
      if (item.id === "rule") {
        const next = [...lines];
        next[active] = rest.trim() ? rest : "---";
        const at = rest.trim() ? active + 1 : active;
        if (rest.trim()) next.splice(active + 1, 0, "---");
        next.splice(at + 1, 0, "");
        return commit(next, { idx: at + 1, pos: 0 });
      }
      if (item.id === "image") {
        setLine(active, rest, "end");
        return file.current?.click();
      }
      const mark = item.id === "ticker" ? "$" : "#";
      return setLine(active, `${before}${mark}${after}`, before.length + 1);
    }
    const text = trigger.kind === "wiki" ? `[[${item.id}]]` : trigger.kind === "ticker" ? `$${item.id}` : `#${item.id}`;
    const tail = after.startsWith("]]") ? after.slice(2) : after;
    setLine(active, `${before}${text}${tail.startsWith(" ") ? "" : " "}${tail.replace(/^ /, "")}`, before.length + text.length + 1);
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (active === null) return;
    const el = e.currentTarget;
    const mod = e.ctrlKey || e.metaKey;
    if (menuOpen) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        setPick((p) => (p + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length);
        return;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        choose(items[Math.min(pick, items.length - 1)]);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setDismissed(key);
        return;
      }
    }
    const at = el.selectionStart;
    const end = el.selectionEnd;
    if (mod && (e.key === "b" || e.key === "i")) {
      e.preventDefault();
      const m = e.key === "b" ? "**" : "*";
      const text = line.slice(0, at) + m + line.slice(at, end) + m + line.slice(end);
      return setLine(active, text, at === end ? at + m.length : end + 2 * m.length);
    }
    if (e.key === "Enter") {
      e.preventDefault();
      const head = line.slice(0, at);
      const tail = line.slice(end);
      const next = fences[active] ? null : continuation(head);
      if (next === "" && !tail.trim()) return setLine(active, "", 0); // an empty item ends the list
      const nextLine = (next ?? (/^( +)/.exec(head)?.[1] ?? "")) + tail;
      const lead = (next ?? "").length || (/^( +)/.exec(head)?.[1] ?? "").length;
      return commit([...lines.slice(0, active), head, nextLine, ...lines.slice(active + 1)], { idx: active + 1, pos: lead });
    }
    if (e.key === "Backspace" && at === 0 && end === 0 && active > 0) {
      e.preventDefault();
      const prev = lines[active - 1];
      return commit([...lines.slice(0, active - 1), prev + line, ...lines.slice(active + 1)], { idx: active - 1, pos: prev.length });
    }
    if (e.key === "Backspace" && at === end && at === line.length && isBareMarker(line)) {
      e.preventDefault();
      return setLine(active, "", 0);
    }
    if (e.key === "Tab" && /^ *([-*+] |\d+[.)] )/.test(line)) {
      e.preventDefault();
      const text = e.shiftKey ? outdentLine(line) : indentLine(line);
      return setLine(active, text, Math.max(0, at + text.length - line.length));
    }
    const oneRow = el.scrollHeight <= el.clientHeight + 4 && el.clientHeight < 60;
    if (e.key === "ArrowUp" && !e.shiftKey && (at === 0 || oneRow) && active > 0) {
      e.preventDefault();
      wants.current = Math.min(at, lines[active - 1].length);
      return setActive(active - 1);
    }
    if (e.key === "ArrowDown" && !e.shiftKey && (at === line.length || oneRow) && active < lines.length - 1) {
      e.preventDefault();
      wants.current = Math.min(at, lines[active + 1].length);
      return setActive(active + 1);
    }
    if (e.key === "Escape") {
      e.preventDefault();
      el.blur();
      setActive(null);
    }
  };

  const onPaste = (e: ClipboardEvent<HTMLTextAreaElement>) => {
    if (active === null) return;
    const files = Array.from(e.clipboardData.files);
    if (files.some((f) => f.type.startsWith("image/"))) {
      e.preventDefault();
      void upload(files, active);
      return;
    }
    const text = e.clipboardData.getData("text/plain");
    if (!text.includes("\n")) return;
    e.preventDefault();
    const el = e.currentTarget;
    const pasted = text.replace(/\r\n/g, "\n").split("\n");
    const head = line.slice(0, el.selectionStart) + pasted[0];
    const last = pasted[pasted.length - 1];
    const tail = line.slice(el.selectionEnd);
    commit(
      [...lines.slice(0, active), head, ...pasted.slice(1, -1), last + tail, ...lines.slice(active + 1)],
      { idx: active + pasted.length - 1, pos: last.length },
    );
  };

  // The phone's toolbar: bold, list, checklist, #, $, image
  const tool = (what: string) => {
    if (active === null) return;
    const el = area.current;
    const at = el?.selectionStart ?? line.length;
    const end = el?.selectionEnd ?? at;
    if (what === "bold") {
      return setLine(active, `${line.slice(0, at)}**${line.slice(at, end)}**${line.slice(end)}`, at === end ? at + 2 : end + 4);
    }
    if (what === "image") return file.current?.click();
    if (what === "bullet" || what === "task") {
      const mark = what === "task" ? "- [ ] " : "- ";
      const bare = line.replace(/^ *([-*+] (\[[ xX]\] )?|\d+[.)] |> |#{1,3} )/, "");
      return setLine(active, line.startsWith(mark) ? bare : mark + bare, "end");
    }
    const ch = what === "tag" ? "#" : "$";
    setLine(active, line.slice(0, at) + ch + line.slice(end), at + 1);
  };

  const body: ReactNode[] = lines.map((text, i) => {
    if (i === active) {
      const info = parseLine(text, fences[i]);
      return (
        <div className="ed-line on" key={i}>
          <textarea
            ref={area}
            className={`ed-input k-${info.kind}`}
            aria-label={`${label}, line ${i + 1}`}
            value={text}
            rows={1}
            spellCheck
            placeholder={lines.length === 1 && !text ? (placeholder ?? "Type / for commands") : undefined}
            onChange={(e) => {
              const v = shorthand(e.target.value);
              setCaret(v === e.target.value ? e.target.selectionStart : v.length);
              setLine(i, v, v === e.target.value ? undefined : "end");
            }}
            onKeyDown={onKey}
            onKeyUp={(e) => setCaret(e.currentTarget.selectionStart)}
            onClick={(e) => setCaret(e.currentTarget.selectionStart)}
            onPaste={onPaste}
            onBlur={() => {
              // A click on the menu or the toolbar keeps the line; elsewhere the line is drawn again
              window.setTimeout(() => {
                if (document.activeElement?.closest(".ed-menu, .ed-toolbar")) return;
                if (document.activeElement !== area.current) setActive((a) => (a === i ? null : a));
              }, 120);
            }}
          />
          {menuOpen && (
            <ul className="ed-menu" role="listbox" aria-label="Suggestions">
              {items.map((it, k) => (
                <li
                  key={it.id}
                  role="option"
                  aria-selected={k === pick}
                  className={k === pick ? "on" : ""}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    choose(it);
                  }}
                  onMouseEnter={() => setPick(k)}
                >
                  <span>{it.label}</span>
                  {it.hint && <kbd>{it.hint}</kbd>}
                </li>
              ))}
            </ul>
          )}
        </div>
      );
    }
    const info = parseLine(text, fences[i]);
    const open = () => {
      wants.current = "end";
      setActive(i);
    };
    const click = (e: React.MouseEvent) => {
      if ((e.target as HTMLElement).closest("a, input, button")) return;
      open();
    };
    const pad = { paddingLeft: info.indent * 9 };
    let view: ReactNode;
    switch (info.kind) {
      case "blank":
        view = lines.length === 1 ? <span className="ed-placeholder">{placeholder ?? "Type / for commands"}</span> : <br />;
        break;
      case "h1": case "h2": case "h3":
        view = <span className={`ed-${info.kind}`}><InlineText text={info.body} /></span>;
        break;
      case "bullet":
        view = <span className="ed-li" style={pad}><i className="ed-dot" aria-hidden>•</i><span><InlineText text={info.body} /></span></span>;
        break;
      case "number":
        view = <span className="ed-li" style={pad}><i className="ed-num">{info.marker.trim()}</i><span><InlineText text={info.body} /></span></span>;
        break;
      case "task":
        view = (
          <span className="ed-li" style={pad}>
            <input
              type="checkbox"
              checked={info.checked}
              aria-label={`Done: ${info.body}`}
              onChange={() => setLine(i, toggleTask(text))}
            />
            <span className={info.checked ? "done" : ""}><InlineText text={info.body} /></span>
          </span>
        );
        break;
      case "quote":
        view = <span className="ed-quote"><InlineText text={info.body} /></span>;
        break;
      case "rule":
        view = <hr className="ed-rule" />;
        break;
      case "fence":
        view = <span className="ed-fence">{text.trim() || "```"}</span>;
        break;
      case "code":
        view = <code className="ed-code">{text || " "}</code>;
        break;
      default:
        view = <InlineText text={text} />;
    }
    return (
      <div className={`ed-line k-${info.kind}`} key={i} onClick={click}>
        {view}
      </div>
    );
  });

  return (
    <div
      className="editor"
      aria-label={label}
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        if (!e.dataTransfer.files.length) return;
        e.preventDefault();
        void upload(Array.from(e.dataTransfer.files), active ?? lines.length - 1);
      }}
    >
      {body}
      <div
        className="ed-tail"
        aria-hidden
        onMouseDown={(e) => e.preventDefault()} // the line being typed keeps the focus
        onClick={() => {
          const last = lines[lines.length - 1];
          if (last.trim()) commit([...lines, ""], { idx: lines.length, pos: 0 });
          else commit(lines, { idx: lines.length - 1, pos: 0 });
        }}
      />
      {note && <p className="ed-note muted">{note}</p>}
      <input
        ref={file}
        type="file"
        accept="image/*"
        className="sr-only"
        aria-label="Add an image"
        tabIndex={-1}
        onChange={(e) => {
          const picked = Array.from(e.target.files ?? []);
          e.target.value = "";
          void upload(picked, active ?? lines.length - 1);
        }}
      />
      {phone && active !== null && (
        <div className="ed-toolbar" role="toolbar" aria-label="Format">
          {(
            [
              ["bold", "B", "Bold"], ["bullet", "•", "List"], ["task", "☐", "Checklist"], ["tag", "#", "Tag"], ["ticker", "$", "Stock"],
            ] as const
          ).map(([id, text, name]) => (
            <button key={id} type="button" aria-label={name} onMouseDown={(e) => e.preventDefault()} onClick={() => tool(id)}>
              {text}
            </button>
          ))}
          <button type="button" aria-label="Image" onMouseDown={(e) => e.preventDefault()} onClick={() => tool("image")}>
            <Icon name="upload" size={18} />
          </button>
        </div>
      )}
    </div>
  );
}
