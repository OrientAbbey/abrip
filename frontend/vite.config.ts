import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Le frontend est servi par FastAPI en production (même origine).
// En développement, /api est relayé vers uvicorn : le code client n'a donc
// jamais d'URL absolue à connaître, quel que soit l'environnement.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: true } },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    chunkSizeWarningLimit: 400,
    rollupOptions: {
      output: {
        // Séparer le socle React de la bibliothèque de graphiques : le socle
        // change rarement et reste en cache entre deux déploiements.
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          charts: ["recharts"],
        },
      },
    },
  },
});
