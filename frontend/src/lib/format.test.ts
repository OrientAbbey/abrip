import { describe, expect, it } from "vitest";
import { day, dt, parseUtc } from "./format";

describe("parseUtc", () => {
  it("interprète une date naïve comme UTC, quel que soit le fuseau local", () => {
    expect(parseUtc("2026-08-24T13:30:00")).toBe(Date.UTC(2026, 7, 24, 13, 30));
  });

  it("respecte un suffixe Z explicite", () => {
    expect(parseUtc("2026-08-24T13:30:00Z")).toBe(Date.UTC(2026, 7, 24, 13, 30));
  });

  it("respecte un offset explicite", () => {
    expect(parseUtc("2026-08-24T15:30:00+02:00")).toBe(Date.UTC(2026, 7, 24, 13, 30));
  });

  it("accepte une date seule comme minuit UTC", () => {
    expect(parseUtc("2026-08-24")).toBe(Date.UTC(2026, 7, 24));
  });
});

describe("formatage", () => {
  it("affiche l'heure UTC annoncée", () => {
    expect(dt("2026-08-24T13:30:00")).toContain("13:30");
    expect(dt("2026-08-24T13:30:00")).toContain("UTC");
  });

  it("ne décale pas l'affichage d'une date seule", () => {
    expect(day("2026-08-24")).toContain("24");
    expect(day("2026-08-24")).toContain("2026");
  });
});
