import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The dev server sends /api to the FastAPI app (uvicorn api.main:app on port 8000).
// In production Caddy serves the built files and proxies /api (deploy/Caddyfile).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": process.env.API_URL ?? "http://127.0.0.1:8000" },
  },
  build: { outDir: "dist", sourcemap: false },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
