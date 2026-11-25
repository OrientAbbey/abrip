import { defineConfig } from "vitest/config";

// Les fichiers `e2e/` sont exécutés par Playwright (`npm run test:e2e`).
// Vitest ne doit voir que les tests unitaires, sinon il tente de lancer les
// tests navigateur avec son propre runner.
export default defineConfig({
  test: {
    include: ["src/**/*.test.ts"],
  },
});
