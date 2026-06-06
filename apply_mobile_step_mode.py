from pathlib import Path

ROOT = Path(__file__).resolve().parent
app = ROOT / "app.js"
styles = ROOT / "styles.css"

text = app.read_text(encoding="utf-8")
call_anchor = "  renderExceptionSummary();\n  const untouchedClaim"
if "updateDispatcherMobileStepMode(job);" not in text:
    if call_anchor not in text:
        raise SystemExit("renderDispatcherDetail anchor not found")
    text = text.replace(call_anchor, "  renderExceptionSummary();\n  updateDispatcherMobileStepMode(job);\n  const untouchedClaim")

sync_anchor = "  els.shortageItemsWrap.classList.toggle(\"hidden\", !(mismatch && (job?.billItems || []).length));\n}"
if "updateDispatcherMobileStepMode(job);\n}" not in text:
    if sync_anchor not in text:
        raise SystemExit("syncPackingTotals anchor not found")
    text = text.replace(sync_anchor, "  els.shortageItemsWrap.classList.toggle(\"hidden\", !(mismatch && (job?.billItems || []).length));\n  updateDispatcherMobileStepMode(job);\n}")

function_anchor = "function goodsStageLabel(status) {"
controller = r'''
function renderDispatcherStepTracker(steps) {
  if (!els.dispatcherStepTracker) return;
  els.dispatcherStepTracker.innerHTML = steps.map((step, index) => `
    <div class="dispatcher-step-chip ${step.state}">
      <span>${index + 1}</span>
      <strong>${escapeHtml(step.label)}</strong>
    </div>
  `).join("");
}

function updateDispatcherMobileStepMode(job = byId(state.selectedDispatcherJobId)) {
  if (!job || !els.goodsCheckSection || !els.packingEntryStep || !els.finalPackingStep) return;
  const goodsPhotos = job.goodsCheck?.photos || [];
  const packingPhotos = job.packingDetails?.packingPhotos || [];
  const submittedStatuses = ["submitted-for-review", "approved-by-reviewer", "dispatch-pending", "dispatched", "delivered", "completed"];
  const submitted = submittedStatuses.includes(job.currentStatus);
  const goodsDone = goodsPhotos.length > 0 || submitted;
  const lines = collectPackingLines();
  const totals = currentPackingTotals();
  const hasPacking = lines.length > 0;
  const packingMatches = totals.totalPackedCases === Number(job.orderCaseCount || 0);
  const differenceResolved = hasValidItemDifferenceForTotals(job, totals) || hasAdminMismatchOverride(job);
  const packingDone = hasPacking && (packingMatches || differenceResolved || submitted);
  const finalDone = packingPhotos.length > 0 || submitted;
  const activeStep = submitted ? "submitted" : !goodsDone ? "goods" : !packingDone ? "packing" : "final";

  els.goodsCheckSection.classList.toggle("hidden", activeStep !== "goods");
  els.packingForm.classList.toggle("hidden", activeStep === "goods" || activeStep === "submitted");
  els.packingEntryStep.classList.toggle("hidden", activeStep !== "packing");
  els.finalPackingStep.classList.toggle("hidden", activeStep !== "final");
  els.packingProofWrap.classList.toggle("hidden", activeStep !== "final");

  els.goodsCheckStatusLabel.textContent = goodsDone ? "Done" : "Step 1";
  els.packingEntryStatusLabel.textContent = !goodsDone ? "Locked" : packingDone ? "Done" : "Step 2";
  els.finalPackingStatusLabel.textContent = !packingDone ? "Locked" : finalDone ? "Done" : "Step 3";
  if (els.goodsStepHint) {
    els.goodsStepHint.textContent = goodsDone ? "Photo saved. Next step is packing details." : "Take or upload goods photo first.";
  }

  [els.packingCameraButton, els.packingCameraInput, els.packingFileInput, els.submitReviewButton].forEach((control) => {
    if (control) control.disabled = activeStep !== "final";
  });

  renderDispatcherStepTracker([
    { label: "Goods", state: goodsDone ? "done" : "active" },
    { label: "Packing", state: !goodsDone ? "locked" : packingDone ? "done" : "active" },
    { label: "Final", state: !packingDone ? "locked" : finalDone ? "done" : "active" },
  ]);
}

'''
if "function updateDispatcherMobileStepMode" not in text:
    if function_anchor not in text:
        raise SystemExit("goodsStageLabel anchor not found")
    text = text.replace(function_anchor, controller + function_anchor)
app.write_text(text, encoding="utf-8")

css = styles.read_text(encoding="utf-8")
marker = "/* Dispatcher mobile one-step mode */"
if marker not in css:
    css += r'''

/* Dispatcher mobile one-step mode */
#dispatcherDetailContent {
  gap: 12px;
}

#goodsCheckSection:not(.hidden),
#packingEntryStep:not(.hidden),
#finalPackingStep:not(.hidden) {
  border-color: rgba(239, 125, 34, 0.34) !important;
  box-shadow: 0 12px 30px rgba(20, 35, 55, 0.07);
}

#goodsCheckSection.hidden,
#packingEntryStep.hidden,
#finalPackingStep.hidden,
#packingProofWrap.hidden {
  display: none !important;
}

.dispatcher-step-chip.done {
  opacity: 1;
}

.dispatcher-step-chip.locked {
  opacity: 0.42;
}

@media (max-width: 720px) {
  #dispatcherDetailContent {
    gap: 8px;
  }

  .dispatcher-layout .detail-panel {
    position: sticky;
    top: 0;
    z-index: 6;
  }

  .dispatcher-step-tracker {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 6px;
  }

  .dispatcher-step-chip {
    min-height: 36px;
    padding: 6px;
    gap: 5px;
    font-size: 0.72rem;
    justify-content: center;
  }

  .dispatcher-step-chip span {
    width: 20px;
    height: 20px;
  }

  #goodsCheckSection,
  #packingEntryStep,
  #finalPackingStep {
    padding: 12px !important;
  }

  #goodsCheckSection .compact-upload-card,
  #finalPackingStep .compact-upload-card {
    grid-template-columns: 1fr;
  }

  #goodsCheckSection .photo-action-row,
  #finalPackingStep .photo-action-row {
    grid-template-columns: 1fr 1fr;
    width: 100%;
  }

  #bankPackingGrid.bank-packing-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  #bankPackingGrid .bora-card {
    grid-column: 1 / -1;
  }

  #submitReviewButton,
  #packingCameraButton,
  #goodsCameraButton,
  .file-button {
    min-height: 48px;
  }
}
'''
styles.write_text(css, encoding="utf-8")

for temp in [ROOT / "apply_mobile_step_mode.py", ROOT / ".github/workflows/apply-mobile-step-mode.yml"]:
    if temp.exists():
        temp.unlink()
