// What the editor and the inline pieces need to know about the rest of the notebook: the tags in
// use (for `#` suggestions), the stocks (for `$`), the pages (for `[[`), and where a link goes.
import { createContext, useContext } from "react";
import { hrefFor } from "../routes";

export interface NbEnv {
  tags: string[];
  /** Stocks the notebook knows (notes, trades, tagged days) */
  tickers: string[];
  /** Every stock of the universe, for `$` suggestions (empty until loaded) */
  symbols: string[];
  pages: { slug: string; title: string }[];
}

export const NbEnvContext = createContext<NbEnv>({ tags: [], tickers: [], symbols: [], pages: [] });
export const useNbEnv = () => useContext(NbEnvContext);

/** A notebook address: `daily:<id>`, `day:<date>`, `trade:<id>`, `stock:<T>`, `page:<slug>`,
 *  `tag:<tag>`, `new:<title>` (a page that does not exist yet). */
export const noteHref = (p: string) => hrefFor("journal", "notes", { p });

export const DATE = /^\d{4}-\d{2}-\d{2}$/;

/** Where a [[wiki link]] goes: a stock, a day, a page by its title, or a new page. */
export function wikiTarget(title: string, pages: NbEnv["pages"]): string {
  if (/^[A-Z][A-Z0-9.-]{0,9}$/.test(title)) return `stock:${title}`;
  if (DATE.test(title)) return `day:${title}`;
  const page = pages.find((p) => p.title.toLowerCase() === title.toLowerCase());
  return page ? `page:${page.slug}` : `new:${title}`;
}
