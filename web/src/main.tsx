import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

// FlowMini BridgeAPI adapter — in-process, zero-network.
// This adapter runs inside a pywebview window created with
// js_api=BridgeAPI. The BridgeAPI instance is available as
// window.pywebview.api and exposes Python methods that this adapter
// uses to forward events to the React UI.
//
// No WebSocket, no localhost ports — pure in-process binding via
// pywebview's JavaScript bridge. The UI never synthesises transcripts;
// the Python engine (AppCoreManager) is the single source of truth.

// Helper: call a BridgeAPI method and return its result.
// If the method returns a promise/thenable, we await it; otherwise
// we treat the return value as the result directly.
function callBridgeAPI(method: string, args: any[] = []): any {
  const win: any = (window as any).pywebview;
  if (!win || !win.api) {
    // Bridge not available yet — return a promise that resolves later
    return Promise.resolve(null);
  }
  const methodFn = win.api[method];
  if (!methodFn) {
    console.warn(`BridgeAPI method "${method}" not found`);
    return Promise.resolve(null);
  }
  try {
    return methodFn(...args);
  } catch (e) {
    console.error(`BridgeAPI.${method}() error:`, e);
    return null;
  }
}

// Poll the BridgeAPI for status updates at regular intervals.
// The returned state is dispatched to the React reducer.
function useBridgePolling(dispatch: any, deps: any[] = []) {
  const ref = { running: false };

  useEffect(() => {
    // Initial fetch
    const fetchState = async () => {
      try {
        const status = await callBridgeAPI("get_status");
        if (status && status.status) {
          dispatch({
            type: "status",
            status: status.status,
          });
          dispatch({
            type: "level",
            level: status.level ?? 0,
          });
          dispatch({
            type: "connected",
            value: status.status !== "error",
          });
        }
        // Fetch config on first poll
        if (!ref.configFetched) {
          ref.configFetched = true;
          const cfg = await callBridgeAPI("get_config");
          if (cfg) {
            dispatch({
              type: "settings",
              patch: {
                language: cfg.language ?? "en-US",
                cleanup: cfg.cleanup_mode ?? "light",
                style: cfg.style_preset ?? "casual",
                translate: cfg.translate_to_english ?? true,
                vad: cfg.vad_sensitivity !== undefined ? true : false,
                stt_model: cfg.stt_model ?? "large-v3-turbo",
                stt_device: cfg.stt_device ?? "auto",
                mic_device: cfg.mic_device ?? "",
              },
            });
          }
        }
      } catch (e) {
        // Bridge not ready yet — retry on next tick
        console.debug("BridgeAPI not ready yet, will retry:", e);
      }
    };

    fetchState();

    // Poll every 150ms for real-time updates
    const intervalId = setInterval(fetchState, 150);
    ref.intervalId = intervalId;
    ref.running = true;

    return () => {
      if (ref.intervalId) {
        clearInterval(ref.intervalId);
      }
      ref.running = false;
    };
  }, deps);
}

// Mount-time: request the Python backend to initialize.
// This starts AppCoreManager if it isn't running yet.
function useBridgeInitialize(dispatch: any) {
  useEffect(() => {
    // Request initialization from the Python backend
    // The BridgeAPI.initialize() method starts AppCoreManager
    // and returns readiness status.
    const init = async () => {
      try {
        const result = await callBridgeAPI("initialize");
        if (result && result.status === "initialized") {
          dispatch({
            type: "connected",
            value: true,
          });
          dispatch({
            type: "status",
            status: "idle",
          });
          dispatch({
            type: "level",
            level: 0,
          });
        }
      } catch (e) {
        console.error("Bridge initialization error:", e);
      }
    };

    init();

    // Cleanup on unmount
    return () => {
      // No explicit cleanup needed — the Python side handles shutdown
    };
  }, [dispatch]);
}

import { LANGUAGES, STT_MODELS, STT_DEVICES, MICS } from "./engine";
import { STATUS_META, initialState, reducer, type Action, type Settings } from "./engine";
import { Aperture } from "./components/Aperture";
import { EventStream } from "./components/EventStream";
import { SettingsSheet } from "./components/SettingsSheet";
import { TranscriptStage } from "./components/TranscriptStage";
import { useBridgePolling, useBridgeInitialize, callBridgeAPI } from "./bridgeAdapter";

function toAction(event: any): Action {
  if (!event) return { type: "status", status: "idle" };
  switch (event.type) {
    case "status":
      return { type: "status", status: event.status };
    case "level":
      return { type: "level", level: event.level };
    case "partial":
      return { type: "partial", text: event.text };
    case "result":
      return {
        type: "result",
        raw: event.raw,
        final: event.final,
        language: event.language,
        confidence: event.confidence,
        edits: event.edits,
        latencyMs: event.latencyMs,
      };
    case "undo":
      return { type: "undo", text: event.text };
    case "log":
      return { type: "log", text: event.text, tag: event.tag };
    case "settings":
      return { type: "settings", patch: event.patch };
    case "connected":
      return { type: "connected", value: event.value };
    case "error":
      return { type: "log", text: event.message, tag: "err" };
    default:
      return { type: "status", status: "idle" };
  }
}

