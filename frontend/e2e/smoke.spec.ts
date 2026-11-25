import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

/** Les parcours critiques doivent se dérouler sans erreur JavaScript ni
 * requête d'API en échec : c'est le complément navigateur des tests API. */
function watchErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(`console: ${message.text()}`);
  });
  page.on("response", (response) => {
    if (response.status() >= 500) errors.push(`HTTP ${response.status()}: ${response.url()}`);
  });
  return errors;
}

test("la vue d'ensemble charge les indicateurs", async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Vue d'ensemble" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Navigation principale" })).toBeVisible();
  await expect(page.getByRole("link", { name: /Systèmes autonomes/ })).toBeVisible();
  expect(errors).toEqual([]);
});

test("la liste des AS ouvre la fiche d'un AS", async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto("/asns");
  await expect(page.getByRole("heading", { level: 1, name: "Systèmes autonomes" })).toBeVisible();
  const firstAs = page.getByRole("link", { name: /^AS\d+/ }).first();
  await expect(firstAs).toBeVisible();
  const asn = (await firstAs.textContent())?.match(/AS(\d+)/)?.[1];
  expect(asn).toBeTruthy();
  await firstAs.click();
  await expect(page).toHaveURL(new RegExp(`/asns/${asn}`));
  await expect(page.getByRole("heading", { level: 1 })).toContainText(`AS${asn}`);
  expect(errors).toEqual([]);
});

test("la liste des préfixes ouvre la fiche d'un préfixe", async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto("/prefixes");
  await expect(page.getByRole("heading", { level: 1, name: "Préfixes" })).toBeVisible();
  const firstPrefix = page.locator("tbody a").first();
  await expect(firstPrefix).toBeVisible();
  const prefix = (await firstPrefix.textContent())?.trim();
  expect(prefix).toMatch(/^\d+\.\d+\.\d+\.\d+\/\d+$/);
  await firstPrefix.click();
  await expect(page).toHaveURL(/\/prefixes\//);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(prefix!);
  await expect(page.getByRole("heading", { name: "Autorisations RPKI" })).toBeVisible();
  expect(errors).toEqual([]);
});

test("la liste des événements ouvre un détail", async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto("/events");
  await expect(page.getByRole("heading", { level: 1, name: "Événements" })).toBeVisible();
  await page.getByRole("link", { name: "détail" }).first().click();
  await expect(page).toHaveURL(/\/events\//);
  await expect(page.getByRole("heading", { name: "Ce qui a été observé" })).toBeVisible();
  expect(errors).toEqual([]);
});
