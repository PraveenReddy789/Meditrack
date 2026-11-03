// Tiny DOM helpers. All dynamic text goes through text nodes (never innerHTML),
// so patient names or server messages can't inject markup.

const PROPERTY_ATTRS = new Set(["value", "checked", "disabled", "selected", "required", "hidden", "readOnly"]);

export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else if (PROPERTY_ATTRS.has(key)) node[key] = value;
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  append(node, children);
  return node;
}

function append(node, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

export function clear(node) {
  node.replaceChildren();
  return node;
}

// ---- formatting ---------------------------------------------------------
export const pct = (x, digits = 1) => (x === null || x === undefined ? "—" : `${(x * 100).toFixed(digits)}%`);
export const num1 = (x) => (x === null || x === undefined ? "—" : Number(x).toFixed(1));

export function localISODate(d = new Date()) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function addDays(iso, days) {
  const d = new Date(`${iso}T12:00:00`);
  d.setDate(d.getDate() + days);
  return localISODate(d);
}

export function prettyDate(iso, { withWeekday = true } = {}) {
  const d = new Date(`${iso}T12:00:00`);
  return d.toLocaleDateString("en-GB", { weekday: withWeekday ? "short" : undefined, day: "numeric", month: "short" });
}

export const TYPE_LABELS = {
  checkup: "Check-up",
  follow_up: "Follow-up",
  specialist: "Specialist",
  vaccination: "Vaccination",
  lab_test: "Lab test",
};
export const STATUS_LABELS = { scheduled: "Scheduled", attended: "Attended", no_show: "No-show" };
export const RISK_LABELS = { low: "Low", medium: "Medium", high: "High" };

export function badge(kind, value, label) {
  return el("span", { class: `badge ${kind}-${value}` }, label);
}

export function toast(message, { error = false } = {}) {
  const host = document.getElementById("toasts");
  const node = el("div", { class: `toast${error ? " error" : ""}` }, message);
  host.append(node);
  setTimeout(() => node.remove(), error ? 7000 : 3800);
}
