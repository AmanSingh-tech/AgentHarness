/** @type {import('tailwindcss').Config} */
// Colours resolve to CSS variables (src/theme.css), so every utility class follows the light/dark theme.
const v = (name) => `rgb(var(--${name}) / <alpha-value>)`;
const scale = (name) => Object.fromEntries([50, 100, 200, 300, 400, 500, 600, 700, 800, 900].map((s) => [s, v(`${name}-${s}`)]));
const PALETTES = ["slate", "emerald", "rose", "amber", "sky", "violet", "orange", "yellow", "teal", "indigo"];

export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  // Hover styles only on devices that can really hover (touch fires false hovers on tap).
  future: { hoverOnlyWhenSupported: true },
  theme: {
    extend: {
      colors: {
        ...Object.fromEntries(PALETTES.map((p) => [p, scale(p)])),
        page: v("page"), surface: v("surface"), ink: v("ink"),
        accent: { DEFAULT: v("accent"), strong: v("accent-strong"), soft: v("accent-soft") },
      },
      fontFamily: {
        sans: ['"Inter Tight"', "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      transitionTimingFunction: {
        out: "cubic-bezier(0.23, 1, 0.32, 1)",
        "in-out": "cubic-bezier(0.77, 0, 0.175, 1)",
      },
    },
  },
  plugins: [],
};
