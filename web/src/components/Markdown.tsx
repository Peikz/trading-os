// Markdown from the package or the data repo (rule texts, study write-ups, reports), rendered
// with marked and sanitized with DOMPurify before it reaches the page.
import DOMPurify from "dompurify";
import { marked } from "marked";
import { useMemo } from "react";

export function Markdown({ text }: { text: string }) {
  const html = useMemo(
    () => DOMPurify.sanitize(marked.parse(text, { async: false, gfm: true }) as string),
    [text],
  );
  return <div className="markdown" dangerouslySetInnerHTML={{ __html: html }} />;
}
