// Small building blocks shared by every place: a segmented control, a tab row, a popover that
// closes on Escape or an outside click, and a media query hook (the phone layout).
import { type ReactNode, useEffect, useRef, useState } from "react";

export function Segmented<T extends string>({
  label,
  options,
  value,
  onPick,
}: {
  label: string;
  options: readonly (readonly [T, ReactNode])[] | readonly T[];
  value: T;
  onPick: (v: T) => void;
}) {
  const items = options.map((o) => (Array.isArray(o) ? o : [o, o])) as [T, ReactNode][];
  return (
    <div className="seg" role="group" aria-label={label}>
      {items.map(([v, text]) => (
        <button key={v} type="button" aria-pressed={value === v} onClick={() => onPick(v)}>
          {text}
        </button>
      ))}
    </div>
  );
}

export function TabRow<T extends string>({
  label,
  tabs,
  value,
  onPick,
  small,
}: {
  label: string;
  tabs: readonly (readonly [T, string])[];
  value: T;
  onPick: (v: T) => void;
  small?: boolean;
}) {
  return (
    <div className={`tabs${small ? " small" : ""}`} role="tablist" aria-label={label}>
      {tabs.map(([id, text]) => (
        <button key={id} type="button" role="tab" aria-selected={value === id} onClick={() => onPick(id)}>
          {text}
        </button>
      ))}
    </div>
  );
}

/** Open/close state for a popover or menu: closes on Escape and on a click outside `ref`. */
export function usePopover<T extends HTMLElement = HTMLDivElement>() {
  const [open, setOpen] = useState(false);
  const ref = useRef<T>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);
  return { open, setOpen, ref };
}

/** True while the media query matches (`(max-width: 639px)`: the phone layout). */
export function useMedia(query: string): boolean {
  const get = () => typeof window.matchMedia === "function" && window.matchMedia(query).matches;
  const [match, setMatch] = useState(get);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const m = window.matchMedia(query);
    const on = () => setMatch(m.matches);
    on();
    m.addEventListener?.("change", on);
    return () => m.removeEventListener?.("change", on);
  }, [query]);
  return match;
}

export const PHONE = "(max-width: 639px)";

/** True when a key press came from a text field (hotkeys stay out of the way there). */
export function typing(e: KeyboardEvent): boolean {
  const t = e.target as HTMLElement | null;
  if (!t) return false;
  return ["INPUT", "SELECT", "TEXTAREA"].includes(t.tagName) || t.isContentEditable;
}
