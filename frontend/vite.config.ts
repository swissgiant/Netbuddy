import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev-Proxy: Frontend (Port 5173) leitet API-Pfade ans Backend (Port 8000) weiter.
const apiPaths = [
  "/topology",
  "/adapters",
  "/devices",
  "/device-credentials",
  "/discovery",
  "/sites",
  "/credentials",
  "/auth",
  "/users",
  "/health",
];

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: Object.fromEntries(
      apiPaths.map((p) => [p, { target: "http://127.0.0.1:8000", changeOrigin: true }]),
    ),
  },
});
