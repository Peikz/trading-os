// Today's two controls, as in Streamlit's board: the view (Focus: queue, chart and plan; Grid: four
// charts at a time; List: one card per stock) and "Show", the list the view reads: today's queue,
// the pushed scans including the C setups, every scan hit, or one of your own watchlists.
import { Segmented, usePopover } from "../../ui/kit";
import { Icon } from "../../ui/Icon";
import { SCOPE_ALL, SCOPE_LABELS, SCOPE_LIST, SCOPE_PUSHED, SCOPE_TODAY, scopeLabel, type View, VIEWS } from "./model";

export function ViewToggle({ value, onPick }: { value: View; onPick: (v: View) => void }) {
  return <Segmented label="View" options={VIEWS.map((v) => [v, v] as const)} value={value} onPick={onPick} />;
}

export function ShowMenu({ value, lists, onPick }: { value: string; lists: string[]; onPick: (s: string) => void }) {
  const { open, setOpen, ref } = usePopover();
  const choose = (s: string) => {
    onPick(s);
    setOpen(false);
  };
  const scopes = [SCOPE_TODAY, SCOPE_PUSHED, SCOPE_ALL];
  return (
    <div className="popover-wrap" ref={ref}>
      <button className="fbtn" aria-expanded={open} aria-haspopup="listbox" onClick={() => setOpen(!open)}>
        <span className="flabel">Show</span>
        {scopeLabel(value)}
        <Icon name="down" size={14} />
      </button>
      {open && (
        <div className="popover left menu" role="listbox" aria-label="Show">
          {scopes.map((s) => (
            <button key={s} role="option" aria-selected={value === s} onClick={() => choose(s)}>
              <span>{SCOPE_LABELS[s]}</span>
            </button>
          ))}
          {lists.length > 0 && <div className="menu-label">Your watchlists</div>}
          {lists.map((n) => (
            <button key={n} role="option" aria-selected={value === SCOPE_LIST + n} onClick={() => choose(SCOPE_LIST + n)}>
              <Icon name="star" size={14} />
              <span>{n}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
