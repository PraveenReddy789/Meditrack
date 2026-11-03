// Dependency-free SVG charts (nothing third-party can load under our CSP anyway).
import { prettyDate } from "./dom.js";

const NS = "http://www.w3.org/2000/svg";
const W = 720, H = 240;
const M = { l: 40, r: 12, t: 14, b: 30 };
const PLOT_W = W - M.l - M.r;
const PLOT_H = H - M.t - M.b;

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
    svg.append(s("text", { class: "axis-label", x: M.l - 6, y: y + 4, "text-anchor": "end" }, text(format(value))));
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
  const yMax = niceMax(Math.max(...points.map((p) => Math.max(p.no_shows, p.expected_no_shows))) * 1.1, 4);
  gridAndYLabels(svg, yMax, (v) => String(Math.round(v * 10) / 10));

  const step = PLOT_W / points.length;
  const barW = Math.max(2, Math.min(24, step * 0.62));
  const xCenter = (i) => M.l + step * i + step / 2;
  const yFor = (v) => M.t + PLOT_H - (v / yMax) * PLOT_H;

  points.forEach((p, i) => {
    const h = (p.no_shows / yMax) * PLOT_H;
    svg.append(s("rect", { class: "bar", x: xCenter(i) - barW / 2, y: M.t + PLOT_H - h, width: barW, height: Math.max(h, 0) },
      s("title", {}, text(`${prettyDate(p.date)}: ${p.no_shows} no-show${p.no_shows === 1 ? "" : "s"}, ${p.expected_no_shows} expected`))));
  });
  if (points.length > 1) {
    svg.append(s("polyline", { class: "line-expected", points: points.map((p, i) => `${xCenter(i)},${yFor(p.expected_no_shows)}`).join(" ") }));
  }
  xLabels(svg, points, xCenter);
  return svg;
}

/** Rolling 7-day no-show rate; days with no reconciled visits leave a gap rather than a fake zero. */
export function rateChart(points) {
  const svg = frame("Rolling 7-day no-show rate");
  if (!points.length) return svg;
  const rates = points.map((p) => p.rate_7d).filter((r) => r !== null);
  const yMax = Math.max(0.4, Math.ceil(Math.max(0, ...rates) * 1.15 * 20) / 20);
  gridAndYLabels(svg, yMax, (v) => `${Math.round(v * 100)}%`);

  const xFor = (i) => M.l + (points.length === 1 ? PLOT_W / 2 : (PLOT_W * i) / (points.length - 1));
  const yFor = (v) => M.t + PLOT_H - (v / yMax) * PLOT_H;

  let run = [];
  const flush = () => {
    if (run.length > 1) svg.append(s("polyline", { class: "line-rate", points: run.join(" ") }));
    run = [];
  };
  points.forEach((p, i) => {
    if (p.rate_7d === null) return flush();
    run.push(`${xFor(i)},${yFor(p.rate_7d)}`);
    if (points.length <= 31) {
      svg.append(s("circle", { class: "dot-rate", cx: xFor(i), cy: yFor(p.rate_7d), r: 3 },
        s("title", {}, text(`${prettyDate(p.date)}: ${(p.rate_7d * 100).toFixed(1)}% over the previous 7 days`))));
    }
  });
  flush();
  xLabels(svg, points, xFor);
  return svg;
}
