import { useEffect, useRef } from "react";
import type { EngineStatus } from "../engine";

type Props = {
  status: EngineStatus;
  level: number;
};

const BARS = 56;

export function Waveform({ status, level }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const buf = useRef<number[]>(Array.from({ length: BARS }, () => 0.08));
  const live = status === "recording" || status === "vad";

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    let raf = 0;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const paint = () => {
      const dpr = window.devicePixelRatio || 1;
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      if (canvas.width !== Math.floor(w * dpr) || canvas.height !== Math.floor(h * dpr)) {
        canvas.width = Math.floor(w * dpr);
        canvas.height = Math.floor(h * dpr);
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);

      const next = live
        ? Math.min(1, Math.max(0.12, level * 0.55 + Math.random() * 0.45))
        : 0.08 + Math.sin(performance.now() / 900) * 0.02;
      buf.current.push(reduce ? (live ? 0.55 : 0.1) : next);
      if (buf.current.length > BARS) buf.current.shift();

      const gap = 3;
      const barW = (w - gap * (BARS - 1)) / BARS;
      buf.current.forEach((v, i) => {
        const bh = Math.max(4, v * (h - 8));
        const x = i * (barW + gap);
        const y = (h - bh) / 2;
        ctx.fillStyle = live ? "#e63946" : "#39415a";
        ctx.globalAlpha = live ? 0.55 + v * 0.45 : 0.85;
        ctx.beginPath();
        ctx.roundRect(x, y, barW, bh, 2);
        ctx.fill();
      });
      ctx.globalAlpha = 1;
      raf = requestAnimationFrame(paint);
    };

    raf = requestAnimationFrame(paint);
    return () => cancelAnimationFrame(raf);
  }, [live, level]);

  return (
    <div className="bezel">
      <div className="bezel-core h-[72px] px-3 py-2">
        <canvas ref={canvasRef} className="h-full w-full" aria-hidden="true" />
        <span className="sr-only">
          {live ? "Microphone is open" : "Microphone is idle"}
        </span>
      </div>
    </div>
  );
}
