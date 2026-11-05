import { api, ApiError, fieldPath } from "../api.js";
import { parseBulk } from "../bulk.js";
import { addDays, badge, clear, el, localISODate, num1, prettyDate, RISK_LABELS, showCenterModal, STATUS_LABELS, toast, TYPE_LABELS } from "../dom.js";

export function mountAppointments(root, ctx) {
  const canWrite = ctx.user.permissions.includes("appointments:write");
  const canDelete = ctx.user.permissions.includes("appointments:delete");
  const today = localISODate();
  const PAGE_SIZE = 8;
  const state = { date: today, items: [], total: 0, page: 1 };

  const listHost = el("div");
  const summaryHost = el("p", { class: "muted" });
  const dateInput = el("input", { type: "date", id: "list-date", value: state.date, "aria-label": "Show appointments for date" });

  let updateFormState = () => {};

  const prevBtn = el("button", { type: "button", class: "btn btn-quiet", onclick: () => shiftDay(-1), "aria-label": "Previous day" }, "‹");

  const shiftDay = (n) => {
    state.date = addDays(state.date, n);
    state.page = 1;
    dateInput.value = state.date;
    updateFormState();
    refresh();
  };

  const refreshBtn = el("button", { type: "button", class: "btn btn-quiet", onclick: () => refresh(true), "aria-label": "Refresh appointments list" }, "Refresh");

  root.append(
    el("div", { class: "page-head" },
      el("div", {}, el("h1", {}, "Appointments"),
        el("p", { class: "muted" }, canWrite
          ? "Enter the day's appointments, then mark each one attended or no-show as the day goes on."
          : "Read-only view of the day's appointments.")),
      el("div", { class: "form-row" },
        prevBtn,
        dateInput,
        el("button", { type: "button", class: "btn btn-quiet", onclick: () => shiftDay(1), "aria-label": "Next day" }, "›"),
        el("button", { type: "button", class: "btn btn-quiet", onclick: () => { state.date = localISODate(); dateInput.value = state.date; updateFormState(); refresh(); } }, "Today"),
        refreshBtn)),
    canWrite ? entryForms() : null,
    el("section", { class: "card", "aria-labelledby": "list-heading" },
      el("h2", { id: "list-heading" }, "Day list"), summaryHost, listHost),
  );
  dateInput.addEventListener("change", () => {
    if (dateInput.value) {
      state.date = dateInput.value;
      state.page = 1;
      updateFormState();
      refresh();
    }
  });

  // ---- entry forms ------------------------------------------------------
  function entryForms() {
    const name = el("input", { id: "f-name", type: "text", required: true, maxlength: 100, autocomplete: "off", placeholder: "e.g. Praveen Kumar" });
    const phone = el("input", { id: "f-phone", type: "tel", required: true, maxlength: 25, autocomplete: "off", placeholder: "e.g. 9398242064 or +91 98451 23456" });
    const time = el("input", { id: "f-time", type: "time", required: true, min: "08:00", max: "17:00", value: "09:00" });
    const type = el("select", { id: "f-type" }, Object.entries(TYPE_LABELS).map(([v, l]) => el("option", { value: v }, l)));
    const date = el("input", { id: "f-date", type: "date", required: true, value: state.date, min: localISODate() });
    const booked = el("input", { id: "f-booked", type: "date", min: localISODate() });
    const errorHost = el("div");
    const submit = el("button", { type: "submit", class: "btn" }, "Add appointment");

    dateInput.addEventListener("change", () => {
      date.value = state.date;
      date.min = localISODate();
    });

    const form = el("form", {
      novalidate: true,
      onsubmit: async (e) => {
        e.preventDefault();
        clear(errorHost);

        const patientName = name.value.trim();
        const patientPhone = phone.value.trim();

        if (!patientName) {
          const msg = "Patient name is required.";
          showErrors(errorHost, { message: msg });
          name.focus();
          return;
        }

        if (!patientPhone) {
          const msg = "Mobile number is required for patient appointment booking and reminders.";
          showErrors(errorHost, { message: msg });
          phone.focus();
          return;
        }

        const now = new Date();
        const todayStr = localISODate(now);
        const currentHours = String(now.getHours()).padStart(2, "0");
        const currentMinutes = String(now.getMinutes()).padStart(2, "0");
        const currentTime = `${currentHours}:${currentMinutes}`;

        if (date.value < todayStr) {
          const msg = "You cannot enter or book an appointment for past dates. Please select today or an upcoming date.";
          showCenterModal("Past Date Not Allowed", msg);
          showErrors(errorHost, { message: msg });
          return;
        }
        if (date.value === todayStr && time.value < currentTime) {
          const msg = `You cannot enter or book an appointment for a past time or date. The time ${time.value} has already passed (current time is ${currentTime}). Please select an upcoming slot.`;
          showCenterModal("Past Time Not Allowed", msg);
          showErrors(errorHost, { message: msg });
          return;
        }

        submit.disabled = true;
        try {
          const body = {
            patient_name: patientName,
            patient_phone: patientPhone,
            appointment_date: date.value,
            appointment_time: time.value,
            appointment_type: type.value,
          };
          if (booked.value) body.booked_on = booked.value;
          const created = await api("/api/appointments", { method: "POST", body });
          toast(`Added ${created.patient_name} (${created.patient_phone || ""}) — ${RISK_LABELS[created.risk_level].toLowerCase()} no-show risk (${Math.round(created.risk_score * 100)}%)`);
          name.value = "";
          phone.value = "";
          if (date.value !== state.date) { state.date = date.value; dateInput.value = date.value; }
          await refresh();
          name.focus();
        } catch (err) {
          showErrors(errorHost, err);
          if (err.message && (err.message.includes("past time or date") || err.message.includes("already booked"))) {
            showCenterModal("Booking Error", err.message);
          }
        } finally {
          submit.disabled = false;
        }
      },
    },
      el("div", { class: "appointment-grid" },
        field("Patient name *", name),
        field("Mobile number *", phone, "", "10-digit Indian mobile (e.g. 9398242064)"),
        field("Appointment date *", date),
        field("Time slot *", time, "", "Clinic hours: 8:00 AM – 5:00 PM"),
        field("Appointment type *", type),
        field("Booked on (optional)", booked, "", "Leave blank for today; used to compute lead time.")
      ),
      el("div", { class: "appointment-actions" },
        submit,
        el("span", { class: "form-required-note" }, "* Required fields")
      ),
      errorHost
    );

    // Bulk paste
    const area = el("textarea", { id: "bulk-text", spellcheck: "false", "aria-describedby": "bulk-hint",
      placeholder: "Asha Rao, 09:00, checkup, 9876543210\nBen Cole, 09:30, follow-up, 9398242064\nCara Dey, 10:15, lab_test" });
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

        const now = new Date();
        const todayStr = localISODate(now);
        const currentHours = String(now.getHours()).padStart(2, "0");
        const currentMinutes = String(now.getMinutes()).padStart(2, "0");
        const currentTime = `${currentHours}:${currentMinutes}`;

        if (state.date < todayStr) {
          const msg = "You cannot enter or book appointments for past dates.";
          showCenterModal("Past Date Not Allowed", msg);
          showLineErrors(bulkErrors, [msg]);
          return;
        }
        if (state.date === todayStr) {
          const pastRows = parsed.rows.filter((r) => r.appointment_time < currentTime);
          if (pastRows.length) {
            const list = pastRows.map((r) => `${r.patient_name} at ${r.appointment_time}`).join(", ");
            const msg = `You cannot enter or book appointments for past times or dates. The following slots have already passed today (current time: ${currentTime}): ${list}.`;
            showCenterModal("Past Time Not Allowed", msg);
            showLineErrors(bulkErrors, [msg]);
            return;
          }
        }

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
          if (err.message && (err.message.includes("past time or date") || err.message.includes("already booked"))) {
            showCenterModal("Booking Error", err.message);
          }
        } finally {
          bulkSubmit.disabled = false;
        }
      },
    },
      el("div", { class: "field" },
        el("label", { for: "bulk-text" }, "Paste appointments list"),
        area,
        el("span", { id: "bulk-hint", class: "hint" }, "One per line: Name, Time (HH:MM), Type (optional), Mobile (optional). Uses date selected above.")),
      el("div", { class: "appointment-actions" }, bulkSubmit),
      bulkErrors
    );

    // Clean Tab Switcher for Single vs Bulk
    const singleTab = el("button", {
      type: "button",
      class: "tab-btn active",
      onclick: () => switchTab("single"),
    }, "Single appointment");

    const bulkTab = el("button", {
      type: "button",
      class: "tab-btn",
      onclick: () => switchTab("bulk"),
    }, "Bulk paste (batch)");

    const tabContainer = el("div", { class: "tab-nav" }, singleTab, bulkTab);
    bulk.hidden = true;

    function switchTab(mode) {
      if (mode === "single") {
        singleTab.classList.add("active");
        bulkTab.classList.remove("active");
        form.hidden = false;
        bulk.hidden = true;
      } else {
        bulkTab.classList.add("active");
        singleTab.classList.remove("active");
        form.hidden = true;
        bulk.hidden = false;
      }
    }

    // Past date notification banner
    const pastBannerText = el("div", { class: "past-date-text" });
    const returnTodayBtn = el("button", {
      type: "button",
      class: "btn btn-small btn-primary",
      onclick: () => {
        state.date = localISODate();
        dateInput.value = state.date;
        state.page = 1;
        updateFormState();
        refresh();
      },
    }, "Return to Today");

    const pastDateBanner = el("div", { class: "past-date-banner", hidden: true },
      el("div", { class: "past-date-badge" }, lockSvg()),
      pastBannerText,
      returnTodayBtn
    );

    const formCard = el("section", { class: "card appointment-schedule-card", "aria-labelledby": "sched-heading" },
      el("div", { class: "card-header-tabs" },
        el("h2", { id: "sched-heading" }, "Schedule appointment"),
        tabContainer
      ),
      pastDateBanner,
      form,
      bulk
    );

    updateFormState = () => {
      const isPast = state.date < localISODate();
      if (isPast) {
        pastDateBanner.hidden = false;
        pastBannerText.replaceChildren(
          el("strong", {}, `Appointment booking disabled for past dates (${prettyDate(state.date)})`),
          el("p", { class: "muted", style: "margin: 2px 0 0;" }, "You are reviewing historical records. Existing visits can be reconciled or inspected below. To schedule a new appointment, switch to Today or an upcoming date.")
        );
        formCard.classList.add("card-disabled");
        name.disabled = true;
        phone.disabled = true;
        date.disabled = true;
        time.disabled = true;
        type.disabled = true;
        booked.disabled = true;
        submit.disabled = true;
        submit.classList.add("btn-disabled");
        area.disabled = true;
        bulkSubmit.disabled = true;
        bulkSubmit.classList.add("btn-disabled");
      } else {
        pastDateBanner.hidden = true;
        formCard.classList.remove("card-disabled");
        name.disabled = false;
        phone.disabled = false;
        date.disabled = false;
        date.value = state.date;
        date.min = localISODate();
        time.disabled = false;
        type.disabled = false;
        booked.disabled = false;
        submit.disabled = false;
        submit.classList.remove("btn-disabled");
        area.disabled = false;
        bulkSubmit.disabled = false;
        bulkSubmit.classList.remove("btn-disabled");
      }
    };

    updateFormState();

    return formCard;
  }

  // ---- list --------------------------------------------------------------
  async function refresh(notify = false) {
    try {
      const data = await api(`/api/appointments?date=${state.date}&limit=500`);
      state.items = data.items;
      state.total = data.total;
      renderList();
      if (notify) toast("Appointments list refreshed");
    } catch (err) {
      clear(listHost).append(el("div", { class: "alert error", role: "alert" }, err.message));
    }
  }

  function renderList() {
    const items = state.items;
    const totalItems = items.length;
    const totalPages = Math.max(1, Math.ceil(totalItems / PAGE_SIZE));
    if (state.page > totalPages) state.page = totalPages;
    if (state.page < 1) state.page = 1;

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

    const startIdx = (state.page - 1) * PAGE_SIZE;
    const pageItems = items.slice(startIdx, startIdx + PAGE_SIZE);

    const rowToggles = [];
    let allRevealed = false;

    const headerEyeBtn = el("button", {
      type: "button",
      class: "btn-eye btn-eye-header",
      title: "Click to reveal all mobile numbers",
      "aria-label": "Toggle all mobile numbers visibility",
      onclick: () => {
        allRevealed = !allRevealed;
        rowToggles.forEach((fn) => fn(allRevealed));
        headerEyeBtn.replaceChildren(allRevealed ? eyeClosedSvg() : eyeOpenSvg());
        headerEyeBtn.title = allRevealed ? "Click to mask all mobile numbers" : "Click to reveal all mobile numbers";
      },
    }, eyeOpenSvg());

    const mobileTh = el("th", { scope: "col", class: "th-mobile" },
      el("div", { class: "th-content" }, "Mobile", headerEyeBtn)
    );

    const theadRow = el("tr", {},
      el("th", { scope: "col" }, "Time"),
      el("th", { scope: "col" }, "Patient"),
      mobileTh,
      el("th", { scope: "col" }, "Type"),
      el("th", { scope: "col" }, "No-show risk"),
      el("th", { scope: "col" }, "Status"),
      canWrite ? el("th", { scope: "col", class: "num" }, "Reconcile") : null
    );

    const tableWrap = el("div", { class: "table-wrap" }, el("table", {},
      el("caption", { class: "sr-only" }, "Appointments"),
      el("thead", {}, theadRow),
      el("tbody", {}, pageItems.map((a) => row(a, rowToggles)))));

    const elements = [tableWrap];

    if (totalItems > PAGE_SIZE) {
      const paginationBar = el("div", { class: "pagination-bar" });
      const infoText = el("div", { class: "pagination-info" },
        `Showing ${startIdx + 1}–${Math.min(startIdx + PAGE_SIZE, totalItems)} of ${totalItems} appointments`
      );

      const prevPageBtn = el("button", {
        type: "button",
        class: "btn btn-quiet btn-small",
        disabled: state.page <= 1,
        onclick: () => { if (state.page > 1) { state.page--; renderList(); } },
        "aria-label": "Previous page",
      }, "‹ Previous");

      const nextPageBtn = el("button", {
        type: "button",
        class: "btn btn-quiet btn-small",
        disabled: state.page >= totalPages,
        onclick: () => { if (state.page < totalPages) { state.page++; renderList(); } },
        "aria-label": "Next page",
      }, "Next ›");

      const pageNumbers = el("div", { class: "pagination-pages" });
      for (let p = 1; p <= totalPages; p++) {
        const pageBtn = el("button", {
          type: "button",
          class: `btn-page${p === state.page ? " active" : ""}`,
          onclick: () => { state.page = p; renderList(); },
          "aria-label": `Page ${p}`,
        }, String(p));
        pageNumbers.append(pageBtn);
      }

      const controls = el("div", { class: "pagination-controls" }, prevPageBtn, pageNumbers, nextPageBtn);
      paginationBar.append(infoText, controls);
      elements.push(paginationBar);
    }

    listHost.append(...elements);
  }

  function lockSvg() {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", "16");
    svg.setAttribute("height", "16");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("x", "3");
    rect.setAttribute("y", "11");
    rect.setAttribute("width", "18");
    rect.setAttribute("height", "11");
    rect.setAttribute("rx", "2");
    rect.setAttribute("ry", "2");
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", "M7 11V7a5 5 0 0 1 10 0v4");
    svg.append(rect, path);
    return svg;
  }

  function eyeOpenSvg() {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", "14");
    svg.setAttribute("height", "14");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
    p.setAttribute("d", "M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z");
    const c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    c.setAttribute("cx", "12");
    c.setAttribute("cy", "12");
    c.setAttribute("r", "3");
    svg.append(p, c);
    return svg;
  }

  function eyeClosedSvg() {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", "14");
    svg.setAttribute("height", "14");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
    p.setAttribute("d", "M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24");
    const l = document.createElementNS("http://www.w3.org/2000/svg", "line");
    l.setAttribute("x1", "1");
    l.setAttribute("y1", "1");
    l.setAttribute("x2", "23");
    l.setAttribute("y2", "23");
    svg.append(p, l);
    return svg;
  }

  function maskPhone(p) {
    if (!p) return "";
    const clean = p.trim();
    const digits = clean.replace(/\D/g, "");
    if (digits.length <= 4) return "•••• " + digits;

    // For 10-digit Indian numbers (e.g. 9398242064):
    if (digits.length === 10) {
      return `+91 ${digits.slice(0, 2)}••• ••${digits.slice(-3)}`;
    }
    // For 12-digit Indian numbers starting with 91:
    if (digits.length === 12 && digits.startsWith("91")) {
      return `+91 ${digits.slice(2, 4)}••• ••${digits.slice(-3)}`;
    }
    const last4 = digits.slice(-4);
    const prefix = clean.startsWith("+") ? "+ " : "";
    return `${prefix}•••• ••• ${last4}`;
  }

  function phoneCell(rawPhone, rowToggles) {
    if (!rawPhone) return el("span", { class: "muted" }, "—");

    const masked = maskPhone(rawPhone);
    const textSpan = el("span", { class: "phone-text" }, masked);
    let isRevealed = false;

    const updateDisplay = () => {
      textSpan.textContent = isRevealed ? rawPhone : masked;
      eyeBtn.replaceChildren(isRevealed ? eyeClosedSvg() : eyeOpenSvg());
      eyeBtn.title = isRevealed ? "Click to mask mobile number" : "Click to reveal mobile number";
      eyeBtn.setAttribute("aria-label", isRevealed ? "Mask mobile number" : "Reveal mobile number");
    };

    const eyeBtn = el("button", {
      type: "button",
      class: "btn-eye",
      title: "Click to reveal mobile number",
      "aria-label": "Reveal mobile number",
      onclick: (e) => {
        e.stopPropagation();
        isRevealed = !isRevealed;
        updateDisplay();
      },
    }, eyeOpenSvg());

    if (rowToggles) {
      rowToggles.push((forceState) => {
        isRevealed = forceState !== undefined ? forceState : !isRevealed;
        updateDisplay();
      });
    }

    return el("div", { class: "phone-cell" }, textSpan, eyeBtn);
  }

  function row(a, rowToggles) {
    const risk = a.risk_score === null ? "—" : `${RISK_LABELS[a.risk_level]} · ${Math.round(a.risk_score * 100)}%`;
    return el("tr", { dataset: { id: a.id } },
      el("td", { class: "num" }, a.appointment_time),
      el("td", {}, a.patient_name),
      el("td", {}, phoneCell(a.patient_phone, rowToggles)),
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
