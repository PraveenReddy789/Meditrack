import { api, request } from "../api.js";
import { dailyChart, rateChart } from "../charts.js";
import { addDays, clear, el, localISODate, num1, pct, prettyDate, toast } from "../dom.js";

export function mountDashboard(root, ctx) {
  const state = { days: 30 };
  const body = el("div");
  const select = el("select", { id: "range", "aria-label": "Time range" },
    [[7, "Last 7 days"], [14, "Last 14 days"], [30, "Last 30 days"], [90, "Last 90 days"]]
      .map(([v, l]) => el("option", { value: v, selected: v === state.days }, l)));
  select.addEventListener("change", () => { state.days = Number(select.value); load(); });

  const exportKind = el("select", { id: "export-kind", "aria-label": "Report type" },
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

  root.append(
    el("div", { class: "page-head" },
      el("div", {}, el("h1", {}, "Dashboard"), el("p", { class: "muted" }, "No-shows so far, what the model expects, and how the rate is trending.")),
      el("div", { class: "form-row" }, select, exportKind, exportBtn)),
    body);

  async function load() {
    try {
      const data = await api(`/api/dashboard?days=${state.days}`);
      render(data);
    } catch (err) {
      clear(body).append(el("div", { class: "alert error", role: "alert" }, err.message));
    }
  }

  function kpi(label, value, sub) {
    return el("div", { class: "card kpi" }, el("div", { class: "label" }, label), el("div", { class: "value" }, value), el("div", { class: "sub" }, sub));
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
    clear(body).append(
      el("div", { class: "grid cols-4" },
        kpi("No-shows", s.no_shows, `${s.reconciled} reconciled visit${s.reconciled === 1 ? "" : "s"}`),
        kpi("No-show rate", pct(s.no_show_rate), "of reconciled visits"),
        kpi("Predicted no-shows", num1(s.expected_no_shows), `${s.flagged} flagged high-risk`),
        kpi("Today", `${d.today.no_shows} / ${d.today.total}`, `${d.today.scheduled} still to reconcile`)),

      el("section", { class: "card" },
        el("h2", {}, "No-shows per day"),
        el("div", { class: "legend" },
          el("span", {}, el("span", { class: "swatch actual" }), "Actual no-shows"),
          el("span", {}, el("span", { class: "swatch expected" }), "Model expected")),
        dailyChart(d.trend)),

      el("section", { class: "card" },
        el("h2", {}, "No-show rate trend"),
        el("div", { class: "legend" }, el("span", {}, el("span", { class: "swatch rate" }), "Rolling 7-day rate")),
        rateChart(d.trend)),

      el("div", { class: "grid cols-2" },
        el("section", { class: "card" }, el("h2", {}, "Next 7 days"),
          el("div", { class: "table-wrap" }, el("table", {},
            el("thead", {}, el("tr", {}, el("th", { scope: "col" }, "Day"), el("th", { scope: "col", class: "num" }, "Booked"), el("th", { scope: "col", class: "num" }, "Expected no-shows"), el("th", { scope: "col", class: "num" }, "High-risk"))),
            el("tbody", {}, d.upcoming.map((u) => el("tr", {},
              el("td", {}, prettyDate(u.date)), el("td", { class: "num" }, u.total), el("td", { class: "num" }, num1(u.expected_no_shows)), el("td", { class: "num" }, u.flagged))))))),

        el("section", { class: "card" }, el("h2", {}, "How good are the predictions?"),
          q.tp + q.fp + q.fn + q.tn === 0
            ? el("p", { class: "empty" }, "Appears once visits have been marked attended or no-show.")
            : el("div", {},
              el("dl", { class: "facts" },
                el("dt", {}, "Caught"), el("dd", {}, `${pct(q.recall, 0)} of real no-shows were flagged`),
                el("dt", {}, "Precision"), el("dd", {}, `${pct(q.precision, 0)} of flags were real no-shows`),
                el("dt", {}, "Accuracy"), el("dd", {}, pct(q.accuracy, 0))),
              el("div", { class: "confusion" },
                el("div", {}, el("b", {}, q.tp), "flagged, no-show"), el("div", {}, el("b", {}, q.fp), "flagged, attended"),
                el("div", {}, el("b", {}, q.fn), "missed no-shows"), el("div", {}, el("b", {}, q.tn), "not flagged, attended"))),
          el("p", { class: "hint" }, `Model ${d.model.version} · alert threshold ${Math.round(d.model.threshold * 100)}%`))),

      el("div", { class: "grid cols-2" },
        breakdownTable("By appointment type", d.by_type.map((r) => ({ ...r, label: r.label.replace("_", " ") })), "Type"),
        breakdownTable("By weekday", d.by_weekday, "Day")),
      breakdownTable("By hour of day", d.by_hour, "Hour"),

      el("p", { class: "hint" }, `Updated ${new Date(d.generated_at).toLocaleTimeString()} · results are cached briefly and refreshed after every change.`));
  }

  load();
}
