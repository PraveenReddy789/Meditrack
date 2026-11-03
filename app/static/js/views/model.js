import { api } from "../api.js";
import { clear, el, pct, toast } from "../dom.js";

export function mountModel(root, ctx) {
  const canTrain = ctx.user.permissions.includes("model:train");
  const body = el("div");
  root.append(
    el("div", { class: "page-head" },
      el("div", {}, el("h1", {}, "Prediction model"),
        el("p", { class: "muted" }, "How no-shows are predicted, how well it works, and what it costs in speed."))),
    body);

  async function load() {
    try {
      render(await api("/api/model"));
    } catch (err) {
      clear(body).append(el("div", { class: "alert error", role: "alert" }, err.message));
    }
  }

  function render(m) {
    const retrain = el("button", { type: "button", class: "btn" }, "Retrain on reconciled data");
    retrain.addEventListener("click", async () => {
      retrain.disabled = true;
      try {
        const r = await api("/api/model/retrain", { method: "POST" });
        toast(`Retrained (AUC ${r.metrics.auc.toFixed(3)}); ${r.rescored_appointments} upcoming appointment${r.rescored_appointments === 1 ? "" : "s"} re-scored`);
        await load();
      } catch (err) {
        toast(err.message, { error: true });
        retrain.disabled = false;
      }
    });

    clear(body).append(
      el("div", { class: "grid cols-2" },
        el("section", { class: "card" }, el("h2", {}, "Current model"),
          el("dl", { class: "facts" },
            el("dt", {}, "Version"), el("dd", {}, m.version),
            el("dt", {}, "Algorithm"), el("dd", {}, m.kind === "logistic" ? "Logistic regression (fast, explainable)" : "Gradient boosting (more flexible, slower)"),
            el("dt", {}, "Trained"), el("dd", {}, new Date(m.trained_at).toLocaleString()),
            el("dt", {}, "Training data"), el("dd", {}, `${m.n_synthetic.toLocaleString()} simulated + ${m.n_real.toLocaleString()} real reconciled visits`),
            el("dt", {}, "Alert threshold"), el("dd", {}, `${Math.round(m.threshold * 100)}% risk (flags high-risk)`),
            el("dt", {}, "Baseline no-show rate"), el("dd", {}, pct(m.base_rate))),
          canTrain ? el("p", {}, retrain) : el("p", { class: "hint" }, "Only an administrator can retrain the model.")),

        el("section", { class: "card" }, el("h2", {}, "Accuracy on held-out data"),
          el("dl", { class: "facts" },
            el("dt", {}, "AUC"), el("dd", {}, m.metrics.auc.toFixed(3)),
            el("dt", {}, "Recall"), el("dd", {}, pct(m.metrics.recall, 0)),
            el("dt", {}, "Precision"), el("dd", {}, pct(m.metrics.precision, 0)),
            el("dt", {}, "F1"), el("dd", {}, m.metrics.f1.toFixed(3)),
            el("dt", {}, "Brier score"), el("dd", {}, m.metrics.brier.toFixed(3))),
          el("p", { class: "hint" }, `Measured on ${m.metrics.test_rows.toLocaleString()} rows the model never trained on. Early on these numbers describe the simulated baseline, not your clinic.`))),

      el("div", { class: "grid cols-2" },
        el("section", { class: "card" }, el("h2", {}, "Speed"),
          el("dl", { class: "facts" },
            el("dt", {}, "Prediction"), el("dd", {}, `${m.single_predict_ms.toFixed(2)} ms per appointment`),
            el("dt", {}, "Training"), el("dd", {}, `${m.train_seconds.toFixed(2)} s`)),
          el("p", { class: "hint" }, "Every appointment is scored the moment it is saved, so prediction speed is what staff feel.")),
        el("section", { class: "card" }, el("h2", {}, "What drives risk"),
          m.top_features.length
            ? el("ul", {}, m.top_features.map((f) => el("li", {}, `${f.feature.replaceAll("_", " ")}: ${f.weight > 0 ? "raises" : "lowers"} risk (${f.weight > 0 ? "+" : ""}${f.weight})`)))
            : el("p", { class: "empty" }, "This algorithm doesn't expose simple per-feature weights."))));
  }

  load();
}
