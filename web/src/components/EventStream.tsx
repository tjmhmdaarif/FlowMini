import type { LogLine, Tag } from "../engine";

const TONE: Record<Tag, string> = {
  ok: "text-ok/90",
  warn: "text-warn/90",
  err: "text-bad/90",
  dim: "text-mute",
};

export function EventStream({ lines }: { lines: LogLine[] }) {
  const recent = lines.slice(-4).reverse();

  return (
    <div className="min-w-0">
      <div className="flex items-baseline gap-3">
        <span className="eyebrow">04</span>
        <span className="eyebrow">event stream</span>
        <span className="ml-auto font-mono text-[9.5px] tracking-[0.14em] text-mute">
          {lines.length} entries
        </span>
      </div>
      <ul className="mt-3 space-y-[3px]">
        {recent.length ? (
          recent.map((line, index) => (
            <li
              key={line.id}
              className="flex items-baseline gap-3 font-mono text-[10.5px] leading-relaxed"
            >
              <span className="w-3 shrink-0 text-right text-white/15 tabular-nums">
                {String(lines.length - index).padStart(2, "0")}
              </span>
              <span className={`truncate ${TONE[line.tag]}`}>{line.text}</span>
            </li>
          ))
        ) : (
          <li className="font-mono text-[10.5px] text-mute">
            no adapter events yet — see src/adapter.ts
          </li>
        )}
      </ul>
    </div>
  );
}
