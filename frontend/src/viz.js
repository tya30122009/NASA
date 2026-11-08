/**
 * QuickX Spectrum Plotter
 */
export function renderSpectrum(points) {
  const container = document.getElementById('spectrum-plot');
  container.innerHTML = '';
  if (!points.length) return;

  const maxFlux = Math.max(...points.map(p => p.flux_mjy_sr || 0));

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("width", "100%");
  svg.setAttribute("height", "100");
  svg.setAttribute("viewBox", `0 0 ${points.length * 20} 100`);

  points.forEach((p, i) => {
    const h = (p.flux_mjy_sr / (maxFlux || 1)) * 90;
    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("x", i * 20 + 2);
    rect.setAttribute("y", 100 - h);
    rect.setAttribute("width", "16");
    rect.setAttribute("height", h);
    rect.setAttribute("fill", "var(--cyan-500)");
    svg.appendChild(rect);
  });
  container.appendChild(svg);
}
