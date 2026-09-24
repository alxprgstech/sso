import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const backendTarget = process.env.VITE_BACKEND_TARGET || "http://localhost:8000";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: backendTarget,
        changeOrigin: true,
      },
      "/oauth": {
        target: backendTarget,
        changeOrigin: true,
      },
      "/.well-known": {
        target: backendTarget,
        changeOrigin: true,
      },
    },
  },
  preview: {
    port: 5173,
    proxy: {
      "/api": {
        target: backendTarget,
        changeOrigin: true,
      },
      "/oauth": {
        target: backendTarget,
        changeOrigin: true,
      },
      "/.well-known": {
        target: backendTarget,
        changeOrigin: true,
      },
    },
  },
});
