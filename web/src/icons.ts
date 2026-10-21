// Inline line icons, built with the DOM API (no innerHTML, allowed by the page's CSP). Decorative: aria-hidden.
const NS = "http://www.w3.org/2000/svg";

const PATHS: Record<string, string[]> = {
  logo: ["M3 16c2.5-5.5 15.5-5.5 18 0", "M3 16h18", "M6.5 12.5v3.5", "M17.5 12.5v3.5", "M8 8h2l1.5-3 2 6 1.5-3h1"],
  mic: ["M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3z", "M19 11a7 7 0 0 1-14 0", "M12 18v3", "M8.5 21h7"],
  mouse: ["M12 3a6 6 0 0 0-6 6v6a6 6 0 0 0 12 0V9a6 6 0 0 0-6-6z", "M12 3v7", "M6 10h12"],
  speaker: ["M11 5 6 9H3v6h3l5 4V5z", "M15.5 8.5a5 5 0 0 1 0 7", "M18.5 5.5a9 9 0 0 1 0 13"],
  window: ["M3 5h18v14H3z", "M3 9h18", "M6 7h.01", "M8.5 7h.01"],
  question: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M9.5 9.5a2.5 2.5 0 1 1 3.6 2.2c-.7.4-1.1 1-1.1 1.8", "M12 16.5h.01"],
  shield: ["M12 3l8 3v6c0 5-3.5 8.5-8 9-4.5-.5-8-4-8-9V6l8-3z", "M9 12l2 2 4-4"],
  stop: ["M7 7h10v10H7z"],
  laptop: ["M5 5h14v10H5z", "M2.5 19h19"],
  link: ["M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1", "M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1"],
  send: ["M4 12l16-8-6 16-2.5-6.5L4 12z"],
  spark: ["M12 3v4", "M12 17v4", "M3 12h4", "M17 12h4", "M6 6l2.5 2.5", "M15.5 15.5 18 18", "M18 6l-2.5 2.5", "M8.5 15.5 6 18"],
  check: ["M5 12.5l4.5 4.5L19 7"],
  bolt: ["M13 2 4 14h7l-1 8 9-12h-7l1-8z"],
  phone: ["M8 2.5h8a1.5 1.5 0 0 1 1.5 1.5v16a1.5 1.5 0 0 1-1.5 1.5H8A1.5 1.5 0 0 1 6.5 20V4A1.5 1.5 0 0 1 8 2.5z", "M11 18.5h2"],
};

export function icon(name: string, cls = "ico"): SVGSVGElement {
  const svg = document.createElementNS(NS, "svg");
  for (const [k, v] of Object.entries({
    viewBox: "0 0 24 24", "aria-hidden": "true", focusable: "false", class: cls, fill: "none", stroke: "currentColor",
    "stroke-width": "1.8", "stroke-linecap": "round", "stroke-linejoin": "round",
  })) svg.setAttribute(k, v);
  for (const d of PATHS[name] ?? PATHS.question) {
    const p = document.createElementNS(NS, "path");
    p.setAttribute("d", d);
    svg.append(p);
  }
  return svg;
}
