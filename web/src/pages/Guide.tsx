// The guide (docs/GUIDE.md): how the system works, what every scan and study does, and what
// each dashboard page shows.
import { useEffect, useState } from "react";
import { api } from "../api";
import { Markdown } from "../components/Markdown";

export function Guide() {
  const [text, setText] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    api.guide().then((g) => setText(g.text), () => setText(null));
  }, []);
  return (
    <div className="guide">
      {text === undefined && <p className="muted">Loading…</p>}
      {text === null && <p className="muted">The guide isn't on the server (docs/GUIDE.md).</p>}
      {text && <Markdown text={text} />}
    </div>
  );
}
