import { api, request } from "../api.js";
import { dailyChart, rateChart } from "../charts.js";
import { addDays, clear, el, localISODate, num1, pct, prettyDate, toast } from "../dom.js";

export function mountDashboard(root, ctx) {
  const state = { days: 30 };
  const body = el("div");
  const select = el("select", { id: "range", class: "control-select", "aria-label": "Time range" },
    [[7, "Last 7 days"], [14, "Last 14 days"], [30, "Last 30 days"], [90, "Last 90 days"]]
      .map(([v, l]) => el("option", { value: v, selected: v === state.days }, l)));
  select.addEventListener("change", () => { state.days = Number(select.value); load(); });

  const exportKind = el("select", { id: "export-kind", class: "control-select", "aria-label": "Report type" },
    el("option", { value: "appointments" }, "Every appointment"),
    el("option", { value: "daily" }, "Daily summary"));
  const exportBtn = el("button", { type: "button", class: "btn" }, "Export CSV");
  exportBtn.addEventListener("click", async () => {
    exportBtn.disabled = true;
    try {
      const end = localISODate();
      const start = addDays(end, -(state.days - 1));
      const kind = exportKind.value;
      const { res, data } = await request(`/api/reports/no-show.csv?kind=${kind}&start=${start}&end=${end}`);
      const match = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") || "");
      const link = el("a", { href: URL.createObjectURL(data), download: match ? match[1] : `meditrack-${kind}.csv` });
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(link.href), 1000);
      toast("Report downloaded");
    } catch (err) {
      toast(err.message, { error: true });
    } finally {
      exportBtn.disabled = false;
    }
  });

  const refreshBtn = el("button", { type: "button", class: "btn btn-quiet", onclick: () => load(true), "aria-label": "Refresh dashboard data" }, "Refresh");

  const displayName = ctx?.user?.username ? (ctx.user.username.charAt(0).toUpperCase() + ctx.user.username.slice(1)) : "Staff";

  const toolbar = el("div", { class: "dashboard-toolbar" },
    select,
    exportKind,
    exportBtn,
    refreshBtn);

  root.append(
    el("div", { class: "page-head" },
      el("div", { class: "page-head-title" },
        el("h1", {}, `Good morning, Dr. ${displayName}`),
        el("p", { class: "muted" }, "Your clinic shift: 8:00 am – 5:00 pm · Real-time AI No-Show Reconciliation")),
      toolbar),
    body);

  async function load(notify = false) {
    try {
      const data = await api(`/api/dashboard?days=${state.days}`);
      render(data);
      if (notify) toast("Dashboard refreshed");
    } catch (err) {
      clear(body).append(el("div", { class: "alert error", role: "alert" }, err.message));
    }
  }

  function kpi(label, value, sub, tag = "") {
    return el("div", { class: "card kpi" },
      el("div", { class: "kpi-header" },
        el("span", { class: "label" }, label),
        tag ? el("span", { class: "kpi-tag" }, tag) : null),
      el("div", { class: "value" }, value),
      el("div", { class: "sub" }, sub));
  }

  function heroKpi(label, value, sub, percent) {
    return el("div", { class: "card kpi card-hero" },
      el("div", { class: "kpi-header" },
        el("span", { class: "label" }, label),
        el("span", { class: "kpi-tag hero" }, `${percent}% Done`)),
      el("div", { class: "value" }, value),
      el("div", { class: "hero-meter" },
        el("div", { class: "hero-meter-bar", style: `width: ${percent}%;` })),
      el("div", { class: "sub" }, sub));
  }

  function breakdownTable(title, rows, labelHeader) {
    return el("section", { class: "card" }, el("h2", {}, title),
      rows.length
        ? el("div", { class: "table-wrap" }, el("table", {},
          el("thead", {}, el("tr", {}, el("th", { scope: "col" }, labelHeader), el("th", { scope: "col", class: "num" }, "Visits"), el("th", { scope: "col", class: "num" }, "No-shows"), el("th", { scope: "col" }, "Rate"))),
          el("tbody", {}, rows.map((r) => el("tr", {},
            el("td", {}, r.label), el("td", { class: "num" }, r.reconciled), el("td", { class: "num" }, r.no_shows),
            el("td", {}, el("meter", { min: 0, max: 1, value: r.no_show_rate ?? 0, "aria-label": `${r.label} no-show rate` }), " ", pct(r.no_show_rate, 0)))))))
        : el("p", { class: "empty" }, "No reconciled visits in this range."));
  }

  function render(d) {
    const s = d.summary;
    const q = d.prediction_quality;

    const reconciledToday = d.today.attended + d.today.no_shows;
    const todayPct = d.today.total > 0 ? Math.round((reconciledToday / d.today.total) * 100) : 0;

    clear(body).append(
      el("div", { class: "grid cols-4" },
        heroKpi("Visits Today", `${reconciledToday} / ${d.today.total}`, `${d.today.scheduled} pending reconciliation · ${d.today.no_shows} no-show`, todayPct),
        kpi("Reconciled Visits", s.reconciled, `${s.attended} attended · ${s.no_shows} no-shows`, "Historical"),
        kpi("Predicted No-Shows", num1(s.expected_no_shows), `${s.flagged} flagged high-risk`, "AI Alert"),
        kpi("Clinic No-Show Rate", pct(s.no_show_rate), "of reconciled appointments", "Overall")),

      el("section", { class: "card chart-card" },
        el("div", { class: "card-title-row" },
          el("h2", {}, "Daily Appointments & AI Expectations"),
          el("div", { class: "legend" },
            el("span", {}, el("span", { class: "swatch actual" }), "Actual no-shows"),
            el("span", {}, el("span", { class: "swatch expected" }), "Model expected"))),
        dailyChart(d.trend)),

      el("section", { class: "card chart-card" },
        el("div", { class: "card-title-row" },
          el("h2", {}, "Rolling 7-Day No-Show Rate Trend"),
          el("div", { class: "legend" },
            el("span", {}, el("span", { class: "swatch rate" }), "Rolling 7-day rate"))),
        rateChart(d.trend)),

      el("div", { class: "grid cols-2" },
        el("section", { class: "card" }, el("h2", {}, "Upcoming Visits (Next 7 Days)"),
          el("div", { class: "table-wrap" }, el("table", {},
            el("thead", {}, el("tr", {}, el("th", { scope: "col" }, "Day"), el("th", { scope: "col", class: "num" }, "Booked"), el("th", { scope: "col", class: "num" }, "Expected No-Shows"), el("th", { scope: "col", class: "num" }, "High-Risk"))),
            el("tbody", {}, d.upcoming.map((u) => el("tr", {},
              el("td", {}, prettyDate(u.date)), el("td", { class: "num" }, u.total), el("td", { class: "num" }, num1(u.expected_no_shows)), el("td", { class: "num" }, u.flagged))))))),

        el("section", { class: "card" }, el("h2", {}, "Model Prediction Quality"),
          q.tp + q.fp + q.fn + q.tn === 0
            ? el("p", { class: "empty" }, "Appears once visits have been marked attended or no-show.")
            : el("div", {},
              el("dl", { class: "facts" },
                el("dt", {}, "Caught (Recall)"), el("dd", {}, `${pct(q.recall, 0)} of real no-shows were flagged`),
                el("dt", {}, "Precision"), el("dd", {}, `${pct(q.precision, 0)} of flags were real no-shows`),
                el("dt", {}, "Accuracy"), el("dd", {}, pct(q.accuracy, 0))),
              el("div", { class: "confusion" },
                el("div", { class: "tile tp" }, el("span", { class: "tile-val" }, q.tp), el("span", { class: "tile-lbl" }, "Flagged, No-Show")),
                el("div", { class: "tile fp" }, el("span", { class: "tile-val" }, q.fp), el("span", { class: "tile-lbl" }, "Flagged, Attended")),
                el("div", { class: "tile fn" }, el("span", { class: "tile-val" }, q.fn), el("span", { class: "tile-lbl" }, "Missed No-Shows")),
                el("div", { class: "tile tn" }, el("span", { class: "tile-val" }, q.tn), el("span", { class: "tile-lbl" }, "Not Flagged, Attended")))),
          el("p", { class: "hint" }, `Model ${d.model.version} · alert threshold ${Math.round(d.model.threshold * 100)}%`))),

      el("div", { class: "grid cols-2" },
        breakdownTable("By Appointment Type", d.by_type.map((r) => ({ ...r, label: r.label.replace("_", " ") })), "Type"),
        breakdownTable("By Weekday", d.by_weekday, "Day")),
      breakdownTable("By Clinic Hour (8:00 AM – 5:00 PM)", d.by_hour, "Hour"),

      el("p", { class: "hint" }, `Updated ${new Date(d.generated_at).toLocaleTimeString()} · results are cached briefly and refreshed after every change.`));
  }

  load();
}
