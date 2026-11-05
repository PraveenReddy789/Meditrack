// Dependency-free SVG charts designed for high-end SaaS medical dashboard.
import { pct, prettyDate } from "./dom.js";

const NS = "http://www.w3.org/2000/svg";
const W = 720, H = 220;
const M = { l: 42, r: 16, t: 20, b: 28 };
const PLOT_W = W - M.l - M.r;
const PLOT_H = H - M.t - M.b;

let tooltipEl = null;

function getTooltip() {
  if (!tooltipEl) {
    tooltipEl = document.createElement("div");
    tooltipEl.className = "chart-tooltip";
    tooltipEl.hidden = true;
    document.body.append(tooltipEl);
  }
  return tooltipEl;
}

function showChartTooltip(evt, { date, mainVal, mainLabel, metrics = [], accent = "#60a5fa" }) {
  const tip = getTooltip();
  tip.replaceChildren();

  const d = document.createElement("div");
  d.className = "tip-date";
  d.textContent = date;
  tip.append(d);

  const main = document.createElement("div");
  main.className = "tip-main";
  const val = document.createElement("span");
  val.className = "tip-stat-val";
  val.textContent = mainVal;
  val.style.color = accent;
  const lbl = document.createElement("span");
  lbl.className = "tip-stat-lbl";
  lbl.textContent = mainLabel;
  main.append(val, lbl);
  tip.append(main);

  if (metrics && metrics.length) {
    const divider = document.createElement("div");
    divider.className = "tip-divider";
    tip.append(divider);

    const grid = document.createElement("div");
    grid.className = "tip-grid";
    metrics.forEach(([label, value]) => {
      const row = document.createElement("div");
      row.className = "tip-row";
      const k = document.createElement("span");
      k.className = "tip-k";
      k.textContent = label;
      const v = document.createElement("span");
      v.className = "tip-v";
      v.textContent = String(value);
      row.append(k, v);
      grid.append(row);
    });
    tip.append(grid);
  }

  tip.hidden = false;
  positionTooltip(evt);
}

function positionTooltip(evt) {
  if (!tooltipEl || tooltipEl.hidden) return;
  const pad = 12;
  let x = evt.clientX + pad;
  let y = evt.clientY - pad - 20;
  if (x + 230 > window.innerWidth) x = evt.clientX - 240;
  if (y < 10) y = evt.clientY + 20;
  if (y + 140 > window.innerHeight) y = Math.max(10, window.innerHeight - 150);
  tooltipEl.style.left = `${x}px`;
  tooltipEl.style.top = `${y}px`;
}

function hideTooltip() {
  if (tooltipEl) tooltipEl.hidden = true;
}

function s(tag, attrs = {}, ...children) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
  for (const c of children) node.append(c);
  return node;
}
const text = (t) => document.createTextNode(t);

function frame(label) {
  return s("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": label });
}

function niceMax(value, minimum) {
  const v = Math.max(value, minimum);
  const step = v <= 5 ? 1 : v <= 10 ? 2 : v <= 25 ? 5 : v <= 100 ? 10 : 50;
  return Math.ceil(v / step) * step;
}

function gridAndYLabels(svg, yMax, format, ticks = 4) {
  for (let i = 0; i <= ticks; i++) {
    const value = (yMax / ticks) * i;
    const y = M.t + PLOT_H - (value / yMax) * PLOT_H;
    svg.append(s("line", { class: "grid-line", x1: M.l, x2: W - M.r, y1: y, y2: y }));
    svg.append(s("text", { class: "axis-label", x: M.l - 8, y: y + 4, "text-anchor": "end" }, text(format(value))));
  }
}

function xLabels(svg, points, xFor) {
  const picks = new Set([0, Math.floor((points.length - 1) / 2), points.length - 1]);
  for (const i of picks) {
    const anchor = i === 0 ? "start" : i === points.length - 1 ? "end" : "middle";
    svg.append(s("text", { class: "axis-label", x: xFor(i), y: H - 8, "text-anchor": anchor }, text(prettyDate(points[i].date, { withWeekday: false }))));
  }
}

