import { api, ApiError, onUnauthorized } from "./api.js";
import { clear, el, toast } from "./dom.js";
import { mountAppointments } from "./views/appointments.js";
import { mountDashboard } from "./views/dashboard.js";
import { mountModel } from "./views/model.js";

const main = document.getElementById("main");
const topbar = document.getElementById("topbar");
const tabsHost = document.getElementById("tabs");
const userChip = document.getElementById("user-chip");

// Which tabs each permission unlocks. The server enforces access too; hiding is only for clarity.
const VIEWS = [
  { id: "appointments", label: "Appointments", needs: "appointments:read", mount: mountAppointments },
  { id: "dashboard", label: "Dashboard", needs: "reports:read", mount: mountDashboard },
  { id: "model", label: "Model", needs: "reports:read", mount: mountModel },
];

let user = null;

function showLogin(message = "") {
  user = null;
  topbar.hidden = true;
  const username = el("input", { id: "username", type: "text", autocomplete: "username", required: true, autocapitalize: "none" });
  const password = el("input", { id: "password", type: "password", autocomplete: "current-password", required: true });
  const errorHost = el("div", { "aria-live": "assertive" }, message ? el("div", { class: "alert error", role: "alert" }, message) : null);
  const submit = el("button", { type: "submit", class: "btn" }, "Sign in");

  const form = el("form", {
    class: "card login",
    onsubmit: async (e) => {
      e.preventDefault();
      clear(errorHost);
      submit.disabled = true;
      try {
        user = await api("/api/auth/login", { method: "POST", body: { username: username.value.trim(), password: password.value } });
        start();
      } catch (err) {
        const text = err instanceof ApiError && err.status === 422 ? "Enter your username and password." : err.message;
        errorHost.append(el("div", { class: "alert error", role: "alert" }, text));
        password.value = "";
        password.focus();
      } finally {
        submit.disabled = false;
      }
    },
  },
    el("h1", {}, el("span", { class: "brand-mark", "aria-hidden": "true" }, "+"), "MediTrack"),
    el("p", { class: "muted" }, "Sign in to reconcile appointments and see no-show predictions."),
    el("div", { class: "field" }, el("label", { for: "username" }, "Username"), username),
    el("div", { class: "field" }, el("label", { for: "password" }, "Password"), password),
    el("p", {}, submit),
    errorHost);

  clear(main).append(form);
  username.focus();
}

function start() {
  const allowed = VIEWS.filter((v) => user.permissions.includes(v.needs));
  topbar.hidden = false;
  userChip.textContent = `${user.username} · ${user.role}`;

  clear(tabsHost);
  const buttons = allowed.map((v) => {
    const b = el("button", { type: "button", class: "tab", role: "tab", id: `tab-${v.id}`, "aria-selected": "false" }, v.label);
    b.addEventListener("click", () => select(v.id));
    tabsHost.append(b);
    return b;
  });
  tabsHost.setAttribute("role", "tablist");

  function select(id) {
    allowed.forEach((v, i) => buttons[i].setAttribute("aria-selected", String(v.id === id)));
    const view = allowed.find((v) => v.id === id);
    clear(main).setAttribute("aria-labelledby", `tab-${id}`);
    view.mount(main, { user });
    history.replaceState(null, "", `#${id}`);
  }

  const wanted = location.hash.slice(1);
  select(allowed.some((v) => v.id === wanted) ? wanted : allowed[0].id);
}

document.getElementById("logout").addEventListener("click", async () => {
  try { await api("/api/auth/logout", { method: "POST" }); } catch { /* session may already be gone */ }
  history.replaceState(null, "", location.pathname);
  showLogin();
});

// Any 401 from a data call means the session ended (expired or signed out elsewhere).
onUnauthorized(() => {
  if (user) {
    toast("Your session has ended. Please sign in again.", { error: true });
    showLogin();
  }
});

(async function boot() {
  try {
    user = await api("/api/auth/me");
    start();
  } catch {
    showLogin();
  }
})();
