/* The single seam between this front end and your engine.
 *
 * The UI never invents transcripts. It renders whatever an adapter emits.
 * Implement these six methods however you like (WebSocket, Tauri IPC,
 * file bridge, local HTTP, mock) and pass your adapter to <App adapter={...} />.
 * The default export is deliberately inert.
 */

import type { Edit, Settings, Status, Tag } from "./engine";

export type FlowEvent =
  | { type: "status"; status: Status }
  | { type: "level"; level: number }
  | { type: "partial"; text: string }
  | {
      type: "result";
      raw: string;
      final: string;
      language?: string;
      confidence?: number;
      edits?: Edit[];
      latencyMs?: number;
    }
  | { type: "undo"; text: string }
  | { type: "log"; text: string; tag?: Tag }
  | { type: "settings"; patch: Partial<Settings> }
  | { type: "connected"; value: boolean }
  | { type: "error"; message: string };

export type FlowMiniAdapter = {
  /** Subscribe to engine events. Return an unsubscribe function. */
  attach: (listener: (event: FlowEvent) => void) => () => void;
  startPushToTalk: () => void;
  stopPushToTalk: () => void;
  setSetting: <K extends keyof Settings>(key: K, value: Settings[K]) => void;
  selfTest: () => void;
  refreshStats: () => void;
  undo: () => void;
};

const NOT_WIRED =
  "No dictation source attached — implement FlowMiniAdapter (src/adapter.ts) and pass it to App.";

/** Inert adapter: settings are local UI state, speech actions go nowhere. */
export function createUnconnectedAdapter(): FlowMiniAdapter {
  let listener: ((event: FlowEvent) => void) | null = null;
  const emit = (event: FlowEvent) => listener?.(event);

  return {
    attach(next) {
      listener = next;
      emit({ type: "connected", value: false });
      return () => {
        listener = null;
      };
    },
    startPushToTalk() {
      emit({ type: "log", text: NOT_WIRED, tag: "warn" });
    },
    stopPushToTalk() {
      emit({ type: "log", text: NOT_WIRED, tag: "warn" });
    },
    setSetting(key, value) {
      emit({ type: "settings", patch: { [key]: value } as Partial<Settings> });
      emit({ type: "log", text: `${String(key)} → ${String(value)} · local UI state`, tag: "dim" });
    },
    selfTest() {
      emit({ type: "log", text: "Self-test belongs to the engine — connect an adapter.", tag: "warn" });
    },
    refreshStats() {
      emit({ type: "log", text: "Session stats come from the engine — connect an adapter.", tag: "dim" });
    },
    undo() {
      emit({ type: "log", text: "Undo needs the raw transcript from the engine.", tag: "warn" });
    },
  };
}

/* ---------------------------------------------------------------- preview --
 * Explicit, opt-in synthetic adapter for design review. It is only created
 * when the Preview switch is on, and every line it logs says "preview".
 */

type Sample = {
  raw: string;
  final: string;
  language: string;
  confidence: number;
  edits: Edit[];
  latencyMs: number;
};

const SAMPLES: Sample[] = [
  {
    raw: "um let's fix the the parser no the tokenizer",
    final: "Let's fix the tokenizer.",
    language: "en",
    confidence: 0.97,
    edits: [{ type: "filler_removed", source: "um" }],
    latencyMs: 1180,
  },
  {
    raw: "open square bracket x close square bracket",
    final: "[x]",
    language: "en",
    confidence: 0.95,
    edits: [{ type: "spoken_command", source: "open square bracket" }],
    latencyMs: 960,
  },
  {
    raw: "import os",
    final: "import os",
    language: "en",
    confidence: 0.94,
    edits: [],
    latencyMs: 1430,
  },
];

export function createPreviewAdapter(): FlowMiniAdapter {
  let listener: ((event: FlowEvent) => void) | null = null;
  let ticker: number | undefined;
  let finish: number | undefined;
  let recording = false;
  let take = 0;
  let lastRaw = "";

  const emit = (event: FlowEvent) => listener?.(event);
  const clear = () => {
    if (ticker) window.clearInterval(ticker);
    if (finish) window.clearTimeout(finish);
    ticker = undefined;
    finish = undefined;
  };

  return {
    attach(next) {
      listener = next;
      emit({ type: "connected", value: true });
      emit({ type: "log", text: "Preview adapter attached — synthetic states for design review.", tag: "warn" });
      return () => {
        listener = null;
        clear();
      };
    },
    startPushToTalk() {
      if (recording) return;
      recording = true;
      const sample = SAMPLES[take % SAMPLES.length];
      const words = sample.raw.split(" ");
      emit({ type: "status", status: "recording" });
      emit({ type: "partial", text: "" });
      emit({ type: "log", text: "preview · recording (no microphone in use)", tag: "dim" });
      let step = 0;
      ticker = window.setInterval(() => {
        step += 1;
        emit({ type: "level", level: 0.3 + Math.random() * 0.65 });
        const shown = Math.min(words.length, Math.ceil((step / 6) * words.length));
        emit({ type: "partial", text: words.slice(0, shown).join(" ") });
      }, 380);
    },
    stopPushToTalk() {
      if (!recording) return;
      recording = false;
      clear();
      const sample = SAMPLES[take % SAMPLES.length];
      lastRaw = sample.raw;
      emit({ type: "status", status: "processing" });
      emit({ type: "level", level: 0 });
      finish = window.setTimeout(() => {
        emit({
          type: "result",
          raw: sample.raw,
          final: sample.final,
          language: sample.language,
          confidence: sample.confidence,
          edits: sample.edits,
          latencyMs: sample.latencyMs,
        });
        emit({ type: "status", status: "idle" });
        take += 1;
      }, 900);
    },
    setSetting(key, value) {
      emit({ type: "settings", patch: { [key]: value } as Partial<Settings> });
      emit({ type: "log", text: `preview · ${String(key)} → ${String(value)}`, tag: "dim" });
    },
    selfTest() {
      emit({ type: "log", text: "preview · self-test is a no-op (no engine attached)", tag: "dim" });
    },
    refreshStats() {
      emit({ type: "log", text: "preview · stats are simulated", tag: "dim" });
    },
    undo() {
      if (!lastRaw) return;
      emit({ type: "undo", text: lastRaw });
      emit({ type: "log", text: "preview · raw transcript restored", tag: "warn" });
    },
  };
}