/** Bars = actual no-shows per day, line = the model's expected no-shows for the same day. */
export function dailyChart(points) {
  const svg = frame("Daily no-shows: actual (bars) compared with model-expected (line)");
  if (!points.length) return svg;
  const yMax = niceMax(Math.max(...points.map((p) => Math.max(p.no_shows, p.expected_no_shows))) * 1.18, 4);
  gridAndYLabels(svg, yMax, (v) => String(Math.round(v * 10) / 10));

  const step = PLOT_W / points.length;
  const barW = Math.max(4, Math.min(22, step * 0.58));
  const xCenter = (i) => M.l + step * i + step / 2;
  const yFor = (v) => M.t + PLOT_H - (v / yMax) * PLOT_H;

  // Render bars with rounded corners
  points.forEach((p, i) => {
    const h = (p.no_shows / yMax) * PLOT_H;
    const bar = s("rect", {
      class: "bar",
      x: xCenter(i) - barW / 2,
      y: M.t + PLOT_H - h,
      width: barW,
      height: Math.max(h, 0),
      rx: 4,
      ry: 4,
    });
    svg.append(bar);

    // Only render direct labels when not crowded (<= 7 days) to prevent overlap!
    if (points.length <= 7 && p.no_shows > 0) {
      const rateStr = p.no_show_rate !== null ? `${Math.round(p.no_show_rate * 100)}%` : "";
      const labelText = rateStr ? `${p.no_shows} (${rateStr})` : `${p.no_shows}`;
      const labelY = Math.max(M.t + 11, yFor(p.no_shows) - 6);
      svg.append(s("text", {
        class: "chart-value-label",
        x: xCenter(i),
        y: labelY,
        fill: "#2563eb",
        "text-anchor": "middle",
        "pointer-events": "none",
        "font-size": "11px",
        "font-weight": "600",
      }, text(labelText)));
    }
  });

  // Expected no-shows line (warm coral/orange with smooth curve)
  if (points.length > 1) {
    svg.append(s("polyline", {
      class: "line-expected",
      points: points.map((p, i) => `${xCenter(i)},${yFor(p.expected_no_shows)}`).join(" "),
      fill: "none",
      stroke: "#f97316",
      "stroke-width": 2.5,
      "stroke-linecap": "round",
      "stroke-linejoin": "round",
    }));
  }

  // Interactive full-height hover slices for effortless hovering anywhere in the column
  points.forEach((p, i) => {
    const rateStr = p.no_show_rate !== null ? `${(p.no_show_rate * 100).toFixed(1)}%` : "0.0%";
    const slice = s("rect", {
      class: "hover-slice",
      fill: "transparent",
      x: xCenter(i) - step / 2,
      y: M.t,
      width: step,
      height: PLOT_H,
    });
    const trigger = (evt) => {
      showChartTooltip(evt, {
        date: prettyDate(p.date),
        mainVal: rateStr,
        mainLabel: "No-Show Rate",
        accent: "#60a5fa",
        metrics: [
          ["Actual no-shows", p.no_shows],
          ["Model expected", p.expected_no_shows],
          ["Attended visits", p.attended],
          ["Total scheduled", p.total],
        ],
      });
    };
    slice.addEventListener("mouseenter", trigger);
    slice.addEventListener("mousemove", positionTooltip);
    slice.addEventListener("mouseleave", hideTooltip);
    svg.append(slice);
  });

  xLabels(svg, points, xCenter);
  return svg;
}

