/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#101114",
        panel: "#17191f",
        panel2: "#20232b",
        line: "#2d313b",
        muted: "#9aa3b2",
        good: "#2dd4bf",
        warn: "#f59e0b",
        bad: "#fb7185",
        focus: "#60a5fa"
      },
      borderRadius: {
        control: "8px"
      }
    }
  },
  plugins: []
};
