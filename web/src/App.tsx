import { useEffect, useReducer, useRef } from "react";
import { ArrowUUpLeft } from "@phosphor-icons/react";
import { RecordButton } from "./components/RecordButton";
import { SettingsPanel } from "./components/SettingsPanel";
import { Waveform } from "./components/Waveform";
import { Hud } from "./components/Hud";
import {
  initialState,
  reducer,
  statusTone,
  statusWord,
  type EngineStatus,
} from "./engine";

const HUD_HIDE_MS = 10_000;

export default function App() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const sample = useRef(0);
  const hideTimer = useRef<number | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const d = e.key.toLowerCase() === "d";
      const f = e.key.toLowerCase() === "f";
      if (e.ctrlKey && e.altKey && d) {
        e.preventDefault();
        dispatch({ type: "toggle_ptt" });
      }
      if (e.ctrlKey && e.altKey && f) {
        e.preventDefault();
        dispatch({
          type: "patch_settings",
          patch: { vadArmed: !state.settings.vadArmed },
        });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [state.settings.vadArmed]);

  useEffect(() => {
    if (state.status !== "processing") return;
    const id = window.setTimeout(() => {
      sample.current += 1;
      dispatch({ type: "finish", sampleIndex: sample.current });
    }, 900);
    return () => window.clearTimeout(id);
  }, [state.status]);

  useEffect(() => {
    if (hideTimer.current) window.clearTimeout(hideTimer.current);
    if (!state.hudVisible) return;
    if (state.status === "recording" || state.status === "vad") return;
    hideTimer.current = window.setTimeout(() => {
      dispatch({ type: "hide_hud" });
    }, HUD_HIDE_MS);
    return () => {
      if (hideTimer.current) window.clearTimeout(hideTimer.current);
    };
  }, [state.hudVisible, state.status, state.transcript]);

  useEffect(() => {
    if (state.status !== "pasted") return;
    const id = window.setTimeout(() => dispatch({ type: "set_status", status: "idle" }), 1800);
    return () => window.clearTimeout(id);
  }, [state.status]);

  const live: EngineStatus[] = ["recording", "vad"];
  const level = live.includes(state.status) ? 0.72 : 0.1;

  return (
    <div className="relative min-h-[100dvh] bg-bg text-ink">
      <div className="grain" />
      <div className="pointer-events-none fixed inset-0 z-0 bg-[radial-gradient(900px_420px_at_12%_-10%,rgb(230_57_70_/_0.08),transparent_55%)]" />

      <div className="relative z-10 mx-auto grid max-w-[1180px] gap-4 px-5 py-5 md:px-7 md:py-6 lg:grid-cols-[minmax(0,1fr)_360px] lg:grid-rows-[auto_auto_auto_1fr_auto] lg:gap-x-5">
        <header className="flex flex-wrap items-center gap-x-4 gap-y-2 lg:col-span-2">
          <div className="flex items-baseline gap-3">
            <h1 className="text-[22px] font-semibold tracking-tight">FlowMini</h1>
            <p className="text-[13px] text-mute">voice dictation</p>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <kbd className="rounded-full border border-line bg-raised px-2.5 py-1 font-mono text-[11px] text-mute">
              CTRL+ALT+D
            </kbd>
            <kbd className="rounded-full border border-line bg-raised px-2.5 py-1 font-mono text-[11px] text-mute">
              CTRL+ALT+F
            </kbd>
          </div>
        </header>

        <div className="flex items-end justify-between gap-4 lg:col-span-2">
          <div className="flex items-center gap-3">
            <span
              className={`block h-2.5 w-2.5 rounded-full ${
                state.status === "recording"
                  ? "bg-live-bright"
                  : state.status === "processing"
                    ? "bg-wait"
                    : state.status === "vad"
                      ? "bg-info"
                      : "bg-ok"
              }`}
            />
            <p
              className={`text-[40px] leading-[1.05] font-semibold tracking-tight md:text-[48px] ${statusTone(state.status)}`}
            >
              {statusWord(state.status)}
            </p>
          </div>
          <p className="pb-2 text-[13px] text-mute">{state.modeLabel}</p>
        </div>

        <div className="flex flex-col gap-4">
          <Waveform status={state.status} level={level} />
          <RecordButton
            status={state.status}
            onToggle={() => dispatch({ type: "toggle_ptt" })}
          />
          <div className="bezel">
            <div className="bezel-core px-4 py-3">
              <p className="text-[13px] font-medium text-ink">Last dictation</p>
              <p
                className={`mt-2 text-[17px] leading-snug ${
                  state.transcript === "nothing dictated yet" ? "text-mute" : "text-ink"
                }`}
              >
                {state.transcript}
              </p>
              {state.heard ? (
                <p className="mt-2 font-mono text-[12px] leading-relaxed text-mute">{state.heard}</p>
              ) : null}
              {state.profile ? (
                <p className="mt-2 inline-flex rounded-full bg-hover px-2 py-0.5 font-mono text-[11px] text-body">
                  profile {state.profile}
                </p>
              ) : null}
            </div>
          </div>
        </div>

        <div className="lg:row-span-2 lg:row-start-3">
          <SettingsPanel
            settings={state.settings}
            onPatch={(patch) => dispatch({ type: "patch_settings", patch })}
          />
        </div>

        <div className="flex flex-col gap-3 lg:col-span-2">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            <GhostButton onClick={() => dispatch({ type: "self_test" })}>
              Self-test
            </GhostButton>
            <GhostButton onClick={() => dispatch({ type: "refresh_stats" })}>
              Refresh stats
            </GhostButton>
            <GhostButton
              disabled={!state.canUndo}
              onClick={() => dispatch({ type: "undo" })}
            >
              <ArrowUUpLeft size={16} weight="bold" />
              Undo raw
            </GhostButton>
          </div>
          <p className="font-mono text-[12px] text-mute">{state.stats}</p>
          <div className="bezel min-h-[160px]">
            <div className="bezel-core max-h-[220px] overflow-auto px-4 py-3">
              <ul className="space-y-1.5 font-mono text-[12px] leading-relaxed">
                {state.log.map((row) => (
                  <li key={row.id} className={logColor(row.level)}>
                    <span className="text-mute">{row.t}</span> {row.text}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </div>

      <Hud state={state} />
    </div>
  );
}

function GhostButton({
  children,
  onClick,
  disabled,
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="inline-flex items-center justify-center gap-2 rounded-[14px] border border-line bg-raised px-4 py-2.5 text-[14px] text-body transition-transform duration-200 ease-[cubic-bezier(0.32,0.72,0,1)] hover:bg-hover active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40"
    >
      {children}
    </button>
  );
}

function logColor(level: "ok" | "warn" | "err" | "dim") {
  switch (level) {
    case "ok":
      return "text-ok";
    case "warn":
      return "text-wait";
    case "err":
      return "text-live-bright";
    default:
      return "text-mute";
  }
}
