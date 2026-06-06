from pathlib import Path

ROOT = Path(__file__).resolve().parent
app = ROOT / "app.js"
styles = ROOT / "styles.css"

text = app.read_text(encoding="utf-8")
old = '''  const packingOpen = goodsDone && !submitted;
  const finalOpen = packingOpen && packingDone;
  els.packingEntryStep.classList.toggle("hidden", !packingOpen);
  els.finalPackingStep.classList.toggle("hidden", !finalOpen);
  els.packingEntryStatusLabel.textContent = !goodsDone ? "Locked" : packingDone ? "Done" : "Open";
  els.finalPackingStatusLabel.textContent = !packingDone ? "Locked" : finalDone ? "Done" : "Open";
  els.goodsCheckStatusLabel.textContent = goodsDone ? "Done" : "Open";
  [els.packingCameraButton, els.packingCameraInput, els.packingFileInput, els.submitReviewButton].forEach((control) => {
    if (control) control.disabled = !finalOpen;
  });
'''
new = '''  const packingOpen = goodsDone && !submitted;
  const finalOpen = packingOpen && packingDone;
  const activeStep = submitted ? "submitted" : !goodsDone ? "goods" : !packingDone ? "packing" : "final";

  // Mobile-worker mode: show one working step at a time. Progress stays visible in chips.
  els.goodsCheckSection.classList.toggle("hidden", activeStep !== "goods");
  els.packingForm.classList.toggle("hidden", activeStep === "goods" || activeStep === "submitted");
  els.packingEntryStep.classList.toggle("hidden", activeStep !== "packing");
  els.finalPackingStep.classList.toggle("hidden", activeStep !== "final");

  els.packingEntryStatusLabel.textContent = !goodsDone ? "Locked" : packingDone ? "Done" : "Open";
  els.finalPackingStatusLabel.textContent = !packingDone ? "Locked" : finalDone ? "Done" : "Open";
  els.goodsCheckStatusLabel.textContent = goodsDone ? "Done" : "Open";
  [els.packingCameraButton, els.packingCameraInput, els.packingFileInput, els.submitReviewButton].forEach((control) => {
    if (control) control.disabled = activeStep !== "final";
  });
'''
if new not in text:
    if old not in text:
        raise SystemExit("Target dispatcher step block not found")
    text = text.replace(old, new)
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
#finalPackingStep.hidden {
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
