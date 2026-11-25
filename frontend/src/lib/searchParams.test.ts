import { describe, expect, it } from "vitest";
import { withFilter, withOffset } from "./searchParams";

describe("paramètres de liste", () => {
  it("changer un filtre supprime l'offset", () => {
    const params = new URLSearchParams("country=CM&offset=50");
    expect(withFilter(params, "q", "37100").toString()).toBe("country=CM&q=37100");
  });

  it("changer de page conserve les filtres", () => {
    const params = new URLSearchParams("country=CM&q=37100");
    expect(withOffset(params, 25).toString()).toBe("country=CM&q=37100&offset=25");
  });

  it("revenir à la première page supprime l'offset", () => {
    const params = new URLSearchParams("country=CM&offset=25");
    expect(withOffset(params, 0).toString()).toBe("country=CM");
  });

  it("vider un filtre supprime aussi l'offset", () => {
    const params = new URLSearchParams("q=37100&offset=25");
    expect(withFilter(params, "q", "").toString()).toBe("");
  });

  it("changer d'offset ne supprime pas l'offset courant", () => {
    const params = new URLSearchParams("country=CM&offset=25");
    expect(withFilter(params, "offset", "50").toString()).toBe("country=CM&offset=50");
  });
});
