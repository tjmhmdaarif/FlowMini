export type EngineStatus =
  | "idle"
  | "recording"
  | "processing"
  | "pasted"
  | "vad";

export type CleanupMode = "off" | "light" | "medium";
export type StylePreset = "formal" | "casual" | "very_casual" | "excited";
export type LogLevel = "ok" | "warn" | "err" | "dim";

export type LogLine = {
  id: number;
  t: string;
  level: LogLevel;
  text: string;
};

export type Settings = {
  language: string;
  translateToEnglish: boolean;
  cleanupMode: CleanupMode;
  stylePreset: StylePreset;
  developerMode: boolean;
  profilesEnabled: boolean;
  autostart: boolean;
  showHud: boolean;
  vadArmed: boolean;
};

export type EngineState = {
  status: EngineStatus;
  modeLabel: string;
  transcript: string;
  heard: string;
  canUndo: boolean;
  profile: "code" | "mail" | null;
  level: number;
  settings: Settings;
  log: LogLine[];
  stats: string;
  hudVisible: boolean;
};

export const LANGUAGES = [
  "English (US)",
  "English (UK)",
  "Hindi",
  "Kannada",
  "Spanish",
  "French",
  "German",
  "Japanese",
] as const;

const SAMPLES: { clean: string; heard: string; profile: "code" | "mail" | null }[] = [
  {
    clean: "Let's fix the tokenizer.",
    heard: "heard (en · 97%): um let's fix the the parser no the tokenizer",
    profile: null,
  },
  {
    clean: "import os",
    heard: "heard (en · 94%): import os",
    profile: "code",
  },
  {
    clean: "Please send the agenda before noon.",
    heard: "heard (en · 96%): please send the agenda before noon",
    profile: "mail",
  },
];

let logSeq = 1;

export function nowStamp() {
  return new Date().toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

export function line(level: LogLevel, text: string): LogLine {
  return { id: logSeq++, t: nowStamp(), level, text };
}

export const initialState: EngineState = {
  status: "idle",
  modeLabel: "push-to-talk",
  transcript: "nothing dictated yet",
  heard: "",
  canUndo: false,
  profile: null,
  level: 0.08,
  settings: {
    language: "English (US)",
    translateToEnglish: true,
    cleanupMode: "medium",
    stylePreset: "casual",
    developerMode: false,
    profilesEnabled: true,
    autostart: true,
    showHud: true,
    vadArmed: false,
  },
  log: [
    line("ok", "UI shell ready. Python engine is not wired yet."),
    line("dim", "Click the disc or press Ctrl+Alt+D to demo a take."),
    line("ok", "Hotkey chips match the desktop app."),
  ],
  stats: "demo  4 takes  61 words  1.4s median",
  hudVisible: false,
};

export type Action =
  | { type: "toggle_ptt" }
  | { type: "set_status"; status: EngineStatus }
  | { type: "finish"; sampleIndex: number }
  | { type: "set_level"; level: number }
  | { type: "patch_settings"; patch: Partial<Settings> }
  | { type: "log"; level: LogLevel; text: string }
  | { type: "undo" }
  | { type: "self_test" }
  | { type: "refresh_stats" }
  | { type: "hide_hud" };

export function reducer(state: EngineState, action: Action): EngineState {
  switch (action.type) {
    case "toggle_ptt": {
      if (state.status === "recording") {
        return {
          ...state,
          status: "processing",
          modeLabel: "cleanup",
          hudVisible: state.settings.showHud,
          log: [line("dim", "Hold ended. Running cleanup."), ...state.log].slice(0, 40),
        };
      }
      if (state.status === "processing") return state;
      return {
        ...state,
        status: "recording",
        modeLabel: "push-to-talk",
        hudVisible: state.settings.showHud,
        log: [line("ok", "Mic open. Speak, then click again to paste."), ...state.log].slice(0, 40),
      };
    }
    case "set_status":
      return { ...state, status: action.status };
    case "finish": {
      const sample = SAMPLES[action.sampleIndex % SAMPLES.length];
      const useCode = state.settings.developerMode || sample.profile === "code";
      const text = useCode && sample.profile === "code" ? sample.clean : sample.clean;
      const profile = state.settings.profilesEnabled ? sample.profile : null;
      return {
        ...state,
        status: "pasted",
        modeLabel: "pasted",
        transcript: text,
        heard: sample.heard,
        canUndo: true,
        profile,
        hudVisible: state.settings.showHud,
        log: [
          line("ok", `Pasted ${text.split(" ").length} words into the focused field.`),
          ...state.log,
        ].slice(0, 40),
      };
    }
    case "set_level":
      return { ...state, level: action.level };
    case "patch_settings": {
      const settings = { ...state.settings, ...action.patch };
      let extra: Partial<EngineState> = {};
      if (action.patch.vadArmed === true) {
        extra = {
          status: "vad",
          modeLabel: "hands-free",
        };
      }
      if (action.patch.vadArmed === false && state.status === "vad") {
        extra = { status: "idle", modeLabel: "push-to-talk" };
      }
      return {
        ...state,
        settings,
        ...extra,
        log: [
          line("dim", describePatch(action.patch)),
          ...state.log,
        ].slice(0, 40),
      };
    }
    case "log":
      return { ...state, log: [line(action.level, action.text), ...state.log].slice(0, 40) };
    case "undo":
      if (!state.canUndo) return state;
      return {
        ...state,
        transcript: state.heard.replace(/^heard[^:]*:\s*/i, "") || "raw take restored",
        canUndo: false,
        status: "idle",
        modeLabel: "push-to-talk",
        log: [line("warn", "Undo: restored the raw take."), ...state.log].slice(0, 40),
      };
    case "self_test":
      return {
        ...state,
        log: [
          line("ok", "Self-test: mic path, paste path, HUD timeout. All green (demo)."),
          ...state.log,
        ].slice(0, 40),
      };
    case "refresh_stats":
      return {
        ...state,
        stats: `demo  ${4 + (state.log.length % 5)} takes  ${58 + state.log.length} words  1.3s median`,
        log: [line("dim", "Session stats refreshed from local demo store."), ...state.log].slice(0, 40),
      };
    case "hide_hud":
      return { ...state, hudVisible: false };
    default:
      return state;
  }
}

function describePatch(patch: Partial<Settings>): string {
  const [key, value] = Object.entries(patch)[0] ?? ["setting", ""];
  return `${key} → ${String(value)}`;
}

export function statusTone(status: EngineStatus): string {
  switch (status) {
    case "recording":
      return "status-live";
    case "processing":
      return "status-wait";
    case "vad":
      return "status-info";
    case "pasted":
      return "status-ok";
    default:
      return "status-idle";
  }
}

export function statusWord(status: EngineStatus): string {
  switch (status) {
    case "recording":
      return "LIVE";
    case "processing":
      return "CLEANUP";
    case "vad":
      return "ARMED";
    case "pasted":
      return "PASTED";
    default:
      return "IDLE";
  }
}
