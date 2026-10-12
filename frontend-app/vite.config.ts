import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// The built app is served by FastAPI at /app/. In dev, proxy API calls to the backend.
const backend = process.env.VITE_BACKEND ?? "http://localhost:8080";

export default defineConfig({
  base: "/app/",
  plugins: [react()],
  server: {
    proxy: Object.fromEntries(
      ["/api", "/health", "/history", "/stream"].map((path) => [path, backend]),
    ),
  },
  test: { environment: "jsdom", globals: true },
});
