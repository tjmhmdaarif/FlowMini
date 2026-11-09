import type { LogLine, Tag } from "../engine";

const TONE: Record<Tag, string> = {
  ok: "text-ok/90",
  warn: "text-warn/90",
  err: "text-bad/90",
  dim: "text-mute",
};

export function EventStream({ lines, partial }: { lines: LogLine[]; partial: string }) {
  const recent = lines.slice(-4).reverse();

  // Show live partial transcript at the top when actively listening/VAD mode
  const livePartial = partial.trim();

  return (
    <div className="min-w-0">
      {/* Live partial transcript banner — appears during VAD/recording */}
      {livePartial.length > 0 && (
        <div className="mt-2 p-2 rounded border-t border-crimson/60 border-b border-crimson/60 bg-crimson/5 text-crimson/90 font-mono text-[10px] overflow-x-auto">
          <span className="eyebrow">live</span>
          <span className="font-mono">{livePartial}</span>
        </div>
      )}

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
