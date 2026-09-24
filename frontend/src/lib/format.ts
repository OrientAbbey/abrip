/** Formatage, en français, avec des espaces insécables pour les milliers. */

const NUMBER = new Intl.NumberFormat("fr-FR");
const PERCENT = new Intl.NumberFormat("fr-FR", {
  style: "percent",
  maximumFractionDigits: 1,
});
const DATETIME = new Intl.DateTimeFormat("fr-FR", {
  dateStyle: "short",
  timeStyle: "short",
  timeZone: "UTC",
});
const DATE = new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium", timeZone: "UTC" });

export const num = (value: number | null | undefined): string =>
  value === null || value === undefined ? "—" : NUMBER.format(value);

export const pct = (value: number | null | undefined): string =>
  value === null || value === undefined ? "—" : PERCENT.format(value);

export const dec = (value: number | null | undefined, digits = 2): string =>
  value === null || value === undefined ? "—" : value.toFixed(digits);

/** Les horodatages de la plateforme sont en UTC ; on le dit au lieu de
 *  convertir silencieusement vers le fuseau du navigateur. */
export const dt = (value: string | null | undefined): string =>
  value ? `${DATETIME.format(new Date(value))} UTC` : "—";

export const day = (value: string | null | undefined): string =>
  value ? DATE.format(new Date(value)) : "—";

export const SEVERITY_LABEL: Record<string, string> = {
  critical: "critique",
  watch: "à surveiller",
  info: "information",
};

export const CONFIDENCE_LABEL: Record<string, string> = {
  high: "confiance élevée",
  medium: "confiance moyenne",
  low: "confiance faible",
};

export const DETECTOR_LABEL: Record<string, string> = {
  moas: "Origines multiples (MOAS)",
  subprefix: "Annonce de sous-préfixe",
  rpki_invalid: "Invalide RPKI",
  valley_free: "Violation valley-free",
  churn_spike: "Pic d'instabilité",
  visibility_drop: "Chute de visibilité",
  bogon: "Bogon",
};

export const detectorLabel = (key: string): string => DETECTOR_LABEL[key] ?? key;

export const COUNTRY_LABEL: Record<string, string> = {
  CM: "Cameroun",
  SN: "Sénégal",
  KE: "Kenya",
  GH: "Ghana",
  ZA: "Afrique du Sud",
  EG: "Égypte",
  NG: "Nigeria",
  CI: "Côte d'Ivoire",
  TD: "Tchad",
  GA: "Gabon",
  CG: "Congo",
  CF: "Centrafrique",
  GQ: "Guinée équatoriale",
  MA: "Maroc",
  TN: "Tunisie",
  DZ: "Algérie",
  ET: "Éthiopie",
  TZ: "Tanzanie",
  UG: "Ouganda",
  RW: "Rwanda",
  ZW: "Zimbabwe",
  ZM: "Zambie",
  AO: "Angola",
  MZ: "Mozambique",
  BJ: "Bénin",
  BF: "Burkina Faso",
  ML: "Mali",
  NE: "Niger",
  TG: "Togo",
  GN: "Guinée",
  MG: "Madagascar",
  MU: "Maurice",
};

export const countryLabel = (iso2: string | null | undefined): string =>
  !iso2 ? "—" : (COUNTRY_LABEL[iso2] ?? iso2);
