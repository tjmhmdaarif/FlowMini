type Props = {
  on: boolean;
  onChange: (next: boolean) => void;
  label: string;
};

export function Toggle({ on, onChange, label }: Props) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      onClick={() => onChange(!on)}
      className={`relative h-7 w-12 shrink-0 rounded-full transition-colors duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] ${
        on ? "bg-ok" : "bg-track"
      }`}
    >
      <span
        className={`absolute top-0.5 left-0.5 block h-6 w-6 rounded-full bg-knob shadow-[0_1px_4px_rgb(0_0_0_/_0.35)] transition-transform duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] ${
          on ? "translate-x-5" : "translate-x-0"
        }`}
      />
    </button>
  );
}
