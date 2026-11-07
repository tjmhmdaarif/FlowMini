import { motion, useReducedMotion } from "motion/react";
import type { Status } from "../engine";

const BARS = 96;
const C = 160;

type Props = {
  status: Status;
  level: number;
  tone: string;
  onToggle: () => void;
  disabled?: boolean;
};

/** Harmonic lens: ninety-six radial lines that breathe with the input level. */
export function Aperture({ status, level, tone, onToggle, disabled }: Props) {
  const reduce = useReducedMotion();
  const live = status === "recording";
  const busy = status === "processing";
  const heat = status === "error" ? 0.2 : status === "vad" ? 0.22 : 1;

  return (
    <div className="relative grid h-[min(52vw,300px)] w-[min(52vw,300px)] place-items-center">
      <div
        className="pointer-events-none absolute inset-0 rounded-full blur-[46px] transition-opacity duration-700"
        style={{
          background: `radial-gradient(circle, ${tone}33 0%, transparent 68%)`,
          opacity: live ? 0.9 : busy ? 0.55 : 0.28,
        }}
        aria-hidden="true"
      />

      <svg viewBox="0 0 320 320" className="absolute inset-0 h-full w-full" aria-hidden="true">
        <g className={reduce ? undefined : "slow-spin"}>
          {Array.from({ length: BARS }).map((_, index) => {
            const turn = index / BARS;
            const angle = turn * Math.PI * 2 - Math.PI / 2;
            const shape = 0.5 + 0.5 * Math.sin(turn * Math.PI * 2 * 5 + 0.4) * Math.cos(turn * Math.PI * 4);
            const pulse =
              0.5 + 0.5 * Math.sin(turn * Math.PI * 2 * 7 + level * Math.PI * 2);
            const value = live
              ? 0.24 + level * 0.95 * pulse
              : busy
                ? 0.3 + 0.2 * pulse
                : Math.max(0.1, (0.22 + 0.2 * shape) * heat);
            const inner = 116;
            const outer = inner + 4 + value * 26;
            return (
              <line
                key={index}
                x1={C + Math.cos(angle) * inner}
                y1={C + Math.sin(angle) * inner}
                x2={C + Math.cos(angle) * outer}
                y2={C + Math.sin(angle) * outer}
                stroke={tone}
                strokeWidth={index % 8 === 0 ? 1.6 : 1}
                strokeLinecap="round"
                opacity={index % 8 === 0 ? 0.75 : 0.42}
              />
            );
          })}
        </g>

        <circle cx={C} cy={C} r={108} fill="none" stroke="rgb(255 255 255 / 0.07)" strokeWidth="1" />
        <circle
          cx={C}
          cy={C}
          r={140}
          fill="none"
          stroke="rgb(255 255 255 / 0.06)"
          strokeWidth="1"
          strokeDasharray="1 7"
        />

        <circle
          cx={C}
          cy={C}
          r={140}
          fill="none"
          stroke={tone}
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeDasharray={`${Math.max(0.001, level) * 880} 880`}
          transform={`rotate(-90 ${C} ${C})`}
          opacity={live || busy ? 0.85 : 0.18}
          style={{ transition: "stroke-dasharray 120ms linear" }}
        />

        <g className={reduce ? undefined : "orbit"}>
          <circle cx={C} cy={16} r={1.8} fill={tone} opacity={live ? 0.9 : 0.45} />
        </g>

        {live && !reduce
          ? [0, 1].map((index) => (
              <motion.circle
                key={index}
                cx={C}
                cy={C}
                r={104}
                fill="none"
                stroke={tone}
                strokeWidth="1"
                initial={{ scale: 1, opacity: 0.45 }}
                animate={{ scale: 1.34, opacity: 0 }}
                transition={{ duration: 3, repeat: Infinity, delay: index * 1.5, ease: "easeOut" }}
                style={{ transformOrigin: "160px 160px" }}
              />
            ))
          : null}
      </svg>

      <motion.button
        type="button"
        onClick={onToggle}
        disabled={disabled}
        aria-pressed={live}
        aria-label={live ? "Finish the take" : "Start a take"}
        className="group relative grid h-[96px] w-[96px] place-items-center rounded-full disabled:cursor-not-allowed"
        whileHover={reduce ? undefined : { scale: 1.04 }}
        whileTap={reduce ? undefined : { scale: 0.96 }}
        transition={{ type: "spring", stiffness: 320, damping: 26 }}
      >
        <span
          className="absolute inset-0 rounded-full transition-all duration-500"
          style={{
            background: `radial-gradient(circle at 36% 26%, ${tone} 0%, ${tone}b3 46%, #5c0b16 100%)`,
            boxShadow: `0 0 46px ${tone}44, inset 0 1px 0 rgb(255 255 255 / 0.28)`,
          }}
        />
        <span className="absolute inset-[-1px] rounded-full border border-white/15" />
        <span
          className="absolute inset-[-13px] rounded-full border transition-colors duration-500"
          style={{ borderColor: `${tone}26` }}
        />

        <span
          className={`relative z-10 block bg-white transition-all duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] ${
            live ? "h-[20px] w-[20px] rounded-[4px]" : "h-[16px] w-[16px] rounded-full"
          }`}
        />

        {busy ? (
          <motion.span
            className="absolute inset-[-7px] rounded-full border"
            style={{ borderColor: `${tone}66`, borderTopColor: "transparent" }}
            animate={reduce ? undefined : { rotate: 360 }}
            transition={{ duration: 1.1, repeat: Infinity, ease: "linear" }}
          />
        ) : null}
      </motion.button>
    </div>
  );
}
