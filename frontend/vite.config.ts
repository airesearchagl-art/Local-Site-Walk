import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// ローカル開発専用の構成。/api はローカルバックエンドへプロキシする。
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        // three.js is only used by the lazily-loaded 360 player (see
        // App.tsx), so it's already out of the initial bundle. Splitting
        // it into its own chunk (separate from PlayerView's own ~3 kB of
        // component code) means editing PlayerView doesn't invalidate the
        // browser cache for the much larger vendor code.
        manualChunks: {
          three: ["three"],
        },
      },
    },
    // The "three" chunk above is ~500 kB minified almost entirely from
    // three.js itself (PlayerView's own code is ~3 kB) - that's the
    // library's floor for the WebGLRenderer/Scene/Camera/geometry/material
    // subset this app uses, not a bundling problem. It's already isolated
    // from the initial load and only fetched when the 360 player opens, so
    // raise the warning threshold just enough to stop flagging that one
    // unavoidable on-demand chunk instead of hiding it entirely.
    chunkSizeWarningLimit: 600,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
