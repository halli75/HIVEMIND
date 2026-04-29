import type { InferenceBudget } from "../types";

export function InferenceMetrics({ budget }: { budget: InferenceBudget }) {
  const aiqPct = Math.min(100, (budget.aiqSlotsActive / Math.max(1, budget.aiqSlotsTotal)) * 100);
  const callsPct = Math.min(100, (budget.callsThisTick / Math.max(1, budget.cap)) * 100);

  return (
    <section className="panel inference-panel" aria-labelledby="inference-heading">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">0G inference</p>
          <h2 id="inference-heading">Compute budget</h2>
        </div>
      </div>
      <div className="inference-body">
        <div className="inference-row">
          <div className="inference-row-head">
            <span>AIQ slots active</span>
            <strong>
              {budget.aiqSlotsActive}/{budget.aiqSlotsTotal}
            </strong>
          </div>
          <div className="inference-bar" role="progressbar" aria-valuemin={0} aria-valuemax={budget.aiqSlotsTotal} aria-valuenow={budget.aiqSlotsActive}>
            <span className="inference-bar-fill aiq" style={{ width: `${aiqPct}%` }} />
          </div>
        </div>
        <div className="inference-row">
          <div className="inference-row-head">
            <span>Inference budget (this tick)</span>
            <strong>
              {budget.callsThisTick}/{budget.cap}
            </strong>
          </div>
          <div className="inference-bar" role="progressbar" aria-valuemin={0} aria-valuemax={budget.cap} aria-valuenow={budget.callsThisTick}>
            <span className="inference-bar-fill calls" style={{ width: `${callsPct}%` }} />
          </div>
        </div>
        <div className="inference-row">
          <div className="inference-row-head">
            <span>Avg calls / tick</span>
            <strong>{budget.callsPerTickAvg.toFixed(2)}</strong>
          </div>
        </div>
      </div>
    </section>
  );
}
