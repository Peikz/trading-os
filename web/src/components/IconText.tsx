// The package marks some facts with coloured emoji (the run grid's ✅ / ❌, the market lines'
// 🟢 / 🔴, the heat table's ✅ held). On the page each becomes a small coloured dot with the
// same meaning, so no emoji stands in for an icon; other pictographs are dropped.
const MARKS: Record<string, [string, string]> = {
  "🟢": ["green", "up"],
  "✅": ["green", "yes"],
  "🟡": ["amber", "caution"],
  "🔴": ["red", "down"],
  "❌": ["red", "no"],
  "⏳": ["", "not due yet"],
};
const SPLIT = /(🟢|🟡|🔴|✅|❌|⏳)️?/u;

export const hasMarks = (text: string) => SPLIT.test(text);

export function IconText({ text }: { text: string }) {
  const parts = text.split(SPLIT);
  return (
    <>
      {parts.map((p, i) =>
        i % 2 ? (
          <span key={i} className={`dot inline ${MARKS[p]?.[0] ?? ""}`} role="img" aria-label={MARKS[p]?.[1] ?? ""} />
        ) : (
          p.replace(/[\p{Extended_Pictographic}️]/gu, "")
        ),
      )}
    </>
  );
}
