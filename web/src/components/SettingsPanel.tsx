import type { ReactNode } from "react";
import { Toggle } from "./Toggle";
import { LANGUAGES, type CleanupMode, type Settings, type StylePreset } from "../engine";

type Props = {
  settings: Settings;
  onPatch: (patch: Partial<Settings>) => void;
};

function Row({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-4 py-2">
      <span className="text-[14px] text-body">{label}</span>
      {children}
    </div>
  );
}

const selectClass =
  "max-w-[180px] rounded-lg border border-line bg-hover px-2.5 py-1.5 text-[13px] text-ink outline-none";

export function SettingsPanel({ settings, onPatch }: Props) {
  return (
    <div className="bezel h-full">
      <div className="bezel-core flex h-full flex-col px-4 py-3">
        <div className="flex items-start justify-between gap-4 pb-3">
          <div>
            <p className="text-[16px] font-semibold tracking-tight text-ink">
              VAD auto-dictation
            </p>
            <p className="mt-1 text-[13px] text-mute">
              Hands-free. Starts when you speak.
            </p>
          </div>
          <Toggle
            on={settings.vadArmed}
            onChange={(v) => onPatch({ vadArmed: v })}
            label="VAD auto-dictation"
          />
        </div>

        <div className="h-px bg-line-soft" />

        <p className="pt-3 pb-1 text-[13px] font-medium text-ink">Language</p>
        <Row label="Speech language">
          <select
            className={selectClass}
            value={settings.language}
            onChange={(e) => onPatch({ language: e.target.value })}
          >
            {LANGUAGES.map((l) => (
              <option key={l}>{l}</option>
            ))}
          </select>
        </Row>
        <Row label="Translate to English">
          <Toggle
            on={settings.translateToEnglish}
            onChange={(v) => onPatch({ translateToEnglish: v })}
            label="Translate to English"
          />
        </Row>
        <Row label="Cleanup mode">
          <select
            className={selectClass}
            value={settings.cleanupMode}
            onChange={(e) => onPatch({ cleanupMode: e.target.value as CleanupMode })}
          >
            <option value="light">light</option>
            <option value="medium">medium</option>
            <option value="off">off</option>
          </select>
        </Row>
        <Row label="Style preset">
          <select
            className={selectClass}
            value={settings.stylePreset}
            onChange={(e) => onPatch({ stylePreset: e.target.value as StylePreset })}
          >
            <option value="formal">formal</option>
            <option value="casual">casual</option>
            <option value="very_casual">very_casual</option>
            <option value="excited">excited</option>
          </select>
        </Row>

        <div className="my-2 h-px bg-line-soft" />
        <p className="pb-1 text-[13px] font-medium text-ink">Behaviour</p>
        <Row label="Developer mode">
          <Toggle
            on={settings.developerMode}
            onChange={(v) => onPatch({ developerMode: v })}
            label="Developer mode"
          />
        </Row>
        <Row label="Per-app profiles">
          <Toggle
            on={settings.profilesEnabled}
            onChange={(v) => onPatch({ profilesEnabled: v })}
            label="Per-app profiles"
          />
        </Row>
        <Row label="Start with Windows">
          <Toggle
            on={settings.autostart}
            onChange={(v) => onPatch({ autostart: v })}
            label="Start with Windows"
          />
        </Row>
        <Row label="Floating HUD">
          <Toggle
            on={settings.showHud}
            onChange={(v) => onPatch({ showHud: v })}
            label="Floating HUD"
          />
        </Row>
      </div>
    </div>
  );
}
