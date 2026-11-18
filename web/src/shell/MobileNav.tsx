// The phone's bottom bar: Today, Chart, Screener, Market and More. More is a sheet with every
// other page: the Journal's and the Lab's tabs. Safe-area padding at the bottom (styles.css).
import { useEffect, useState } from "react";
import { chartHref, useActive } from "./active";
import { hrefFor, PHONE_TABS, PLACES, type Place, TABS } from "../routes";
import { Icon } from "../ui/Icon";

const MORE: Place[] = PLACES.map((p) => p.id).filter((id) => !PHONE_TABS.includes(id));

export function MobileNav({ place }: { place: Place }) {
  const [more, setMore] = useState(false);
  const active = useActive();
  useEffect(() => setMore(false), [place]);
  useEffect(() => {
    if (!more) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setMore(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [more]);
  return (
    <>
      <nav className="tabbar" aria-label="Places (phone)">
        {PHONE_TABS.map((id) => {
          const p = PLACES.find((x) => x.id === id)!;
          return (
            <a
              key={id}
              href={id === "chart" ? chartHref(active) : hrefFor(id)}
              aria-current={id === place ? "page" : undefined}
            >
              <Icon name={p.icon} size={22} />
              {p.label}
            </a>
          );
        })}
        <button
          className={`more-btn${MORE.includes(place) ? " current" : ""}`}
          aria-expanded={more}
          aria-haspopup="dialog"
          onClick={() => setMore((m) => !m)}
        >
          <Icon name="more" size={22} />
          More
        </button>
      </nav>
      {more && (
        <div
          className="more-back"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setMore(false);
          }}
        >
          <div className="more-sheet" role="dialog" aria-label="More pages">
            {MORE.map((id) => {
              const p = PLACES.find((x) => x.id === id)!;
              return (
                <section key={id}>
                  <div className="section-label">
                    <a href={hrefFor(id)} onClick={() => setMore(false)}>
                      {p.label}
                    </a>
                  </div>
                  <ul>
                    {TABS[id].map(([tab, text]) => (
                      <li key={tab}>
                        <a href={hrefFor(id, tab)} onClick={() => setMore(false)}>
                          {text}
                        </a>
                      </li>
                    ))}
                  </ul>
                </section>
              );
            })}
          </div>
        </div>
      )}
    </>
  );
}
