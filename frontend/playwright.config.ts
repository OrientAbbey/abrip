import { defineConfig, devices } from "@playwright/test";

// Le navigateur parle au service FastAPI, qui sert lui-même `frontend/dist`
// sur la même origine : aucun proxy ni URL absolue à configurer dans le test.
const port = Number(process.env.ABRIP_E2E_PORT ?? 8010);
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  // Un seul navigateur en local : le premier lancement peut être lent sur
  // Windows, et deux instances concurrentes dépassent le délai de démarrage.
  workers: process.env.CI ? 2 : 1,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["list"]] : [["list"]],
  use: {
    baseURL,
    trace: "on-first-retry",
    // Les endpoints analytiques de la démonstration peuvent prendre quelques
    // secondes au premier appel ; on attend les éléments, pas des délais fixes.
    navigationTimeout: 60_000,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `uv run --locked abrip api serve --host 127.0.0.1 --port ${port}`,
    cwd: "..",
    url: `${baseURL}/api/health`,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
});
