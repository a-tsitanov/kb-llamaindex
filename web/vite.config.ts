/// <reference types="vitest/config" />
import { defineConfig } from "vite";

// Same routes as nginx in the container: /board/* → lens (/lens/v1/*), /agent/* → lens-agent.
const board = process.env.LENS_BOARD_URL ?? "http://localhost:8010";
const agent = process.env.LENS_AGENT_URL ?? "http://localhost:8020";

export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      "/board": { target: board, changeOrigin: true, rewrite: (p) => p.replace(/^\/board/, "/lens/v1") },
      "/agent": { target: agent, changeOrigin: true, rewrite: (p) => p.replace(/^\/agent/, "") },
    },
  },
  build: { chunkSizeWarningLimit: 800 }, // vis-network alone is ~500 kB
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
