// Practice (trading_os/practice.py; the Streamlit page app/practice.py): a past signal as the chart
// up to the entry and the facts known then, four answers (Skip, 1, 2, 3 = half, normal and 1.5x
// size), then the whole trade and what your pick made. Your numbers compare your picks with taking
// every signal, blind against shown. Answers append to data/practice/answers/ through the same
// function Streamlit uses; the bars after the entry are never sent before you answer.
// On a phone the answers are big thumb buttons.
import { useCallback, useEffect, useState } from "react";
import {
  api,
  type PracticeAnswered,
  type PracticeSignal,
  type PracticeState,
  type PracticeStats,
} from "../api";
import { DrawChart } from "../components/DrawChart";
import { Icon } from "../ui/Icon";
import { PHONE, Segmented, TabRow, usePopover, useMedia } from "../ui/kit";

const DEFAULT_LINES = ["MA10", "MA20", "MA50"];
const MULTIPLIER: Record<string, number> = { skip: 0, "1": 0.5, "2": 1, "3": 1.5 };

const r = (x: number | null | undefined, digits = 2) =>
  x === null || x === undefined ? "–" : `${x >= 0 ? "+" : ""}${x.toFixed(digits)} R`;
const choiceName = (c: string) => (c === "skip" ? "Skip" : c);

function Facts({ sig }: { sig: PracticeSignal }) {
  return (
    <div className="pr-grid" aria-label="Facts known at the entry">
      {sig.facts.map((f) => (
        <div key={f.label}>
          <small>{f.label}</small>
          {f.value}
        </div>
      ))}
    </div>
  );
}

function ResultLine({ sig }: { sig: PracticeSignal }) {
  const res = sig.result;
  if (!res) return null;
  return (
    <p className="pr-result" role="status">
      <b>{res.ticker}</b>, entry {res.entry_date} · net <b className={res.net_r >= 0 ? "up" : "down"}>{r(res.net_r)}</b> in{" "}
      {res.hold_days} days · your pick {res.choice === "skip" ? "skip" : res.choice} ={" "}
      <b className={res.pick_r >= 0 ? "up" : "down"}>{r(res.pick_r)}</b>
    </p>
  );
}

