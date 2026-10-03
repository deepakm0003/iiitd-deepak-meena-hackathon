import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The FastAPI engine runs on :8000; the app calls /api/* and Vite forwards it in development.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8000", rewrite: (p) => p.replace(/^\/api/, "") } },
  },
});
