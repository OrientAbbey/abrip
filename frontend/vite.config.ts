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
        // Vite 8 (rolldown) n'accepte que la forme fonctionnelle.
        manualChunks(id) {
          if (
            id.includes("/node_modules/react/") ||
            id.includes("/node_modules/react-dom/") ||
            id.includes("/node_modules/react-router") ||
            id.includes("/node_modules/scheduler/")
          ) {
            return "react";
          }
          if (
            id.includes("/node_modules/recharts/") ||
            id.includes("/node_modules/d3-") ||
            id.includes("/node_modules/victory-vendor/")
          ) {
            return "charts";
          }
          return undefined;
        },
      },
    },
  },
});
