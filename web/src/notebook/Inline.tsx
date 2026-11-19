// The inline pieces of a line, drawn: bold, italic, code, links, #tags (a chip that opens the tag
// view), $TICKER and [[TICKER]] (a link to the stock page with a hover card: last, % change,
// grade) and [[Page title]]. Built as elements, never as HTML, so a note cannot inject markup.
import { Fragment, type ReactNode, useState } from "react";
import { api, type NbCard } from "../api";
import { GradeBadge } from "../components/Card";
import { signed } from "../format";
import { noteHref, useNbEnv, wikiTarget } from "./env";
import { type Inline, parseInline } from "./text";

const cards = new Map<string, Promise<NbCard | null>>();

function card(ticker: string): Promise<NbCard | null> {
  let found = cards.get(ticker);
  if (!found) {
    found = api.noteCards([ticker]).then(
      (r) => r[ticker] ?? null,
      () => {
        cards.delete(ticker); // try again next time
        return null;
      },
    );
    cards.set(ticker, found);
  }
  return found;
}

export function TickerRef({ ticker, label }: { ticker: string; label?: string }) {
  const [shown, setShown] = useState<NbCard | null | undefined>(undefined);
  const [open, setOpen] = useState(false);
  const show = () => {
    setOpen(true);
    if (shown === undefined) card(ticker).then(setShown);
  };
  return (
    <span className="nb-ref" onMouseEnter={show} onMouseLeave={() => setOpen(false)} onFocus={show} onBlur={() => setOpen(false)}>
      <a className="nb-ticker" href={noteHref(`stock:${ticker}`)}>
        {label ?? `$${ticker}`}
      </a>
      {open && (
        <span className="nb-card" role="tooltip">
          <b>{ticker}</b>
          {shown === undefined && <span className="muted"> …</span>}
          {shown === null && <span className="muted"> no price</span>}
          {shown && (
            <>
              <span className="num"> {shown.last === null ? "–" : shown.last.toFixed(2)}</span>
              {shown.chg_pct !== null && (
                <span className={`num ${shown.chg_pct >= 0 ? "up" : "down"}`}> {signed(shown.chg_pct, 1, "%")}</span>
              )}
              {shown.grade && <GradeBadge grade={shown.grade} />}
              {shown.grade === "" && shown.last !== null && <span className="muted"> not a hit today</span>}
            </>
          )}
        </span>
      )}
    </span>
  );
}

function Pieces({ parts }: { parts: Inline[] }) {
  const env = useNbEnv();
  const draw = (p: Inline, i: number): ReactNode => {
    switch (p.t) {
      case "text":
        return <Fragment key={i}>{p.v}</Fragment>;
      case "bold":
        return <strong key={i}>{p.c.map(draw)}</strong>;
      case "italic":
        return <em key={i}>{p.c.map(draw)}</em>;
      case "strike":
        return <s key={i}>{p.c.map(draw)}</s>;
      case "code":
        return <code key={i}>{p.v}</code>;
      case "tag":
        return (
          <a key={i} className="nb-tag" href={noteHref(`tag:${p.tag}`)}>
            #{p.tag}
          </a>
        );
      case "ticker":
        return <TickerRef key={i} ticker={p.ticker} />;
      case "wiki": {
        const target = wikiTarget(p.title, env.pages);
        if (target.startsWith("stock:")) return <TickerRef key={i} ticker={p.title} label={p.title} />;
        return (
          <a key={i} className={`nb-wiki${target.startsWith("new:") ? " missing" : ""}`} href={noteHref(target)}>
            {p.title}
          </a>
        );
      }
      case "link":
        return (
          <a key={i} href={p.href} target={p.href.startsWith("#") ? undefined : "_blank"} rel="noreferrer">
            {p.c.map(draw)}
          </a>
        );
      case "image":
        return <img key={i} className="nb-img" src={p.src} alt={p.alt} />;
    }
  };
  return <>{parts.map(draw)}</>;
}

export function InlineText({ text }: { text: string }) {
  return <Pieces parts={parseInline(text)} />;
}
