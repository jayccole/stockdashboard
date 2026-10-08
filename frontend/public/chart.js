// Single-series line chart with crosshair + tooltip. No dependencies.
// points: [{x: Date, y: number}], fmt: value formatter
export function lineChart(el, points, { fmt = (v) => v.toFixed(2), height = 260, label = "" } = {}) {
  el.innerHTML = "";
  if (!points.length) {
    el.innerHTML = '<p class="empty">No price history yet. Run "Pull daily history" on the Data jobs tab.</p>';
    return;
  }
  const W = Math.max(el.clientWidth || 600, 320), H = height;
  const m = { t: 10, r: 56, b: 24, l: 8 };
  const xs = points.map((p) => +p.x), ys = points.map((p) => p.y);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  let y0 = Math.min(...ys), y1 = Math.max(...ys);
  const pad = (y1 - y0) * 0.08 || Math.abs(y1) * 0.02 || 1;
  y0 -= pad; y1 += pad;
  const sx = (v) => m.l + ((v - x0) / (x1 - x0 || 1)) * (W - m.l - m.r);
  const sy = (v) => m.t + (1 - (v - y0) / (y1 - y0)) * (H - m.t - m.b);

  const ticks = niceTicks(y0, y1, 4);
  const xTicks = [0, 0.33, 0.66, 1].map((f) => new Date(x0 + f * (x1 - x0)));
  const d = points.map((p, i) => `${i ? "L" : "M"}${sx(+p.x).toFixed(1)},${sy(p.y).toFixed(1)}`).join("");

  el.insertAdjacentHTML("beforeend", `
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${label}">
      <g class="axis">
        ${ticks.map((t) => `<line class="grid-line" x1="${m.l}" x2="${W - m.r}" y1="${sy(t)}" y2="${sy(t)}"/>
          <text x="${W - m.r + 8}" y="${sy(t) + 4}">${fmt(t)}</text>`).join("")}
        ${xTicks.map((t, i) => `<text x="${sx(+t)}" y="${H - 6}" text-anchor="${i === 0 ? "start" : i === 3 ? "end" : "middle"}">${
          t.toLocaleDateString(undefined, { month: "short", day: "numeric", year: x1 - x0 > 3e10 ? "2-digit" : undefined })}</text>`).join("")}
      </g>
      <path class="line" d="${d}"/>
      <line class="cross" y1="${m.t}" y2="${H - m.b}" visibility="hidden"/>
      <circle class="marker" r="5" visibility="hidden"/>
      <rect x="${m.l}" y="0" width="${W - m.l - m.r}" height="${H}" fill="transparent"/>
    </svg>`);
  const svg = el.querySelector("svg");
  const cross = svg.querySelector(".cross"), marker = svg.querySelector(".marker"), hit = svg.querySelector("rect");
  const tip = document.createElement("div");
  tip.className = "tip"; tip.hidden = true; el.appendChild(tip);

  const show = (clientX) => {
    const r = svg.getBoundingClientRect();
    const vx = ((clientX - r.left) / r.width) * W;
    const tx = x0 + ((vx - m.l) / (W - m.l - m.r)) * (x1 - x0);
    let best = 0;
    for (let i = 1; i < xs.length; i++) if (Math.abs(xs[i] - tx) < Math.abs(xs[best] - tx)) best = i;
    const p = points[best], px = sx(+p.x), py = sy(p.y);
    cross.setAttribute("x1", px); cross.setAttribute("x2", px); cross.setAttribute("visibility", "visible");
    marker.setAttribute("cx", px); marker.setAttribute("cy", py); marker.setAttribute("visibility", "visible");
    tip.hidden = false;
    tip.textContent = `${p.x.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}  ${fmt(p.y)}`;
    tip.style.left = `${(px / W) * r.width}px`;
    tip.style.top = `${(py / H) * r.height}px`;
  };
  const hide = () => { cross.setAttribute("visibility", "hidden"); marker.setAttribute("visibility", "hidden"); tip.hidden = true; };
  hit.addEventListener("pointermove", (e) => show(e.clientX));
  hit.addEventListener("pointerleave", hide);
}

function niceTicks(lo, hi, n) {
  const span = hi - lo, step0 = span / n, mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map((s) => s * mag).find((s) => span / s <= n) || 10 * mag;
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}
