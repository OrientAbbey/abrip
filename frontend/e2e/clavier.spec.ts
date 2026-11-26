import { expect, test, type Locator, type Page } from "@playwright/test";

/** Atteint un élément uniquement avec Tab, comme un utilisateur clavier. */
async function tabJusquA(page: Page, cible: Locator): Promise<void> {
  for (let i = 0; i < 80; i += 1) {
    if (await cible.evaluate((element) => element === document.activeElement)) return;
    await page.keyboard.press("Tab");
  }
  throw new Error("Élément jamais atteint avec Tab");
}

test("les onglets d'une fiche AS répondent aux flèches, Début et Fin", async ({ page }) => {
  await page.goto("/asns/37100");
  const onglets = page.getByRole("tablist", { name: "Sections de la page" });
  const prefix = onglets.getByRole("tab", { name: "Préfixes" });
  await expect(prefix).toHaveAttribute("aria-selected", "true");

  await tabJusquA(page, prefix);
  await page.keyboard.press("ArrowRight");
  const voisins = onglets.getByRole("tab", { name: "Voisins BGP" });
  await expect(voisins).toBeFocused();
  await expect(voisins).toHaveAttribute("aria-selected", "true");

  await page.keyboard.press("End");
  await expect(onglets.getByRole("tab", { name: /Événements/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await page.keyboard.press("Home");
  await expect(prefix).toHaveAttribute("aria-selected", "true");
});

test("une modale s'ouvre au clavier et se ferme avec Échap", async ({ page }) => {
  await page.goto("/asns/37100");
  const bouton = page.getByRole("button", { name: /^Historique d'annonce de/ }).first();
  await expect(bouton).toBeVisible();

  await tabJusquA(page, bouton);
  await page.keyboard.press("Enter");
  const dialogue = page.getByRole("dialog");
  await expect(dialogue).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(dialogue).toHaveCount(0);
  await expect(bouton).toBeFocused();
});
