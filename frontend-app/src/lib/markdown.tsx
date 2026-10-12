import type { ReactNode } from "react";

export type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "list"; items: string[] }
  | { kind: "paragraph"; text: string };

/** Tiny markdown reader: headings, bullet lists, paragraphs. */
export function parseMarkdown(md: string): Block[] {
  const blocks: Block[] = [];
  let para: string[] = [];
  const flush = () => { if (para.length) { blocks.push({ kind: "paragraph", text: para.join(" ") }); para = []; } };
  for (const raw of md.replace(/\r\n/g, "\n").split("\n")) {
    const line = raw.trimEnd();
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    const li = /^\s*[-*]\s+(.*)$/.exec(line);
    if (h) { flush(); blocks.push({ kind: "heading", level: h[1].length, text: h[2] }); }
    else if (li) {
      flush();
      const last = blocks[blocks.length - 1];
      if (last?.kind === "list") last.items.push(li[1]); else blocks.push({ kind: "list", items: [li[1]] });
    } else if (!line.trim()) flush();
    else para.push(line.trim());
  }
  flush();
  return blocks;
}

/** Inline **bold** and *italic* (also _italic_), built as elements so text is never injected as HTML. */
export function renderInline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /\*\*([^*]+)\*\*|\*([^*]+)\*|\b_([^_]+)_\b/g;
  let last = 0; let m: RegExpExecArray | null; let key = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    out.push(m[1] !== undefined ? <strong key={key++}>{m[1]}</strong> : <em key={key++}>{m[2] ?? m[3]}</em>);
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function Markdown({ text }: { text: string }) {
  return (
    <div className="markdown">
      {parseMarkdown(text).map((b, i) => {
        if (b.kind === "heading") {
          const Tag = `h${Math.min(6, b.level + 2)}` as "h3";
          return <Tag key={i}>{renderInline(b.text)}</Tag>;
        }
        if (b.kind === "list") return <ul key={i}>{b.items.map((it, j) => <li key={j}>{renderInline(it)}</li>)}</ul>;
        return <p key={i}>{renderInline(b.text)}</p>;
      })}
    </div>
  );
}
