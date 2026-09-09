import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Deliberately restrained. This has to read clearly on a projector at
        // the demo, so contrast matters more than personality.
        ink: "#111827",
        muted: "#6b7280",
        line: "#e5e7eb",
        surface: "#f9fafb",
        accent: "#1d4ed8",
        danger: "#b91c1c",
        warn: "#b45309",
        ok: "#15803d",
      },
    },
  },
  plugins: [],
};

export default config;
