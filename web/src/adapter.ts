/* The single seam between the FlowMini React UI and the Python BridgeAPI.
 *
 * The UI never invents transcripts. It renders whatever the BridgeAPI emits.
 * This adapter calls window.pywebview.api.MethodName() - no WebSocket, no ports,
 * pure in-process bridging. Works both in development and when packaged with
 * PyInstaller (the BridgeAPI methods are available in the pywebview window).
 *
 * IMPORTANT: The React side must be rendered inside a pywebview window that was
 * created with js_api=BridgeAPI (see app.py). The window exposes Python methods
 * as window.pywebview.api.{method}() which this adapter uses.
 */

import type { Edit, Settings, Status, Tag } from "./engine";

/* Types */

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
  attach: (listener: (event: FlowEvent) => void) => () => void;
  startPushToTalk: () => void;
  stopPushToTalk: () => void;
  setSetting: <K extends keyof Settings>(key: K, value: Settings[K]) => void;
  selfTest: () => void;
  refreshStats: () => void;
  undo: () => void;
};

/* BridgeAPI access */

type BridgeStatus = {
  status?: Status;
  model?: string;
  level?: number;
  active?: boolean;
  uptime?: number;
  partial_transcript?: string;
};

type BridgeConfig = {
  language?: string;
  stt_engine?: string;
  stt_model?: string;
  stt_device?: string;
  cleanup_mode?: Settings["cleanup"];
  style_preset?: Settings["style"];
  show_hud?: boolean;
  translate_to_english?: boolean;
  start_with_windows?: boolean;
  developer_mode?: boolean;
  mic_device?: string;
  vad_enabled?: boolean;
  app_profiles_enabled?: boolean;
  detect_language?: boolean;
  auto_learn?: boolean;
};

interface BridgeApi {
  get_status(): BridgeStatus | Promise<BridgeStatus>;
  get_config(): BridgeConfig | Promise<BridgeConfig>;
  get_learn_stats(): unknown;
  get_stats(): unknown;
  toggle_recording(): unknown;
  set_setting(key: string, value: unknown): unknown;
  change_model(model: string): unknown;
  get_transcription_history(): unknown;
  minimize_to_tray(): unknown;
  close_app(): unknown;
  initialize(): unknown;
  self_test(): unknown;
  undo_last(): unknown;
  refresh_stats(): unknown;
}

const CONFIG_KEY: Record<string, string> = {
  cleanup: "cleanup_mode",
  style: "style_preset",
  translate: "translate_to_english",
  developer: "developer_mode",
  vad: "vad_enabled",
  profiles: "app_profiles_enabled",
  autostart: "start_with_windows",
  hud: "show_hud",
  detect_language: "detect_language",
  auto_learn: "auto_learn",
};

function bridgeApi(): BridgeApi | null {
  const win = (window as unknown as { pywebview?: { api?: BridgeApi } }).pywebview;
  return win?.api ?? null;
}

function call(method: keyof BridgeApi, ...args: unknown[]): unknown {
  const api = bridgeApi();
  if (!api) return null;
  const fn = api[method] as unknown as (...a: unknown[]) => unknown;
  if (typeof fn !== "function") return null;
  try {
    return fn.apply(api, args);
  } catch (e) {
    console.warn("BridgeAPI." + String(method) + "() error:", e);
    return null;
  }
}

/* In-process BridgeAPI adapter */

