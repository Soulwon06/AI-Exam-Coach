import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        primary: "#58cc02",
        "primary-dark": "#46a302",
        secondary: "#1cb0f6",
        accent: "#ffc800",
        danger: "#ff4b4b",
        surface: "#ffffff",
        muted: "#8a8d91",
        bg: "#f7f7f7",
      },
    },
  },
  plugins: [],
};

export default config;
