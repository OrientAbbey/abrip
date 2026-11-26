import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

/** Vérifications WCAG automatisées sur les pages les plus consultées. */
const parcours = [
  ["/", "Vue d'ensemble"],
  ["/asns", "Systèmes autonomes"],
  ["/prefixes", "Préfixes"],
  ["/events", "Événements"],
] as const;

for (const [route, titre] of parcours) {
  test(`accessibilité WCAG de ${route}`, async ({ page }) => {
    await page.goto(route);
    await expect(page.getByRole("heading", { level: 1, name: titre })).toBeVisible();

    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();

    const violations = results.violations.map((violation) => ({
      id: violation.id,
      impact: violation.impact,
      cibles: violation.nodes.map((node) => node.target.join(" ")),
    }));
    expect(violations).toEqual([]);
  });
}
