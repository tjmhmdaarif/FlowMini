import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { statusTone, statusWord, type EngineState } from "../engine";

type Props = {
  state: EngineState;
};

export function Hud({ state }: Props) {
  const reduce = useReducedMotion();
  const show =
    state.settings.showHud &&
    state.hudVisible &&
    (state.status === "recording" ||
      state.status === "processing" ||
      state.status === "pasted" ||
      state.status === "vad");

  return (
    <AnimatePresence>
      {show ? (
        <motion.aside
          initial={reduce ? false : { opacity: 0, y: 12, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={reduce ? undefined : { opacity: 0, y: 8, scale: 0.98 }}
          transition={{ duration: 0.28, ease: [0.32, 0.72, 0, 1] }}
          className="pointer-events-none fixed right-6 bottom-6 z-30 w-[min(320px,calc(100vw-2rem))]"
          aria-live="polite"
        >
          <div className="hud-glass rounded-[22px] border border-white/10 p-4">
            <div className="flex items-baseline justify-between gap-3">
              <p className={`text-[15px] font-semibold tracking-tight ${statusTone(state.status)}`}>
                {statusWord(state.status)}
              </p>
              {state.profile ? (
                <span className="rounded-full bg-hover px-2 py-0.5 font-mono text-[11px] text-body">
                  {state.profile}
                </span>
              ) : null}
            </div>
            <p className="mt-2 line-clamp-3 text-[14px] leading-snug text-ink">
              {state.status === "recording"
                ? "Listening. Text lands in the focused window."
                : state.transcript}
            </p>
          </div>
        </motion.aside>
      ) : null}
    </AnimatePresence>
  );
}
