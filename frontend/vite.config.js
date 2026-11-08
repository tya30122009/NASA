import { defineConfig } from "vite";

export default defineConfig({
  root: ".",
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true
      },
      "/health": "http://localhost:8000"
    }
  },
  build: {
    outDir: "dist",
    target: "es2022"
  }
});