export function createBridgeAPIIAdapter(): FlowMiniAdapter {
  let listener: ((event: FlowEvent) => void) | null = null;
  let timer: number | undefined;
  let lastStatus = "";
  let lastLevel = -1;
  let lastPartial = "";

  const emit = (event: FlowEvent) => listener?.(event);

  const poll = async (): Promise<void> => {
    const api = bridgeApi();
    if (!api) return;

    try {
      const status = await api.get_status();
      if (status) {
        if (status.status && status.status !== lastStatus) {
          lastStatus = status.status;
          emit({ type: "status", status: status.status });
        }
        const level = Number(status.level ?? 0);
        if (Math.abs(level - lastLevel) > 0.01) {
          lastLevel = level;
          emit({ type: "level", level });
        }
        const partial = String(status.partial_transcript ?? "");
        if (partial !== lastPartial) {
          lastPartial = partial;
          if (partial) emit({ type: "partial", text: partial });
        }
      }
    } catch {
      /* bridge not ready yet */
    }

    try {
      const cfg = await api.get_config();
      if (cfg) {
        emit({
          type: "settings",
          patch: {
            language: cfg.language ?? "en-US",
            cleanup: cfg.cleanup_mode ?? "light",
            style: cfg.style_preset ?? "casual",
            translate: Boolean(cfg.translate_to_english),
            developer: Boolean(cfg.developer_mode),
            vad: Boolean(cfg.vad_enabled),
            stt_model: cfg.stt_model ?? "large-v3-turbo",
            stt_device: cfg.stt_device ?? "auto",
            mic_device: cfg.mic_device ?? "",
            profiles: Boolean(cfg.app_profiles_enabled),
            autostart: Boolean(cfg.start_with_windows),
            hud: Boolean(cfg.show_hud),
            detect_language: Boolean(cfg.detect_language),
            auto_learn: Boolean(cfg.auto_learn),
          },
        });
      }
    } catch {
      /* ignore */
    }
  };

  return {
    attach(next) {
      listener = next;
      emit({ type: "connected", value: true });
      call("initialize");
      void poll();
      timer = window.setInterval(() => void poll(), 250);
      return () => {
        listener = null;
        if (timer !== undefined) window.clearInterval(timer);
        timer = undefined;
      };
    },

    startPushToTalk() {
      call("toggle_recording");
    },

    stopPushToTalk() {
      call("toggle_recording");
    },

    setSetting(key, value) {
      const configKey = CONFIG_KEY[key] ?? key;
      call("set_setting", configKey, value);
      emit({ type: "settings", patch: { [key]: value } as Partial<Settings> });
    },

    selfTest() {
      call("self_test");
      emit({
        type: "log",
        text: "Self-test started — check the tray log for results.",
        tag: "dim",
      });
    },

    refreshStats() {
      void poll();
      const stats = call("refresh_stats");
      if (stats && typeof stats === "object") {
        emit({ type: "log", text: "Stats refreshed from engine", tag: "ok" });
      }
    },

    undo() {
      const res = call("undo_last");
      if (res && (res as { status?: string }).status === "ok") {
        emit({ type: "log", text: "Undid transform — raw transcript pasted", tag: "warn" });
      } else {
        emit({ type: "log", text: "Nothing to undo yet", tag: "warn" });
      }
    },
  };
}

/* Unconnected adapter (no engine) */

const NOT_WIRED = "Not wired to an engine.";

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
      emit({ type: "log", text: String(key) + " -> " + String(value) + " - local UI state", tag: "dim" });
    },
    selfTest() {
      emit({ type: "log", text: "Self-test belongs to the engine - connect an adapter.", tag: "warn" });
    },
    refreshStats() {
      emit({ type: "log", text: "Session stats come from the engine - connect an adapter.", tag: "dim" });
    },
    undo() {
      emit({ type: "log", text: "Undo needs the raw transcript from the engine.", tag: "warn" });
    },
  };
}

/* Preview adapter (design review, synthetic states) */

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
      emit({ type: "log", text: "Preview adapter attached - synthetic states for design review.", tag: "warn" });
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
      emit({ type: "log", text: "preview - recording (no microphone in use)", tag: "dim" });
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
      emit({ type: "log", text: "preview - " + String(key) + " -> " + String(value), tag: "dim" });
    },
    selfTest() {
      emit({ type: "log", text: "Self-test belongs to the engine - connect an adapter.", tag: "warn" });
    },
    refreshStats() {
      emit({ type: "log", text: "Session stats come from the engine - connect an adapter.", tag: "dim" });
    },
    undo() {
      emit({ type: "log", text: "Undo needs the raw transcript from the engine.", tag: "warn" });
    },
  };
}

/* Legacy: WebSocket adapter (kept for reference, not used in pywebview mode) */

/*
export function createSocketAdapter(url = "ws://127.0.0.1:8765"): FlowMiniAdapter {
  let socket: WebSocket | null = null;
  let listener: ((event: FlowEvent) => void) | null = null;
  const send = (payload: unknown) => {
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(payload));
    }
  };

  return {
    attach(next) {
      listener = next;
      socket = new WebSocket(url);
      socket.onmessage = (message) => {
        try {
          listener?.(JSON.parse(message.data) as FlowEvent);
        } catch (err) {
          listener?.({ type: "error", message: "bad event frame" });
        }
      };
      socket.onopen = () => listener?.({ type: "connected", value: true });
      socket.onclose = () => listener?.({ type: "connected", value: false });
      socket.onerror = () => listener?.({ type: "error", message: "adapter connection failed" });
      return () => {
        socket?.close();
        socket = null;
      };
    },
    startPushToTalk: () => send({ cmd: "start" }),
    stopPushToTalk: () => send({ cmd: "stop" }),
    setSetting: (key, value) => send({ cmd: "setting", key, value }),
    selfTest: () => send({ cmd: "self_test" }),
    refreshStats: () => send({ cmd: "stats" }),
    undo: () => send({ cmd: "undo" }),
  };
}
*/
