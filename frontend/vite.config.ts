import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// ローカル開発専用の構成。/api はローカルバックエンドへプロキシする。
export default defineConfig({
  plugins: [react()],
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
