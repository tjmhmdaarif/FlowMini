export type Status = "idle" | "recording" | "processing" | "vad" | "error";
export type Tag = "ok" | "warn" | "err" | "dim";
export type CleanupMode = "off" | "light" | "medium";
export type StylePreset = "formal" | "casual" | "very_casual" | "excited";

export type Edit = { type: string; source?: string; replacement?: string };

export type Settings = {
  language: string;
  cleanup: CleanupMode;
  style: StylePreset;
  translate: boolean;
  developer: boolean;
  vad: boolean;
  /** Day 8: local STT model / device (live streaming model). */
  stt_model: string;
  stt_device: string;
  mic_device: string;
};

export type LogLine = { id: number; text: string; tag: Tag };

export type State = {
  status: Status;
  level: number;
  partial: string;
  final: string;
  raw: string;
  language: string;
  confidence: number;
  edits: Edit[];
  latencyMs: number;
  sessions: number;
  words: number;
  settings: Settings;
  logs: LogLine[];
  connected: boolean;
  sheetOpen: boolean;
  canUndo: boolean;
};

export const STATUS_META: Record<Status, { label: string; hint: string; tone: string }> = {
  idle: {
    label: "IDLE",
    hint: "ready — press Ctrl+Alt+D or hit the disc",
    tone: "#38e08b",
  },
  recording: {
    label: "LISTENING",
    hint: "speak now — press again to finish the take",
    tone: "#ff3b4e",
  },
  processing: {
    label: "CLEANING",
    hint: "transcribing and running the cleanup pass",
    tone: "#ffb02e",
  },
  vad: {
    label: "ARMED",
    hint: "hands-free — starts on speech, stops on silence",
    tone: "#5aa9ff",
  },
  error: {
    label: "FAULT",
    hint: "adapter reported an error — see the log",
    tone: "#ff6b7d",
  },
};

export const LANGUAGES: { code: string; label: string }[] = [
  { code: "en-US", label: "English (US)" },
  { code: "en-GB", label: "English (UK)" },
  { code: "hi-IN", label: "Hindi" },
  { code: "bn-IN", label: "Bengali" },
  { code: "ta-IN", label: "Tamil" },
  { code: "te-IN", label: "Telugu" },
  { code: "mr-IN", label: "Marathi" },
  { code: "gu-IN", label: "Gujarati" },
  { code: "kn-IN", label: "Kannada" },
  { code: "ml-IN", label: "Malayalam" },
  { code: "pa-IN", label: "Punjabi" },
  { code: "ur-PK", label: "Urdu" },
  { code: "ne-NP", label: "Nepali" },
  { code: "es-ES", label: "Spanish" },
  { code: "fr-FR", label: "French" },
  { code: "de-DE", label: "German" },
  { code: "ja-JP", label: "Japanese" },
  { code: "ko-KR", label: "Korean" },
  { code: "zh-CN", label: "Chinese (Simplified)" },
  { code: "ar-SA", label: "Arabic" },
];

let seq = 1;

export const initialState: State = {
  status: "idle",
  level: 0,
  partial: "",
  final: "",
  raw: "",
  language: "en-US",
  confidence: 0,
  edits: [],
  latencyMs: 0,
  sessions: 0,
  words: 0,
  settings: {
    language: "en-US",
    cleanup: "light",
    style: "casual",
    translate: true,
    developer: false,
    vad: false,
    stt_model: "large-v3-turbo",
    stt_device: "auto",
    mic_device: "",
  },
  logs: [],
  connected: false,
  sheetOpen: false,
  canUndo: false,
};

export type Action =
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
  | { type: "sheet"; open: boolean }
  | { type: "reset" };

const withLog = (logs: LogLine[], text: string, tag: Tag = "dim"): LogLine[] =>
  [...logs, { id: seq++, text, tag }].slice(-120);

export function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "status":
      return {
        ...state,
        status: action.status,
        logs: withLog(
          state.logs,
          `state → ${STATUS_META[action.status].label.toLowerCase()}`,
          action.status === "error" ? "err" : "dim",
        ),
      };

    case "level":
      return { ...state, level: Math.max(0, Math.min(1, action.level)) };

    case "partial":
      return { ...state, partial: action.text };

    case "result": {
      const words = action.final.split(/\s+/).filter(Boolean).length;
      return {
        ...state,
        status: state.settings.vad ? "vad" : "idle",
        partial: "",
        final: action.final,
        raw: action.raw,
        language: action.language ?? state.language,
        confidence: action.confidence ?? 0,
        edits: action.edits ?? [],
        latencyMs: action.latencyMs ?? 0,
        sessions: state.sessions + 1,
        words: state.words + words,
        canUndo: action.raw.trim() !== action.final.trim(),
        logs: withLog(
          state.logs,
          `${words} words · ${action.latencyMs ?? 0} ms · ${(action.edits ?? []).length} edit(s)`,
          "ok",
        ),
      };
    }

    case "undo":
      return {
        ...state,
        final: action.text,
        edits: [],
        canUndo: false,
        logs: withLog(state.logs, "raw transcript restored", "warn"),
      };

    case "log":
      return { ...state, logs: withLog(state.logs, action.text, action.tag ?? "dim") };

    case "settings":
      return {
        ...state,
        settings: { ...state.settings, ...action.patch },
        status:
          action.patch.vad !== undefined && state.status === "idle"
            ? action.patch.vad
              ? "vad"
              : "idle"
            : state.status,
      };

    case "connected":
      return {
        ...state,
        connected: action.value,
        logs: withLog(
          state.logs,
          action.value ? "adapter attached" : "no adapter attached",
          action.value ? "ok" : "warn",
        ),
      };

    case "sheet":
      return { ...state, sheetOpen: action.open };

    case "reset":
      return {
        ...initialState,
        settings: state.settings,
        logs: withLog(state.logs, "preview data cleared", "dim"),
        sessions: state.sessions,
        words: state.words,
      };

    default:
      return state;
  }
}
