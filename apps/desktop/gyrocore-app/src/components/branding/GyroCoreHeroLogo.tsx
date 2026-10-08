/**
 * Hero wordmark — ported from AeroTuner components/branding/GyroCoreHeroLogo.tsx.
 * Chakra Petch is bundled locally (@fontsource) instead of next/font/google.
 */
import { cn } from "@/lib/utils";

export function GyroCoreHeroLogo({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-block max-w-full origin-center -skew-x-[6deg] select-none font-wordmark font-semibold leading-none tracking-[-0.022em] text-transparent antialiased [text-rendering:geometricPrecision]",
        "text-[clamp(2.5rem,3.4vw+1rem,3.75rem)]",
        className,
      )}
      style={{
        backgroundImage:
          "linear-gradient(180deg, #ffffff 0%, #ffffff 22%, #f0f9ff 40%, #e0f2fe 58%, #a5f3fc 78%, #22d3ee 100%)",
        WebkitBackgroundClip: "text",
        backgroundClip: "text",
        filter:
          "drop-shadow(0 0 0.5px rgba(255,255,255,0.88)) drop-shadow(0 0.5px 0 rgba(15,23,42,0.25)) drop-shadow(0 0 22px rgba(14,116,144,0.30)) drop-shadow(0 0 48px rgba(14,116,144,0.12))",
      }}
    >
      GyroCore
    </span>
  );
}