/** Rolling 7-day no-show rate rendered as a sleek area chart matching the reference UI. */
export function rateChart(points) {
  const svg = frame("Rolling 7-day no-show rate");
  if (!points.length) return svg;
  const rates = points.map((p) => p.rate_7d).filter((r) => r !== null);
  const yMax = Math.max(0.4, Math.ceil(Math.max(0, ...rates) * 1.2 * 20) / 20);
  gridAndYLabels(svg, yMax, (v) => `${Math.round(v * 100)}%`);

  const xFor = (i) => M.l + (points.length === 1 ? PLOT_W / 2 : (PLOT_W * i) / (points.length - 1));
  const yFor = (v) => M.t + PLOT_H - (v / yMax) * PLOT_H;

  // Add gradient defs for soft modern area fill under the curve
  const gradId = `areaGrad_${Math.random().toString(36).slice(2, 8)}`;
  const defs = s("defs", {},
    s("linearGradient", { id: gradId, x1: "0", y1: "0", x2: "0", y2: "1" },
      s("stop", { offset: "0%", "stop-color": "#3b82f6", "stop-opacity": "0.22" }),
      s("stop", { offset: "100%", "stop-color": "#3b82f6", "stop-opacity": "0.01" })
    )
  );
  svg.append(defs);

  // Group continuous runs of non-null rate_7d
  const runs = [];
  let currentRun = [];
  points.forEach((p, i) => {
    if (p.rate_7d !== null) {
      currentRun.push({ x: xFor(i), y: yFor(p.rate_7d), point: p, index: i });
    } else if (currentRun.length) {
      runs.push(currentRun);
      currentRun = [];
    }
  });
  if (currentRun.length) runs.push(currentRun);

  // Render area fills and polylines
  runs.forEach((run) => {
    if (run.length > 1) {
      const baselineY = M.t + PLOT_H;
      const areaPoints = [
        `${run[0].x},${baselineY}`,
        ...run.map((pt) => `${pt.x},${pt.y}`),
        `${run[run.length - 1].x},${baselineY}`,
      ].join(" ");
      svg.append(s("polygon", {
        class: "chart-area",
        points: areaPoints,
        fill: `url(#${gradId})`,
      }));

      svg.append(s("polyline", {
        class: "line-rate",
        points: run.map((pt) => `${pt.x},${pt.y}`).join(" "),
        fill: "none",
        stroke: "#2563eb",
        "stroke-width": 2.5,
        "stroke-linecap": "round",
        "stroke-linejoin": "round",
      }));
    }
  });

  // Render dots
  points.forEach((p, i) => {
    if (p.rate_7d === null) return;
    const dot = s("circle", {
      class: "dot-rate",
      cx: xFor(i),
      cy: yFor(p.rate_7d),
      r: points.length <= 14 ? 4 : 3,
      fill: "#ffffff",
      stroke: "#2563eb",
      "stroke-width": 2,
    });
    svg.append(dot);

    // Only render direct text when not crowded (<= 7 days) to prevent clumsy overlap!
    if (points.length <= 7) {
      const pctText = `${(p.rate_7d * 100).toFixed(1)}%`;
      const labelY = Math.max(M.t + 11, yFor(p.rate_7d) - 8);
      svg.append(s("text", {
        class: "chart-rate-label",
        x: xFor(i),
        y: labelY,
        fill: "#2563eb",
        "text-anchor": "middle",
        "pointer-events": "none",
        "font-size": "11px",
        "font-weight": "700",
      }, text(pctText)));
    }
  });

  // Interactive full-height hover slices for effortless inspection
  const colW = PLOT_W / Math.max(1, points.length - 1);
  points.forEach((p, i) => {
    if (p.rate_7d === null) return;
    const rate7dStr = `${(p.rate_7d * 100).toFixed(1)}%`;
    const dayRateStr = p.no_show_rate !== null ? `${(p.no_show_rate * 100).toFixed(1)}%` : "0.0%";
    const slice = s("rect", {
      class: "hover-slice",
      fill: "transparent",
      x: xFor(i) - colW / 2,
      y: M.t,
      width: colW,
      height: PLOT_H,
    });
    const trigger = (evt) => {
      showChartTooltip(evt, {
        date: prettyDate(p.date),
        mainVal: rate7dStr,
        mainLabel: "Rolling 7-Day Rate",
        accent: "#93c5fd",
        metrics: [
          ["Day no-show rate", dayRateStr],
          ["Day no-shows", p.no_shows],
          ["Day attended", p.attended],
          ["Day visits", p.total],
        ],
      });
    };
    slice.addEventListener("mouseenter", trigger);
    slice.addEventListener("mousemove", positionTooltip);
    slice.addEventListener("mouseleave", hideTooltip);
    svg.append(slice);
  });

  xLabels(svg, points, xFor);
  return svg;
}
