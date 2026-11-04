// Pull latest and Save & push, run automatically (design review 4 Nov 2026): a pull when the
// dashboard opens and every 10 minutes while it is on screen; a Save & push 20 seconds after
// your last change (grades, notes, journal, watchlists, alerts, drawings, screens). The buttons
// stay in Settings as the manual fallback. A pull that brought new runs shows "New data" in the
// top bar instead of reloading the page under your hands.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, onWrite } from "../api";

export interface SyncResult {
  ok: boolean;
  message: string;
  at: Date;
}

export interface Sync {
  auto: boolean;
  setAuto: (on: boolean) => void;
  busy: "pull" | "push" | null;
  pull: SyncResult | null;
  push: SyncResult | null;
  unsaved: boolean;
  fresh: boolean;
  clearFresh: () => void;
  pullNow: () => Promise<void>;
  pushNow: () => Promise<void>;
}

const KEY = "trading-os.auto-sync";
export const PULL_EVERY_MS = 10 * 60 * 1000;
export const PUSH_AFTER_MS = 20 * 1000;

function readAuto(): boolean {
  try {
    return window.localStorage.getItem(KEY) !== "off";
  } catch {
    return true;
  }
}

export function useSync(): Sync {
  const [auto, setAutoState] = useState(readAuto);
  const [busy, setBusy] = useState<"pull" | "push" | null>(null);
  const [pull, setPull] = useState<SyncResult | null>(null);
  const [push, setPush] = useState<SyncResult | null>(null);
  const [unsaved, setUnsaved] = useState(false);
  const [fresh, setFresh] = useState(false);
  const running = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const setAuto = useCallback((on: boolean) => {
    setAutoState(on);
    try {
      window.localStorage.setItem(KEY, on ? "on" : "off");
    } catch {
      /* private window: on for this visit only */
    }
  }, []);

  const pullNow = useCallback(async () => {
    if (running.current) return;
    running.current = true;
    setBusy("pull");
    try {
      const r = await api.pull();
      setPull({ ...r, at: new Date() });
      if (r.ok && !/up to date/i.test(r.message)) setFresh(true);
    } catch (e) {
      setPull({ ok: false, message: (e as Error).message, at: new Date() });
    } finally {
      running.current = false;
      setBusy(null);
    }
  }, []);

  const pushNow = useCallback(async () => {
    if (running.current) return;
    running.current = true;
    setBusy("push");
    try {
      const r = await api.push();
      setPush({ ...r, at: new Date() });
      if (r.ok) setUnsaved(false);
    } catch (e) {
      setPush({ ok: false, message: (e as Error).message, at: new Date() });
    } finally {
      running.current = false;
      setBusy(null);
    }
  }, []);

  // A pull on open and every 10 minutes while the page is visible
  useEffect(() => {
    if (!auto) return;
    pullNow();
    const every = setInterval(() => {
      if (document.visibilityState !== "hidden") pullNow();
    }, PULL_EVERY_MS);
    return () => clearInterval(every);
  }, [auto, pullNow]);

  // A Save & push shortly after the last change
  useEffect(
    () =>
      onWrite(() => {
        setUnsaved(true);
        if (!auto) return;
        if (timer.current) clearTimeout(timer.current);
        timer.current = setTimeout(() => {
          timer.current = null;
          pushNow();
        }, PUSH_AFTER_MS);
      }),
    [auto, pushNow],
  );
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  return {
    auto,
    setAuto,
    busy,
    pull,
    push,
    unsaved,
    fresh,
    clearFresh: () => setFresh(false),
    pullNow,
    pushNow,
  };
}

export function ago(at: Date, now = new Date()): string {
  const s = Math.max(0, Math.round((now.getTime() - at.getTime()) / 1000));
  if (s < 60) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  return `${at.getHours().toString().padStart(2, "0")}:${at.getMinutes().toString().padStart(2, "0")}`;
}
