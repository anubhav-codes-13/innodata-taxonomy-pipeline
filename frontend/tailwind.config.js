/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#1F2530",
        bar: "#2D3340",
        body: "#3A4250",
        mut: "#8A93A0",
        line: "#C7CDD4",
        hair: "#EDF0F2",
        bg: "#F7F8FA",
        panel: "#F1F3F5",
        // accents
        anchor: { bg: "#DCEFE3", fg: "#2E7D52" },
        expand: { bg: "#FBE9D8", fg: "#B5651D" },
        ka: { bg: "#DCE7F7", fg: "#2B5C9B" },
        kcl: { bg: "#E0DEF7", fg: "#3B2B9B" },
      },
      fontFamily: {
        sans: ["Inter", "Segoe UI", "system-ui", "Arial", "sans-serif"],
      },
    },
  },
  plugins: [],
};
