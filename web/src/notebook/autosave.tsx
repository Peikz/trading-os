// Autosave: a change is written after a short pause (or at once when the page is left), one write
// at a time, with a status for the "Saved" label. No Save button.
import { useCallback, useEffect, useRef, useState } from "react";

export type SaveStatus = "idle" | "dirty" | "saving" | "saved" | "error";

export const SAVE_DELAY_MS = 700;

export function useAutosave<T>(save: (value: T) => Promise<unknown>, delay = SAVE_DELAY_MS) {
  const [status, setStatus] = useState<SaveStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const latest = useRef<{ value: T } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const busy = useRef(false);
  const saver = useRef(save);
  saver.current = save;
  const alive = useRef(true);

  const run = useCallback(async () => {
    if (busy.current) return; // the running write picks the newest value up when it ends
    busy.current = true;
    try {
      while (latest.current) {
        const { value } = latest.current;
        latest.current = null;
        if (alive.current) setStatus("saving");
        try {
          await saver.current(value);
          if (alive.current) {
            setError(null);
            setStatus(latest.current ? "saving" : "saved");
          }
        } catch (e) {
          if (alive.current) {
            setError((e as Error).message);
            setStatus("error");
          }
        }
      }
    } finally {
      busy.current = false;
    }
  }, []);

  const push = useCallback(
    (value: T) => {
      latest.current = { value };
      setStatus("dirty");
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(run, delay);
    },
    [run, delay],
  );

  /** Write what is waiting now (leaving the page, closing the tab). */
  const flush = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    if (latest.current) void run();
  }, [run]);

  useEffect(() => {
    alive.current = true;
    const hide = () => document.visibilityState === "hidden" && flush();
    window.addEventListener("pagehide", flush);
    document.addEventListener("visibilitychange", hide);
    return () => {
      window.removeEventListener("pagehide", flush);
      document.removeEventListener("visibilitychange", hide);
      flush();
      alive.current = false;
    };
  }, [flush]);

  return { status, error, push, flush };
}

export function SaveLabel({ status, error }: { status: SaveStatus; error?: string | null }) {
  const text =
    status === "saving" ? "Saving…" : status === "saved" ? "Saved" : status === "dirty" ? "Editing…" : status === "error" ? `Not saved: ${error ?? "error"}` : "";
  return (
    <span className={`nb-save ${status}`} role="status" aria-live="polite">
      {text}
    </span>
  );
}