function StatsPanel({ s }: { s: PracticeStats }) {
  if (!s.answered) {
    return (
      <p className="muted">
        {s.remaining} left of {s.pool_size}. No answers yet.
      </p>
    );
  }
  return (
    <div className="pr-stats">
      <p className="muted">
        {s.answered} answered, {s.remaining} left of {s.pool_size}.
      </p>
      <div className="table-wrap">
        <table aria-label={`${s.pool} answers by choice`}>
          <thead>
            <tr>
              <th>Choice</th>
              <th>Answers</th>
              <th>Mean net R</th>
            </tr>
          </thead>
          <tbody>
            {["skip", "1", "2", "3"].map((c) => (
              <tr key={c}>
                <td>{c === "skip" ? "Skip" : `${c} (${MULTIPLIER[c]}x size)`}</td>
                <td>{s.by_choice[c]?.count ?? 0}</td>
                <td>{r(s.by_choice[c]?.mean_r)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="metrics">
        <div className="metric">
          <span className="muted">Your picks, total</span>
          <b>{r(s.picks_r, 1)}</b>
          <small className="muted">{r(s.picks_r_per_signal)} / signal</small>
        </div>
        <div className="metric">
          <span className="muted">Take every signal</span>
          <b>{r(s.equal_r, 1)}</b>
          <small className="muted">{r(s.equal_r_per_signal)} / signal</small>
        </div>
      </div>
      <p className="muted hint">Picks: net R times your size (skip 0, 1 = 0.5x, 2 = 1x, 3 = 1.5x).</p>
      <b>Blind vs shown</b>
      <div className="table-wrap">
        <table aria-label={`${s.pool} blind against shown`}>
          <thead>
            <tr>
              <th>Answered with</th>
              <th>Answers</th>
              <th>Your picks / signal</th>
              <th>Take all / signal</th>
            </tr>
          </thead>
          <tbody>
            {(
              [
                ["Blind (stock and date hidden)", s.by_shown.blind],
                ["Shown", s.by_shown.shown],
              ] as const
            ).map(([name, part]) => (
              <tr key={name}>
                <td>{name}</td>
                <td>{part.answered}</td>
                <td>{r(part.picks_r_per_signal)}</td>
                <td>{r(part.equal_r_per_signal)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p>
        Trades of 5R or more: {s.big.total} shown, you took {s.big.taken} and skipped {s.big.skipped}. Losing trades:{" "}
        {s.losers.total} shown, you took {s.losers.taken} and skipped {s.losers.skipped}.
      </p>
    </div>
  );
}

function Answered({ rows, onOpen }: { rows: PracticeAnswered[]; onOpen: (row: PracticeAnswered) => void }) {
  if (!rows.length) return <p className="muted">Nothing answered yet.</p>;
  return (
    <div className="table-wrap">
      <table aria-label="Your answered signals">
        <thead>
          <tr>
            <th>Answered</th>
            <th>Pool</th>
            <th>Stock</th>
            <th>Setup</th>
            <th>Pick</th>
            <th>Net R</th>
            <th>Shown</th>
            <th>Note</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((a) => (
            <tr key={a.signal_id} className="clickable" tabIndex={0} onClick={() => onOpen(a)} onKeyDown={(e) => e.key === "Enter" && onOpen(a)}>
              <td>{a.answered}</td>
              <td>{a.pool}</td>
              <td>{a.ticker}</td>
              <td>{a.setup_name}</td>
              <td>{choiceName(a.choice)}</td>
              <td className={a.net_r >= 0 ? "up" : "down"}>{r(a.net_r)}</td>
              <td>{a.shown ? "shown" : "blind"}</td>
              <td className="note-cell">{a.note}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Practice() {
  const phone = useMedia(PHONE);
  const [state, setState] = useState<PracticeState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pool, setPool] = useState("practice");
  const [shownBy, setShownBy] = useState<Record<string, boolean>>({ practice: true, exam: false });
  const [lines, setLines] = useState<string[]>(DEFAULT_LINES);
  const [sid, setSid] = useState<string | null | undefined>(undefined); // undefined: not picked yet
  const [sig, setSig] = useState<PracticeSignal | null>(null);
  const [note, setNote] = useState("");
  const [noteMsg, setNoteMsg] = useState<string | null>(null);
  const [answers, setAnswers] = useState<PracticeAnswered[]>([]);
  const [review, setReview] = useState<PracticeAnswered | null>(null);
  const [reviewSig, setReviewSig] = useState<PracticeSignal | null>(null);
  const [statsPool, setStatsPool] = useState("practice");
  const [busy, setBusy] = useState(false);
  const menu = usePopover();
  const shown = shownBy[pool] ?? pool === "practice";

  const reloadNumbers = useCallback(
    () =>
      Promise.all([api.practice(), api.practiceAnswers()]).then(
        ([s, a]) => {
          setState(s);
          setAnswers(a);
        },
        (e: Error) => setError(e.message),
      ),
    [],
  );
  useEffect(() => {
    reloadNumbers();
  }, [reloadNumbers]);

  // A new signal for the pool
  const next = useCallback(
    (p: string) => {
      setSig(null);
      setNote("");
      setNoteMsg(null);
      setSid(undefined);
      api.practiceNext(p).then(
        (n) => setSid(n.signal_id),
        (e: Error) => setError(e.message),
      );
    },
    [],
  );
  useEffect(() => {
    if (state?.available) next(pool);
  }, [state?.available, pool, next]);

  // The chart follows the signal, the stock-and-date switch and the indicator lines
  useEffect(() => {
    if (!sid) return;
    let live = true;
    api.practiceSignal(sid, shown, lines).then(
      (s) => live && setSig(s),
      (e: Error) => live && setError(e.message),
    );
    return () => {
      live = false;
    };
  }, [sid, shown, lines]);
  useEffect(() => {
    if (!review) return setReviewSig(null);
    let live = true;
    api.practiceSignal(review.signal_id, review.shown, lines).then(
      (s) => live && setReviewSig(s),
      (e: Error) => live && setError(e.message),
    );
    return () => {
      live = false;
    };
  }, [review, lines]);

  const answer = async (choice: string) => {
    if (!sig || busy) return;
    setBusy(true);
    try {
      await api.practiceAnswer({ signal_id: sig.signal_id, pool, choice, note, shown });
      const fresh = await api.practiceSignal(sig.signal_id, shown, lines);
      setSig(fresh);
      setNote(fresh.result?.note ?? note);
      await reloadNumbers();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const saveNote = (id: string, text: string) =>
    api.practiceNote(id, text).then(
      () => {
        setNoteMsg("Note saved.");
        reloadNumbers();
      },
      (e: Error) => setNoteMsg(`Error: ${e.message}`),
    );

  if (error && !state) return <p className="error">{error}</p>;
  if (!state) return <p className="muted">Loading…</p>;
  if (!state.available) {
    return (
      <div>
        <h1 className="sr-only">Practice</h1>
        <p className="muted">No practice data yet. It is exported to the data repo (data/research/practice).</p>
      </div>
    );
  }
  const done = sig?.answered ?? false;
  const stats = state.stats[statsPool];
  const picker = (
    <div className="pr-tools">
      <Segmented
        label="Pool"
        options={state.pools.map((p) => [p.id, p.label] as const)}
        value={pool}
        onPick={(p) => setPool(p)}
      />
      <label className="check">
        <input
          type="checkbox"
          checked={shown}
          onChange={(e) => setShownBy({ ...shownBy, [pool]: e.target.checked })}
        />
        Show stock and date
      </label>
      <div className="popover-wrap" ref={menu.ref}>
        <button aria-expanded={menu.open} onClick={() => menu.setOpen(!menu.open)}>
          <Icon name="sliders" size={16} />
          Indicators
        </button>
        {menu.open && (
          <div className="popover left" role="dialog" aria-label="Indicators">
            <h4>Lines</h4>
            {state.lines.map((l) => (
              <label key={l} className="check settings-row" style={{ justifyContent: "flex-start" }}>
                <input
                  type="checkbox"
                  checked={lines.includes(l)}
                  onChange={(e) => setLines(e.target.checked ? [...lines, l] : lines.filter((x) => x !== l))}
                />
                {l}
              </label>
            ))}
            <p className="muted hint">MA200 needs 200 bars; the practice window has 130 before the entry.</p>
          </div>
        )}
      </div>
    </div>
  );

  return (
    <div className="practice">
      <h1 className="sr-only">Practice</h1>
      <p className="muted">
        A past signal: the chart up to the entry and the facts known then. Pick a size (Skip, 1, 2 or 3), see how it
        went, and check whether your picks beat taking all.
      </p>
      {picker}
      {pool === "exam" && (
        <p className="muted">
          Take the exam once you are ready: each signal is answered once and the result counts once. Practice first.
        </p>
      )}
      {error && <p className="error">{error}</p>}
      {sid === null && <p className="ok">Every signal in this pool is answered.</p>}
      {sid !== null && !sig && <p className="muted">Loading the signal…</p>}
      {sig && (
        <section className="card pr-card" aria-label="The signal">
          {sig.ticker && (
            <p className="pr-title">
              <b>{sig.ticker}</b>
            </p>
          )}
          <div className="pr-chart">
            <DrawChart data={sig.chart} height={phone ? 300 : 400} tool="none" markerText />
          </div>
          <p className="muted hint">
            Pan and zoom like the Chart. Before your answer only the sessions up to the entry are shown.
          </p>
          <Facts sig={sig} />
          <textarea
            aria-label="Note"
            rows={3}
            value={note}
            placeholder="Why this call? Saved with your answer; you can edit it afterwards."
            onChange={(e) => {
              setNote(e.target.value);
              setNoteMsg(null);
            }}
          />
          {!done ? (
            <div className="pr-buttons" role="group" aria-label="Your answer">
              {["skip", "1", "2", "3"].map((c) => (
                <button key={c} className="pr-answer" disabled={busy} onClick={() => answer(c)}>
                  {choiceName(c)}
                </button>
              ))}
            </div>
          ) : (
            <>
              <ResultLine sig={sig} />
              <div className="row">
                <button onClick={() => saveNote(sig.signal_id, note)}>Save note</button>
                {noteMsg && <span className={noteMsg.startsWith("Error") ? "error" : "ok"}>{noteMsg}</span>}
              </div>
              <button className="primary block pr-next" onClick={() => next(pool)}>
                Next
              </button>
            </>
          )}
        </section>
      )}

      <h3>Your numbers</h3>
      <TabRow
        label="Pool of the numbers"
        tabs={state.pools.map((p) => [p.id, p.label] as const)}
        value={statsPool}
        onPick={setStatsPool}
      />
      {stats && <StatsPanel s={stats} />}

      <h3>Your answered signals</h3>
      <Answered
        rows={answers}
        onOpen={setReview}
      />
      {review && reviewSig && (
        <section className="card pr-card" aria-label="An answered signal">
          <div className="row">
            <b>{review.ticker}</b>
            <span className="muted">{review.setup_name}</span>
            <span className="grow" />
            <button className="ghost icon-btn" aria-label="Close" onClick={() => setReview(null)}>
              <Icon name="x" />
            </button>
          </div>
          <ResultLine sig={reviewSig} />
          <div className="pr-chart">
            <DrawChart data={reviewSig.chart} height={phone ? 300 : 380} tool="none" markerText />
          </div>
          <Facts sig={reviewSig} />
          <ReviewNote key={review.signal_id} sig={reviewSig} onSave={saveNote} msg={noteMsg} />
        </section>
      )}
    </div>
  );
}

function ReviewNote({
  sig,
  onSave,
  msg,
}: {
  sig: PracticeSignal;
  onSave: (id: string, text: string) => void;
  msg: string | null;
}) {
  const [text, setText] = useState(sig.result?.note ?? "");
  return (
    <>
      <textarea aria-label="Review note" rows={3} value={text} onChange={(e) => setText(e.target.value)} />
      <div className="row">
        <button onClick={() => onSave(sig.signal_id, text)}>Save note</button>
        {msg && <span className={msg.startsWith("Error") ? "error" : "ok"}>{msg}</span>}
      </div>
    </>
  );
}
