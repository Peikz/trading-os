// The broker export upload (.csv or .xlsx), as a dialog: pick the file, see what it holds (rows,
// columns found, new against already imported fills, the dates; nothing is written), then
// import. The same preview and the same append-only import as Streamlit (fills_import).
import { useEffect, useRef, useState } from "react";
import { api, type ImportPreview } from "../../api";
import { readBase64 } from "../../format";
import { Icon } from "../../ui/Icon";

export function ImportDialog({ onClose, onImported }: { onClose: () => void; onImported: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [seen, setSeen] = useState<ImportPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    box.current?.querySelector<HTMLElement>("input,button")?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const pick = async (f: File | null) => {
    setFile(f);
    setSeen(null);
    setDone(null);
    setError(null);
    if (!f) return;
    try {
      setSeen(await api.importPreview(f.name, await readBase64(f)));
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const run = async () => {
    if (!file) return;
    setBusy(true);
    try {
      const r = await api.importFills(file.name, await readBase64(file));
      setDone(r.message);
      setSeen(null);
      onImported();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const label = seen?.new ? `Import ${seen.new} new fills` : "Nothing new to import";
  return (
    <div
      className="dialog-back"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="dialog" role="dialog" aria-modal="true" aria-label="Import broker fills" ref={box}>
        <div className="dialog-head">
          <h2>Import broker fills</h2>
          <button className="ghost icon-btn" aria-label="Close" onClick={onClose}>
            <Icon name="x" />
          </button>
        </div>
        <p className="muted">
          Upload a .csv or .xlsx export. Column names are mapped in config/scans.yaml → journal.csv_columns. You
          see a preview first; nothing is written until you press Import.
        </p>
        <input
          aria-label="Fills export"
          type="file"
          accept=".csv,.xlsx"
          onChange={(e) => pick(e.target.files?.[0] ?? null)}
        />
        {seen && !seen.ok && <p className="error">{seen.error}</p>}
        {seen?.ok && (
          <>
            <ul className="preview-lines">
              {seen.lines.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
            <button className="primary block" disabled={!seen.new || busy} onClick={run}>
              {label}
            </button>
          </>
        )}
        {error && <p className="error">{error}</p>}
        {done && (
          <>
            <p className="ok pre">{done}</p>
            <button className="block" onClick={onClose}>
              Close
            </button>
          </>
        )}
      </div>
    </div>
  );
}
