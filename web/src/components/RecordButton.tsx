import { motion, useReducedMotion } from "motion/react";
import type { EngineStatus } from "../engine";

type Props = {
  status: EngineStatus;
  onToggle: () => void;
};

export function RecordButton({ status, onToggle }: Props) {
  const reduce = useReducedMotion();
  const live = status === "recording";
  const busy = status === "processing";

  return (
    <div className="flex flex-col items-center gap-3">
      <button
        type="button"
        onClick={onToggle}
        aria-pressed={live}
        aria-label={live ? "Stop dictation" : "Start dictation"}
        className="relative grid h-[108px] w-[108px] place-items-center rounded-full"
      >
        <motion.span
          className="absolute inset-0 rounded-full border border-line"
          animate={
            reduce
              ? undefined
              : live
                ? { scale: [1, 1.08, 1], opacity: [0.35, 0.7, 0.35] }
                : { scale: 1, opacity: 0.35 }
          }
          transition={{ duration: 1.6, repeat: live ? Infinity : 0, ease: [0.32, 0.72, 0, 1] }}
        />
        <span className="absolute inset-[10px] rounded-full border border-line-soft" />
        <motion.span
          className={`relative z-[1] block h-[58px] w-[58px] ${
            live ? "rounded-[18px] bg-live" : busy ? "rounded-[18px] bg-wait" : "rounded-full bg-live"
          }`}
          animate={reduce ? undefined : { scale: live ? 0.92 : 1 }}
          transition={{ type: "spring", stiffness: 280, damping: 22 }}
          style={{
            boxShadow: live
              ? "0 0 0 6px color-mix(in srgb, var(--color-live) 22%, transparent)"
              : "inset 0 1px 0 rgb(255 255 255 / 0.18)",
          }}
        />
      </button>
      <p className="text-[13px] text-mute">
        {live ? "click to paste" : busy ? "cleaning the take" : "click, or press Ctrl+Alt+D"}
      </p>
    </div>
  );
}
