/** @type {import('tailwindcss').Config} */
// GyroCore Premium Design System (ported from AeroTuner frontend/tailwind.config.js),
// loaded by Tailwind v4 through `@config` in src/index.css.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        muted: {
          foreground: "#94a3b8",
        },
      },
      fontFamily: {
        // Bundled offline via @fontsource-variable (no next/font, no CDN).
        sans: ['"Geist Variable"', "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ['"Geist Mono Variable"', "ui-monospace", "SFMono-Regular", "monospace"],
        wordmark: ['"Chakra Petch"', '"Geist Variable"', "sans-serif"],
      },
    },
  },
  plugins: [],
};
