import type { Edit } from "../engine";

type Props = {
  partial: string;
  final: string;
  language: string;
  confidence: number;
  latencyMs: number;
  edits: Edit[];
};

const ANNOTATION: Record<string, string> = {
  spoken_command: "symbol",
  filler_removed: "filler",
  correction: "correction",
  formatting: "rewrite",
};

export function TranscriptStage({ partial, final, language, confidence, latencyMs, edits }: Props) {
  const body = partial || final;
  const streaming = Boolean(partial);
  const meta = [
    language.replace("-", " "),
    confidence ? `${Math.round(confidence * 100)}%` : null,
    latencyMs ? `${latencyMs} ms` : null,
  ].filter(Boolean);

  return (
    <div className="flex min-w-0 flex-col">
      <div className="flex items-baseline gap-3">
        <span className="eyebrow">03</span>
        <span className="eyebrow">transcript</span>
        <span className="ml-auto font-mono text-[9.5px] tracking-[0.14em] text-mute">
          {meta.join("  ·  ")}
        </span>
      </div>

      <div className="mt-7 min-h-[2.2em]">
        {body ? (
          <p
            aria-live="polite"
            className={`font-serif text-[clamp(2rem,4.4vw,3.9rem)] leading-[1.02] tracking-[-0.015em] text-pretty ${
              streaming
                ? "text-white/55"
                : "bg-gradient-to-b from-white via-white to-white/60 bg-clip-text text-transparent"
            }`}
          >
            {body}
            {streaming ? <span className="caret" aria-hidden="true" /> : null}
          </p>
        ) : (
          <p className="font-serif text-[clamp(2rem,4.4vw,3.9rem)] leading-[1.02] tracking-[-0.015em] text-white/22 italic">
            Say something.
          </p>
        )}
      </div>

      <div className="mt-8 flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-white/8 pt-4">
        <span className="eyebrow">
          {streaming ? "streaming" : final ? "committed" : "awaiting voice"}
        </span>
        {edits.length ? (
          <span className="flex flex-wrap gap-x-4 gap-y-1">
            {edits.map((edit, index) => (
              <span
                key={`${edit.type}-${index}`}
                className="font-mono text-[9.5px] tracking-[0.12em] text-body uppercase"
                title={
                  edit.source ? `"${edit.source}" → "${edit.replacement ?? ""}"` : undefined
                }
              >
                <span className="text-white/25">— </span>
                {ANNOTATION[edit.type] ?? edit.type}
              </span>
            ))}
          </span>
        ) : null}
        <span className="ml-auto font-mono text-[9.5px] tracking-[0.14em] text-mute">
          {final && !streaming ? final.split(/\s+/).filter(Boolean).length + " words" : ""}
        </span>
      </div>
    </div>
  );
}
