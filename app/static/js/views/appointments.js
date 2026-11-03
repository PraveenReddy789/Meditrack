import { api, ApiError, fieldPath } from "../api.js";
import { parseBulk } from "../bulk.js";
import { addDays, badge, clear, el, localISODate, num1, prettyDate, RISK_LABELS, STATUS_LABELS, toast, TYPE_LABELS } from "../dom.js";

export function mountAppointments(root, ctx) {
  const canWrite = ctx.user.permissions.includes("appointments:write");
  const canDelete = ctx.user.permissions.includes("appointments:delete");
  const state = { date: localISODate(), items: [], total: 0 };

  const listHost = el("div");
  const summaryHost = el("p", { class: "muted" });
  const dateInput = el("input", { type: "date", id: "list-date", value: state.date, "aria-label": "Show appointments for date" });

  const shiftDay = (n) => {
    state.date = addDays(state.date, n);
    dateInput.value = state.date;
    refresh();
  };

  root.append(
    el("div", { class: "page-head" },
      el("div", {}, el("h1", {}, "Appointments"),
        el("p", { class: "muted" }, canWrite
          ? "Enter the day's appointments, then mark each one attended or no-show as the day goes on."
          : "Read-only view of the day's appointments.")),
      el("div", { class: "form-row" },
        el("button", { type: "button", class: "btn btn-quiet", onclick: () => shiftDay(-1), "aria-label": "Previous day" }, "‹"),
        dateInput,
        el("button", { type: "button", class: "btn btn-quiet", onclick: () => shiftDay(1), "aria-label": "Next day" }, "›"),
        el("button", { type: "button", class: "btn btn-quiet", onclick: () => { state.date = localISODate(); dateInput.value = state.date; refresh(); } }, "Today"))),
    canWrite ? entryForms() : null,
    el("section", { class: "card", "aria-labelledby": "list-heading" },
      el("h2", { id: "list-heading" }, "Day list"), summaryHost, listHost),
  );
  dateInput.addEventListener("change", () => {
    if (dateInput.value) { state.date = dateInput.value; refresh(); }
  });

  // ---- entry forms ------------------------------------------------------
  function entryForms() {
    const name = el("input", { id: "f-name", type: "text", required: true, maxlength: 100, autocomplete: "off", placeholder: "e.g. Asha Rao" });
    const time = el("input", { id: "f-time", type: "time", required: true, min: "07:00", max: "19:59", value: "09:00" });
    const type = el("select", { id: "f-type" }, Object.entries(TYPE_LABELS).map(([v, l]) => el("option", { value: v }, l)));
    const date = el("input", { id: "f-date", type: "date", required: true, value: state.date });
    const booked = el("input", { id: "f-booked", type: "date" });
    const errorHost = el("div");
    const submit = el("button", { type: "submit", class: "btn" }, "Add appointment");

    dateInput.addEventListener("change", () => { date.value = state.date; });

    const form = el("form", {
      novalidate: true,
      onsubmit: async (e) => {
        e.preventDefault();
        clear(errorHost);
        submit.disabled = true;
        try {
          const body = {
            patient_name: name.value, appointment_date: date.value, appointment_time: time.value,
            appointment_type: type.value,
          };
          if (booked.value) body.booked_on = booked.value;
          const created = await api("/api/appointments", { method: "POST", body });
          toast(`Added ${created.patient_name} — ${RISK_LABELS[created.risk_level].toLowerCase()} no-show risk (${Math.round(created.risk_score * 100)}%)`);
          name.value = "";
          if (date.value !== state.date) { state.date = date.value; dateInput.value = date.value; }
          await refresh();
          name.focus();
        } catch (err) {
          showErrors(errorHost, err);
        } finally {
          submit.disabled = false;
        }
      },
    },
      el("div", { class: "form-row" },
        field("Patient name", name, "wide"), field("Time", time), field("Type", type), field("Date", date),
        field("Booked on (optional)", booked, "", "Leave blank for today; used to work out lead time."),
        submit),
      errorHost);

    // Bulk paste
    const area = el("textarea", { id: "bulk-text", spellcheck: "false", "aria-describedby": "bulk-hint",
      placeholder: "Asha Rao, 09:00\nBen Cole, 09:30, follow-up\nCara Dey, 10:15, lab test" });
    const bulkErrors = el("div");
    const bulkSubmit = el("button", { type: "submit", class: "btn" }, "Add all");
    const bulk = el("form", {
      novalidate: true,
      onsubmit: async (e) => {
        e.preventDefault();
        clear(bulkErrors);
        const parsed = parseBulk(area.value, state.date);
        if (parsed.errors.length) return showLineErrors(bulkErrors, parsed.errors.map((x) => `Line ${x.line}: ${x.message}`));
        if (!parsed.rows.length) return showLineErrors(bulkErrors, ["Paste at least one appointment."]);
        bulkSubmit.disabled = true;
        try {
          const created = await api("/api/appointments/bulk", { method: "POST", body: { appointments: parsed.rows } });
          const high = created.filter((a) => a.risk_level === "high").length;
          toast(`Added ${created.length} appointments (${high} high-risk)`);
          area.value = "";
          await refresh();
        } catch (err) {
          if (err instanceof ApiError && err.items.length) {
            const msgs = err.items.map((it) => {
              const idx = it.loc.find((p) => typeof p === "number");
              const line = idx === undefined ? "" : `Line ${parsed.lines[idx]}: `;
              return `${line}${fieldPath(it.loc)}${it.msg}`;
            });
            showLineErrors(bulkErrors, msgs, "Nothing was saved. Fix these and submit again:");
          } else {
            showErrors(bulkErrors, err, "Nothing was saved. ");
          }
        } finally {
          bulkSubmit.disabled = false;
        }
      },
    },
      el("div", { class: "field" },
        el("label", { for: "bulk-text" }, "Paste a list"),
        area,
        el("span", { id: "bulk-hint", class: "hint" }, "One per line: name, time (HH:MM), optional type. All rows use the date selected above and are saved together or not at all.")),
      el("div", { class: "form-row" }, bulkSubmit),
      bulkErrors);

    return el("div", { class: "grid cols-2" },
      el("section", { class: "card", "aria-labelledby": "single-heading" }, el("h2", { id: "single-heading" }, "Add one appointment"), form),
      el("section", { class: "card", "aria-labelledby": "bulk-heading" }, el("h2", { id: "bulk-heading" }, "Add many at once"), bulk));
  }

  // ---- list --------------------------------------------------------------
  async function refresh() {
    try {
      const data = await api(`/api/appointments?date=${state.date}&limit=500`);
      state.items = data.items;
      state.total = data.total;
      renderList();
    } catch (err) {
      clear(listHost).append(el("div", { class: "alert error", role: "alert" }, err.message));
    }
  }

  function renderList() {
    const items = state.items;
    const expected = items.reduce((sum, a) => sum + (a.risk_score ?? 0), 0);
    const high = items.filter((a) => a.risk_level === "high").length;
    const noShows = items.filter((a) => a.status === "no_show").length;
    summaryHost.textContent = items.length
      ? `${prettyDate(state.date)} · ${items.length} appointment${items.length === 1 ? "" : "s"} · ${num1(expected)} no-shows expected · ${high} high-risk · ${noShows} recorded no-show${noShows === 1 ? "" : "s"}`
      : prettyDate(state.date);

    clear(listHost);
    if (!items.length) {
      listHost.append(el("p", { class: "empty" }, canWrite ? "No appointments for this day yet. Add some above." : "No appointments for this day."));
      return;
    }
    const head = ["Time", "Patient", "Type", "No-show risk", "Status"];
    listHost.append(el("div", { class: "table-wrap" }, el("table", {},
      el("caption", { class: "sr-only" }, "Appointments"),
      el("thead", {}, el("tr", {}, head.map((h) => el("th", { scope: "col" }, h)), canWrite ? el("th", { scope: "col", class: "num" }, "Reconcile") : null)),
      el("tbody", {}, items.map(row)))));
  }

  function row(a) {
    const risk = a.risk_score === null ? "—" : `${RISK_LABELS[a.risk_level]} · ${Math.round(a.risk_score * 100)}%`;
    return el("tr", { dataset: { id: a.id } },
      el("td", { class: "num" }, a.appointment_time),
      el("td", {}, a.patient_name),
      el("td", {}, TYPE_LABELS[a.appointment_type]),
      el("td", {}, a.risk_level ? el("span", { class: `badge risk-${a.risk_level}`, title: `Model ${a.model_version}` }, risk) : "—"),
      el("td", {}, badge("status", a.status, STATUS_LABELS[a.status])),
      canWrite ? el("td", { class: "actions" }, actionsFor(a)) : null);
  }

  function actionsFor(a) {
    const set = (status) => async (e) => {
      e.currentTarget.disabled = true;
      try {
        await api(`/api/appointments/${a.id}`, { method: "PATCH", body: { status } });
        await refresh();
      } catch (err) {
        toast(err.message, { error: true });
        e.currentTarget.disabled = false;
      }
    };
    const buttons = [];
    if (a.status !== "attended") buttons.push(el("button", { type: "button", class: "btn btn-small", onclick: set("attended") }, "Attended"));
    if (a.status !== "no_show") buttons.push(el("button", { type: "button", class: "btn btn-small btn-danger", onclick: set("no_show") }, "No-show"));
    if (a.status !== "scheduled") buttons.push(el("button", { type: "button", class: "btn btn-small btn-quiet", onclick: set("scheduled") }, "Undo"));
    if (canDelete) {
      buttons.push(el("button", {
        type: "button", class: "btn btn-small btn-quiet", "aria-label": `Delete ${a.patient_name}`,
        onclick: async () => {
          if (!confirm(`Delete the appointment for ${a.patient_name}? This cannot be undone.`)) return;
          try { await api(`/api/appointments/${a.id}`, { method: "DELETE" }); await refresh(); }
          catch (err) { toast(err.message, { error: true }); }
        },
      }, "Delete"));
    }
    return buttons;
  }

  refresh();
}

function field(label, input, extraClass = "", hint = "") {
  return el("div", { class: `field ${extraClass}`.trim() },
    el("label", { for: input.id }, label), input, hint ? el("span", { class: "hint" }, hint) : null);
}

function showErrors(host, err, prefix = "") {
  const items = err instanceof ApiError && err.items.length
    ? err.items.map((it) => `${fieldPath(it.loc)}${it.msg}`) : [prefix + (err.message || "Something went wrong.")];
  showLineErrors(host, items);
}

function showLineErrors(host, messages, intro = "") {
  clear(host).append(el("div", { class: "alert error", role: "alert" },
    intro || null, el("ul", {}, messages.map((m) => el("li", {}, m)))));
}
