import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { LANGUAGES, type CleanupMode, type Settings, type StylePreset } from "../engine";

/** STT model names — the local streaming model is always tiny; these pick the
 *  final transcription model (tiny|base|small|medium|large-v3-turbo). */
export const STT_MODELS = [
  { value: "tiny", label: "tiny (fastest)" },
  { value: "base", label: "base" },
  { value: "small", label: "small" },
  { value: "medium", label: "medium" },
  { value: "large-v3-turbo", label: "large-v3-turbo (best)" },
] as const;

/** STT compute device. */
export const STT_DEVICES = [
  { value: "auto", label: "auto" },
  { value: "cuda", label: "cuda (GPU)" },
  { value: "cpu", label: "cpu (int8)" },
] as const;

/** Microphone input devices, as reported by the engine. */
export const MICS: string[] = [];

type Props = {
  open: boolean;
  settings: Settings;
  onClose: () => void;
  onChange: <K extends keyof Settings>(key: K, value: Settings[K]) => void;
  onSelfTest: () => void;
  onRefresh: () => void;
  onUndo: () => void;
  canUndo: boolean;
};

function Switch({
  on,
  onChange,
  label,
}: {
  on: boolean;
  onChange: (next: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      onClick={() => onChange(!on)}
      className="relative h-[18px] w-[32px] shrink-0 rounded-full border transition-colors duration-300"
      style={{
        background: on ? "color-mix(in srgb, #4ade9b 26%, transparent)" : "rgb(255 255 255 / 0.05)",
        borderColor: on ? "color-mix(in srgb, #4ade9b 55%, transparent)" : "rgb(255 255 255 / 0.12)",
      }}
    >
      <span
        className={`absolute top-[2px] left-[2px] block h-[12px] w-[12px] rounded-full transition-transform duration-300 ${
          on ? "translate-x-[14px] bg-ok" : "translate-x-0 bg-white/45"
        }`}
      />
    </button>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-white/6 py-3 last:border-0">
      <span className="text-[12.5px] text-body">{label}</span>
      {children}
    </div>
  );
}

const selectClass =
  "max-w-[180px] cursor-pointer border-0 border-b border-white/12 bg-transparent px-0 py-1 text-right font-mono text-[10.5px] tracking-[0.04em] text-ink outline-none transition-colors hover:border-white/30 focus:border-accent";

export function SettingsSheet({
  open,
  settings,
  onClose,
  onChange,
  onSelfTest,
  onRefresh,
  onUndo,
  canUndo,
}: Props) {
  const reduce = useReducedMotion();

  return (
    <AnimatePresence>
      {open ? (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={onClose}
            className="fixed inset-0 z-40 bg-black/65 backdrop-blur-[2px]"
            aria-hidden="true"
          />
          <motion.aside
            role="dialog"
            aria-label="Controls"
            initial={reduce ? false : { x: 36, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={reduce ? undefined : { x: 36, opacity: 0 }}
            transition={{ duration: 0.3, ease: "easeOut" }}
            className="fixed top-0 right-0 z-50 flex h-full w-[min(392px,100vw)] flex-col border-l border-white/8 bg-[#06070b]/95 px-7 py-7 backdrop-blur-2xl"
          >
            <div className="flex items-start justify-between">
              <div>
                <p className="eyebrow">deck</p>
                <h2 className="mt-2 font-serif text-[26px] leading-none tracking-[-0.01em] text-ink">
                  Controls
                </h2>
              </div>
              <button
                type="button"
                onClick={onClose}
                aria-label="Close controls"
                className="-mt-1 grid h-7 w-7 place-items-center rounded-full border border-white/10 text-[11px] text-body transition-colors hover:border-white/25 hover:text-ink"
              >
                ✕
              </button>
            </div>

            <div className="mt-7 flex-1 overflow-auto pr-1">
              <p className="eyebrow">voice</p>
              <div className="mt-1">
                <Field label="Language">
                  <select
                    aria-label="Language"
                    className={selectClass}
                    value={settings.language}
                    onChange={(event) => onChange("language", event.target.value)}
                  >
                    {LANGUAGES.map((language) => (
                      <option key={language.code} value={language.code}>
                        {language.label}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Translate to English">
                  <Switch
                    on={settings.translate}
                    onChange={(value) => onChange("translate", value)}
                    label="Translate to English"
                  />
                </Field>
                <Field label="Hands-free VAD">
                  <Switch
                    on={settings.vad}
                    onChange={(value) => onChange("vad", value)}
                    label="Hands-free VAD"
                  />
                </Field>
              </div>

              <p className="eyebrow mt-8">stt (live model)</p>
              <div className="mt-1">
                <Field label="Model">
                  <select
                    aria-label="STT model"
                    className={selectClass}
                    value={settings.stt_model}
                    onChange={(event) => onChange("stt_model", event.target.value)}
                  >
                    {STT_MODELS.map((m) => (
                      <option key={m.value} value={m.value}>
                        {m.label}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Device">
                  <select
                    aria-label="STT device"
                    className={selectClass}
                    value={settings.stt_device}
                    onChange={(event) => onChange("stt_device", event.target.value)}
                  >
                    {STT_DEVICES.map((d) => (
                      <option key={d.value} value={d.value}>
                        {d.label}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Mic device">
                  <select
                    aria-label="Microphone device"
                    className={selectClass}
                    value={settings.mic_device}
                    onChange={(event) => onChange("mic_device", event.target.value)}
                  >
                    <option value="">default (system)</option>
                    {MICS.map((m) => (
                      <option key={m} value={m}>
                        {m}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>

              <p className="eyebrow mt-8">cleanup</p>
              <div className="mt-1">
                <Field label="Mode">
                  <select
                    aria-label="Cleanup mode"
                    className={selectClass}
                    value={settings.cleanup}
                    onChange={(event) => onChange("cleanup", event.target.value as CleanupMode)}
                  >
                    <option value="off">off</option>
                    <option value="light">light</option>
                    <option value="medium">medium</option>
                  </select>
                </Field>
                <Field label="Style preset">
                  <select
                    aria-label="Style preset"
                    className={selectClass}
                    value={settings.style}
                    onChange={(event) => onChange("style", event.target.value as StylePreset)}
                  >
                    <option value="formal">formal</option>
                    <option value="casual">casual</option>
                    <option value="very_casual">very casual</option>
                    <option value="excited">excited</option>
                  </select>
                </Field>
                <Field label="Developer mode">
                  <Switch
                    on={settings.developer}
                    onChange={(value) => onChange("developer", value)}
                    label="Developer mode"
                  />
                </Field>
              </div>

              <p className="eyebrow mt-8">workflow</p>
              <div className="mt-1">
                <Field label="Per-app profiles">
                  <Switch
                    on={settings.profiles}
                    onChange={(value) => onChange("profiles", value)}
                    label="Per-app profiles"
                  />
                </Field>
                <Field label="Start with Windows">
                  <Switch
                    on={settings.autostart}
                    onChange={(value) => onChange("autostart", value)}
                    label="Start with Windows"
                  />
                </Field>
                <Field label="Show HUD">
                  <Switch
                    on={settings.hud}
                    onChange={(value) => onChange("hud", value)}
                    label="Show HUD"
                  />
                </Field>
                <Field label="Detect language">
                  <Switch
                    on={settings.detect_language}
                    onChange={(value) => onChange("detect_language", value)}
                    label="Detect language"
                  />
                </Field>
                <Field label="Auto-learn corrections">
                  <Switch
                    on={settings.auto_learn}
                    onChange={(value) => onChange("auto_learn", value)}
                    label="Auto-learn corrections"
                  />
                </Field>
              </div>

              <p className="eyebrow mt-8">session</p>
              <div className="mt-3 flex flex-wrap gap-x-6 gap-y-2">
                <SheetAction onClick={onSelfTest}>Self-test</SheetAction>
                <SheetAction onClick={onRefresh}>Stats</SheetAction>
                <SheetAction onClick={onUndo} disabled={!canUndo}>
                  Undo raw
                </SheetAction>
              </div>
            </div>

            <p className="mt-6 border-t border-white/6 pt-4 font-mono text-[9px] leading-relaxed tracking-[0.04em] text-mute">
              every control calls adapter.setSetting — wired live to the engine via BridgeAPI
            </p>
          </motion.aside>
        </>
      ) : null}
    </AnimatePresence>
  );
}

function SheetAction({
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
      onClick={onClick}
      disabled={disabled}
      className="border-b border-white/12 pb-1 font-mono text-[9.5px] tracking-[0.16em] text-body uppercase transition-colors hover:border-white/30 hover:text-ink disabled:cursor-not-allowed disabled:opacity-35"
    >
      {children}
    </button>
  );
}
