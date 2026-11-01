/** Export du graphe de propagation : SVG autonome, PNG, CSV. Le SVG de la page
 *  s'appuie sur des variables CSS (var(--paper-raised)…) qui n'existent plus
 *  une fois le fichier ouvert ailleurs : on les remplace par leur valeur
 *  calculée avant de sérialiser. */

function resolveVars(value: string, root: CSSStyleDeclaration): string {
  return value.replace(/var\((--[\w-]+)\)/g, (_m, name: string) => root.getPropertyValue(name).trim() || "#000");
}

export function standaloneSvg(svg: SVGSVGElement): { text: string; width: number; height: number } {
  const root = getComputedStyle(document.documentElement);
  const clone = svg.cloneNode(true) as SVGSVGElement;
  const box = svg.viewBox.baseVal;
  const width = Math.round(box.width);
  const height = Math.round(box.height);
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("width", String(width));
  clone.setAttribute("height", String(height));
  clone.removeAttribute("style");
  // Les textes héritent de la police de la page : sans elle, le fichier retombe sur une police à empattements.
  clone.setAttribute("font-family", getComputedStyle(document.body).fontFamily);
  for (const el of [clone, ...Array.from(clone.querySelectorAll<SVGElement>("*"))]) {
    for (const attr of Array.from(el.attributes)) {
      if (attr.value.includes("var(")) el.setAttribute(attr.name, resolveVars(attr.value, root));
    }
  }
  const background = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  background.setAttribute("width", String(width));
  background.setAttribute("height", String(height));
  background.setAttribute("fill", root.getPropertyValue("--paper").trim() || "#ffffff");
  clone.insertBefore(background, clone.firstChild);
  return { text: new XMLSerializer().serializeToString(clone), width, height };
}

function save(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function downloadSvg(svg: SVGSVGElement, filename: string) {
  save(new Blob([standaloneSvg(svg).text], { type: "image/svg+xml;charset=utf-8" }), filename);
}

export async function downloadPng(svg: SVGSVGElement, filename: string, scale = 2) {
  const { text, width, height } = standaloneSvg(svg);
  const url = URL.createObjectURL(new Blob([text], { type: "image/svg+xml;charset=utf-8" }));
  try {
    const image = new Image();
    await new Promise<void>((resolve, reject) => {
      image.onload = () => resolve();
      image.onerror = () => reject(new Error("rendu du SVG impossible"));
      image.src = url;
    });
    const canvas = document.createElement("canvas");
    canvas.width = width * scale;
    canvas.height = height * scale;
    canvas.getContext("2d")!.drawImage(image, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
    if (!blob) throw new Error("export PNG impossible");
    save(blob, filename);
  } finally {
    URL.revokeObjectURL(url);
  }
}

const csvCell = (value: string | number) => {
  const text = String(value);
  return /[",\n;]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
};

export function downloadCsv(header: string[], rows: Array<Array<string | number>>, filename: string) {
  const body = [header, ...rows].map((row) => row.map(csvCell).join(";")).join("\r\n");
  // BOM : Excel ouvre ainsi le fichier en UTF-8 sans passer par l'assistant d'import.
  save(new Blob(["\ufeff", body], { type: "text/csv;charset=utf-8" }), filename);
}
