// Your grade, notes, tags and screenshots for a scan hit or a closed trade (append-only in the
// data repo, like the Streamlit form). The grade is your call; code never grades a trade.
import { useEffect, useState } from "react";
import { api, type GradeNote } from "../api";

function asBase64(file: File): Promise<{ name: string; data: string }> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve({ name: file.name, data: String(reader.result) });
    reader.onerror = () => reject(reader.error ?? new Error("read failed"));
    reader.readAsDataURL(file);
  });
}

export function GradeForm({
  kind,
  refId,
  title,
  onSaved,
}: {
  kind: "signal" | "trade";
  refId: string;
  title: string;
  onSaved?: (note: GradeNote) => void;
}) {
  const [note, setNote] = useState<GradeNote | null>(null);
  const [grade, setGrade] = useState("");
  const [notes, setNotes] = useState("");
  const [tags, setTags] = useState("");
  const [sure, setSure] = useState<number | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    setMessage(null);
    api.grade(kind, refId).then(
      (n) => {
        setNote(n);
        setGrade(n.grade);
        setNotes(n.notes);
        setTags(n.tags);
        setSure(n.conviction);
      },
      (e: Error) => setMessage(`Error: ${e.message}`),
    );
  }, [kind, refId]);

  if (!note) return message ? <p className="error">{message}</p> : null;

  const save = async () => {
    try {
      const screenshots = await Promise.all(files.map(asBase64));
      const saved = await api.saveGrade(kind, refId, { grade, notes, tags, conviction: sure, screenshots });
      setNote(saved);
      setSure(saved.conviction);
      onSaved?.(saved);
      setFiles([]);
      setMessage(saved.message ?? "Saved.");
    } catch (e) {
      setMessage(`Error: ${(e as Error).message}`);
    }
  };

  return (
    <section className="card" aria-label="Grading form">
      <b>{title}</b>
      <div className="row" role="radiogroup" aria-label="Grade (your call)">
        {note.grades.map((g) => (
          <label key={g || "none"} className="check">
            <input type="radio" name={`grade-${refId}`} checked={grade === g} onChange={() => setGrade(g)} />
            {g || "none"}
          </label>
        ))}
      </div>
      <div className="row" role="radiogroup" aria-label="Conviction" title="1 = small, 2 = normal, 3 = high conviction. Optional; the Journal compares them.">
        <span className="muted">Conviction</span>
        {[null, ...(note.convictions ?? [1, 2, 3])].map((c) => (
          <label key={c ?? "none"} className="check">
            <input type="radio" name={`conviction-${refId}`} checked={sure === c} onChange={() => setSure(c)} />
            {c ?? "none"}
          </label>
        ))}
      </div>
      <textarea aria-label="Notes" rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} />
      <input
        aria-label="Tags (comma separated)"
        placeholder="Tags (comma separated)"
        value={tags}
        onChange={(e) => setTags(e.target.value)}
      />
      <input
        aria-label="Screenshots"
        type="file"
        accept=".png,.jpg,.jpeg"
        multiple
        onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
      />
      <button onClick={save}>Save</button>
      {message && <p className={message.startsWith("Error") ? "error" : "ok"}>{message}</p>}
      <div className="shots">
        {note.attachments.map((a) => (
          <img key={a} src={`/api/attachments/${a}`} alt={a.split("/").pop()} />
        ))}
      </div>
    </section>
  );
}
