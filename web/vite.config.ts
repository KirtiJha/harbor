import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// `npm run dev` serves the UI with hot reload and forwards /api to a running Harbor (`python3 -m harbor`).
const api = (globalThis as { process?: { env: Record<string, string | undefined> } }).process?.env.HARBOR_URL || "http://127.0.0.1:7475";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: "127.0.0.1",
    port: 7476,
    proxy: { "/api": { target: api, changeOrigin: true } },
  },
});