type AppProps = {
  /** Pass your own implementation to connect the UI to a real engine. */
  adapter?: any;
};

export default function App({ adapter }: AppProps = {}) {
  const [state, dispatch] = useReducer(reducer, initialState);
  const reduce = useReducedMotion();
  const frameRef = useRef<HTMLDivElement>(null);
  const stateRef = useRef(state);
  stateRef.current = state;

  // Initialize the BridgeAPI on mount
  useBridgeInitialize(dispatch);

  // Poll the BridgeAPI for real-time events
  const unsubscribe = useBridgePolling(dispatch, [state.status]);

  // Keyboard shortcuts (Ctrl+Alt+D = PTT, Ctrl+Alt+F = VAD)
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        dispatch({ type: "sheet", open: false });
      }
      if (!event.ctrlKey || !event.altKey) return;
      const key = event.key.toLowerCase();
      if (key === "d") {
        event.preventDefault();
        // Push-to-talk: ask Python to toggle recording
        callBridgeAPI("toggle_recording");
      }
      if (key === "f") {
        event.preventDefault();
        // VAD toggle: ask Python to set VAD setting
        callBridgeAPI("set_setting", ["vad", !state.settings.vad]);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [state.settings.vad, dispatch]);

  // Adapter ref for direct method calls
  const adapterRef = useRef<any>(adapter);
  adapterRef.current = adapter;

  const meta = STATUS_META[state.status];
  const live = state.status === "recording";
  const toggleTake = () => {
    callBridgeAPI("toggle_recording");
  };
  const setSetting = <K extends keyof Settings>(key: K, value: Settings[K]) =>
    callBridgeAPI("set_setting", [key, value]);
  const trackPointer = (event: React.PointerEvent<HTMLDivElement>) => {
    const node = frameRef.current;
    if (!node) return;
    node.style.setProperty("--mx", `${event.clientX}px`);
    node.style.setProperty("--my", `${event.clientY}px`);
  };
  const rise = (delay: number) =>
    reduce
      ? {}
      : {
          initial: { opacity: 0, y: 14 },
          animate: { opacity: 1, y: 0 },
          transition: { duration: 0.7, delay, ease: "easeOut" as const },
        };

  return (
    <div
      ref={frameRef}
      onPointerMove={trackPointer}
      style={{ ["--tone" as string]: meta.tone }}
      className="pointer-light relative flex min-h-[100dvh] flex-col overflow-x-hidden bg-shell"
    >
      <div className="aura" aria-hidden="true" />
      <div className="stage-light" aria-hidden="true" />
      <div className="vignette" aria-hidden="true" />
      <div className="grain" aria-hidden="true" />

      <div className="relative z-10 mx-auto flex w-full max-w-[1400px] flex-1 flex-col px-5 py-5 sm:px-8 lg:px-12 lg:py-8">
        <motion.header
          {...rise(0)}
          className="flex flex-wrap items-center gap-x-5 gap-y-3 pb-4"
        >
          <SignalMark live={live} tone={meta.tone} />
          <div className="flex items-baseline gap-3">
            <span className="font-serif text-[23px] leading-none tracking-[-0.01em]">FlowMini</span>
            <span className="eyebrow hidden sm:block">voice instrument</span>
          </div>

          <div className="ml-auto flex items-center gap-4">
            {/* Preview switch removed — we use BridgeAPI in-process instead */}
            <button
              type="button"
              aria-label="Open controls"
              onClick={() => dispatch({ type: "sheet", open: true })}
              className="grid h-8 w-8 place-items-center rounded-full border border-white/10 text-body transition-colors hover:border-white/25 hover:text-ink"
            >
              <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true">
                <circle cx="8" cy="8" r="2.3" stroke="currentColor" strokeWidth="1.2" fill="none" />
                <path
                  d="M8 1.6v1.9M8 12.5v1.9M1.6 8h1.9M12.5 8h1.9M3.5 3.5l1.3 1.3M11.2 11.2l1.3 1.3M12.5 3.5l-1.3 1.3M4.8 11.2l-1.3 1.3"
                  stroke="currentColor"
                  strokeWidth="1.2"
                  strokeLinecap="round"
                />
              </svg>
            </button>
          </div>
        </motion.header>

        <div className="ruler" aria-hidden="true" />

        <main className="grid flex-1 gap-y-11 pt-10 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)] lg:gap-x-16">
          <motion.section
            {...rise(0.08)}
            className="flex flex-col gap-10 lg:border-r lg:border-white/8 lg:pr-16"
            aria-label="Instrument"
          >
            <div>
              <div className="flex items-baseline justify-between">
                <span className="eyebrow">01</span>
                <span className="eyebrow">state</span>
              </div>
              <h2
                className="mt-5 text-[clamp(2.1rem,3.4vw,3rem)] leading-[0.9] font-light tracking-[-0.035em] transition-colors duration-500"
                style={{ color: meta.tone }}
              >
                {meta.label}
              </h2>
              <p className="mt-4 max-w-[30ch] text-[12.5px] leading-relaxed text-body">{meta.hint}</p>
            </div>

            <Aperture
              status={state.status}
              level={state.level}
              tone={meta.tone}
              onToggle={toggleTake}
            />

            <div>
              <div className="flex items-baseline justify-between">
                <span className="eyebrow">02</span>
                <span className="eyebrow">signal</span>
                <span className="font-mono text-[10px] tabular-nums text-body">
                  {Math.round(state.level * 100)}%
                </span>
              </div>
              <div className="mt-3 h-px w-full bg-white/10">
                <div
                  className="h-px"
                  style={{
                    width: `${state.level * 100}%`,
                    background: meta.tone,
                    transition: "width 110ms linear",
                  }}
                />
              </div>

              <dl className="mt-6">
                <div
                  className="flex items-baseline justify-between gap-4 border-b border-white/6 py-[7px]"
                >
                  <span className="font-mono text-[9px] tracking-[0.2em] text-mute uppercase">adapter</span>
                  <span
                    className={`font-mono text-[10px] text-body ${
                      state.connected ? "text-ok" : "text-mute"
                    }`}
                  >
                    {state.connected ? "attached" : "not connected"}
                  </span>
                </div>
                <MetaRow label="language" value={state.settings.language} />
                <MetaRow
                  label="cleanup"
                  value={`${state.settings.cleanup} · ${state.settings.style}`}
                />
                <MetaRow
                  label="hands-free"
                  value={state.settings.vad ? "armed" : "off"}
                  tone={state.settings.vad ? "#6aa8ff" : undefined}
                />
              </dl>
            </div>
          </motion.section>

          <motion.section
            {...rise(0.16)}
            className="flex min-w-0 flex-col justify-between gap-10"
            aria-label="Transcript"
          >
            <TranscriptStage
              partial={state.partial}
              final={state.final}
              language={state.language}
              confidence={state.confidence}
              latencyMs={state.latencyMs}
              edits={state.edits}
            />
            <EventStream lines={state.logs} />
          </motion.section>
        </main>

        <motion.footer
          {...rise(0.24)}
          className="mt-10 flex flex-wrap items-end gap-x-10 gap-y-4 border-t border-white/8 pt-5"
        >
          <Numeral label="sessions" value={String(state.sessions).padStart(2, "0")} />
          <Numeral label="words" value={state.words.toLocaleString("en-US")} />
          <Numeral label="last take" value={state.latencyMs ? `${state.latencyMs} ms` : "—"} />
          <Numeral
            label="confidence"
            value={state.confidence ? `${Math.round(state.confidence * 100)}%` : "—"}
          />

          <div className="ml-auto flex flex-wrap items-center gap-x-5 gap-y-2 font-mono text-[9px] tracking-[0.16em] uppercase">
            <span className="text-mute">
              ctrl + alt + d <span className="text-white/25">take</span>
            </span>
            <span className="text-mute">
              ctrl + alt + f <span className="text-white/25">hands-free</span>
            </span>
            <span className="flex items-center gap-2 text-mute">
              <span
                className={`h-1 w-1 rounded-full ${state.connected ? "bg-ok" : "bg-white/25"}`}
              />
              {state.connected ? "adapter live" : "no adapter"}
            </span>
          </div>
        </motion.footer>
      </div>

      <SettingsSheet
        open={state.sheetOpen}
        settings={state.settings}
        onClose={() => dispatch({ type: "sheet", open: false })}
        onChange={setSetting}
        onSelfTest={() => callBridgeAPI("self_test")}
        onRefresh={() => callBridgeAPI("refresh_stats")}
        onUndo={() => callBridgeAPI("undo")}
        canUndo={state.canUndo}
      />
    </div>
  );
}

function SignalMark({ live, tone }: { live: boolean; tone: string }) {
  return (
    <span className="flex h-4 items-end gap-[3px]" aria-hidden="true">
      {[0, 1, 2].map((index) => (
        <span
          key={index}
          className="block w-[2px] origin-bottom rounded-full transition-colors duration-500"
          style={{
            height: `${6 + index * 4}px`,
            background: live ? tone : "rgb(255 255 255 / 0.35)",
            animation: live ? `signal 1.1s ease-in-out ${index * 0.14}s infinite` : undefined,
          }}
        />
      ))}
    </span>
  );
}

function MetaRow({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-white/6 py-[7px]">
      <dt className="font-mono text-[9px] tracking-[0.2em] text-mute uppercase">{label}</dt>
      <dd
        className="truncate font-mono text-[10px] tracking-[0.04em] text-body"
        style={tone ? { color: tone } : undefined}
      >
        {value}
      </dd>
    </div>
  );
}

function Numeral({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <p className="eyebrow">{label}</p>
      <p className="mt-1.5 font-mono text-[14px] leading-none tracking-[0.02em] text-ink tabular-nums">
        {value}
      </p>
    </div>
  );
}