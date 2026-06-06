from pathlib import Path
import re


def read(path):
    return Path(path).read_text(encoding='utf-8-sig')


def write(path, text):
    Path(path).write_text(text, encoding='utf-8')


html = read('index.html')
html = html.replace('20260603-dispatcher-compact', '20260606-dispatcher-steps')
if 'dispatcherStepTracker' not in html:
    html = html.replace('<div id="dispatcherReadonlyGrid" class="readonly-grid"></div>', '<div id="dispatcherReadonlyGrid" class="readonly-grid"></div>\n                <div id="dispatcherStepTracker" class="dispatcher-step-tracker"></div>')
if 'goodsStepHint' not in html:
    html = html.replace('<span id="goodsCheckStatusLabel" class="soft-pill">Waiting</span>\n                  </div>', '<span id="goodsCheckStatusLabel" class="soft-pill">Waiting</span>\n                  </div>\n                  <p id="goodsStepHint" class="muted-copy">Upload picked-goods photo to unlock packing.</p>')
new_form = '''<form id="packingForm" class="stack-form">
                  <section id="packingEntryStep" class="dispatcher-step-panel">
                    <div class="section-header compact-header">
                      <div><p class="eyebrow">Step 2</p><h4>Packing details</h4></div>
                      <span id="packingEntryStatusLabel" class="soft-pill">Locked</span>
                    </div>
                    <div class="readonly-grid compact-total-grid">
                      <div><span>Total Packages</span><strong id="totalPackagesValue">0</strong></div>
                      <div><span>Total Packed Cases</span><strong id="totalPackedCasesValue">0</strong></div>
                    </div>
                    <div id="bankPackingGrid" class="bank-packing-grid">
                      <label class="bank-pack-card">
                        <span>1 ×</span>
                        <input id="pack1Input" type="number" min="0" inputmode="numeric" />
                        <small>1 case packs</small>
                      </label>
                      <label class="bank-pack-card">
                        <span>2 ×</span>
                        <input id="pack2Input" type="number" min="0" inputmode="numeric" />
                        <small>2 case packs</small>
                      </label>
                      <label class="bank-pack-card">
                        <span>3 ×</span>
                        <input id="pack3Input" type="number" min="0" inputmode="numeric" />
                        <small>3 case packs</small>
                      </label>
                      <label class="bank-pack-card">
                        <span>4 ×</span>
                        <input id="pack4Input" type="number" min="0" inputmode="numeric" />
                        <small>4 case packs</small>
                      </label>
                      <label class="bank-pack-card">
                        <span>5 ×</span>
                        <input id="pack5Input" type="number" min="0" inputmode="numeric" />
                        <small>5 case packs</small>
                      </label>
                      <label class="bank-pack-card bora-card">
                        <span>Bora</span>
                        <input id="boraCasesListInput" inputmode="numeric" placeholder="Cases in each bora: 12,17" />
                        <small>Enter each bora separately</small>
                      </label>
                    </div>
                    <section id="shortageSection" class="warning-panel hidden compact-warning-panel">
                      <div class="section-header compact-header">
                        <div><p class="eyebrow">Item difference</p><h4>Packed cases do not match order</h4></div>
                      </div>
                      <div class="button-row compact-action-row">
                        <button id="openExceptionDialogButton" type="button" class="warning-button">Add Item Difference</button>
                      </div>
                      <div id="exceptionSummaryList" class="exception-summary-list"></div>
                      <label class="field"><span>Overall Note</span><textarea id="shortageNoteInput" rows="1"></textarea></label>
                      <div id="shortageItemsWrap" class="hidden compact-difference-help">
                        <div id="shortageBillItems" class="shortage-item-list"></div>
                        <div id="shortageSelectedItems" class="shortage-selected-list"></div>
                      </div>
                    </section>
                  </section>
                  <section id="finalPackingStep" class="dispatcher-step-panel">
                    <div class="section-header compact-header">
                      <div><p class="eyebrow">Step 3</p><h4>Final packing photo</h4></div>
                      <span id="finalPackingStatusLabel" class="soft-pill">Locked</span>
                    </div>
                    <div id="packingProofWrap" class="proof-grid single-proof-grid compact-proof-wrap">
                      <section class="upload-card compact-upload-card">
                        <span>Final Packing Photo</span>
                        <strong id="packingPhotoLabel">Upload packing photos</strong>
                        <div class="button-row photo-action-row">
                          <button id="packingCameraButton" type="button" class="secondary-button">Take Photo</button>
                          <label class="secondary-button file-button">Upload File<input id="packingFileInput" type="file" accept="image/*" multiple /></label>
                        </div>
                        <input id="packingCameraInput" class="native-file-input" type="file" accept="image/*" capture="environment" />
                        <div id="packingPhotoPreviewGrid" class="photo-preview-grid compact-photo-grid"></div>
                      </section>
                    </div>
                    <label class="field note-field"><span>Dispatcher Note</span><textarea id="dispatcherNoteInput" rows="1"></textarea><button id="dispatcherNoteMicButton" type="button" class="mic-button" data-mic-target="dispatcherNoteInput">Mic</button></label>
                    <div class="button-row">
                      <button id="unassignJobButton" type="button" class="secondary-button hidden">Unassign</button>
                      <button id="submitReviewButton" type="button" class="primary-button">Submit for Review</button>
                    </div>
                  </section>
                </form>'''
html = re.sub(r'<form id="packingForm" class="stack-form">.*?</form>', new_form, html, count=1, flags=re.S)
write('index.html', html)

app = read('app.js')
old = '''const goodsReady = goodsPhotos.length > 0;
  const goodsSatisfied = goodsReady || ["submitted-for-review", "approved-by-reviewer", "dispatch-pending", "dispatched", "delivered", "completed"].includes(job.currentStatus);
  els.goodsCheckSection.classList.toggle("completed-step", goodsSatisfied);
  els.goodsCheckSection.querySelector(".muted-copy").textContent = goodsSatisfied
    ? "Picked-goods photo uploaded. Continue with packing."
    : "You can prepare packing now. Picked-goods photo is still required before submit.";
  els.packingForm.classList.toggle("hidden", !packingVisible);
  els.packingProofWrap.classList.toggle("hidden", !packingVisible);'''
new = '''const goodsReady = goodsPhotos.length > 0;
  const finishedStatuses = ["submitted-for-review", "approved-by-reviewer", "dispatch-pending", "dispatched", "delivered", "completed"];
  const goodsSatisfied = goodsReady || finishedStatuses.includes(job.currentStatus);
  els.goodsCheckSection.classList.toggle("completed-step", goodsSatisfied);
  els.goodsCheckSection.classList.remove("collapsed-step");
  els.goodsStepHint.textContent = goodsSatisfied
    ? "Photo uploaded. Packing details are now open."
    : "Upload picked-goods photo first. Packing stays locked until this is done.";
  els.packingForm.classList.toggle("hidden", !packingVisible || !goodsSatisfied);'''
app = app.replace(old, new)
app = app.replace('  renderExceptionSummary();\n  const untouchedClaim', '  renderExceptionSummary();\n  updateDispatcherStepVisibility(job);\n  const untouchedClaim')
if 'function renderDispatcherStepTracker' not in app:
    funcs = '''function renderDispatcherStepTracker(steps) {
  if (!els.dispatcherStepTracker) return;
  els.dispatcherStepTracker.innerHTML = steps.map((step, index) => `
    <div class="dispatcher-step-chip ${step.state}">
      <span>${index + 1}</span>
      <strong>${escapeHtml(step.label)}</strong>
    </div>
  `).join("");
}

function updateDispatcherStepVisibility(job = byId(state.selectedDispatcherJobId)) {
  if (!job) return;
  const goodsPhotos = job.goodsCheck?.photos || [];
  const packingPhotos = job.packingDetails?.packingPhotos || [];
  const lines = collectPackingLines();
  const totals = currentPackingTotals();
  const goodsDone = goodsPhotos.length > 0 || ["submitted-for-review", "approved-by-reviewer", "dispatch-pending", "dispatched", "delivered", "completed"].includes(job.currentStatus);
  const hasPacking = lines.length > 0;
  const packingMatches = totals.totalPackedCases === Number(job.orderCaseCount || 0);
  const differenceResolved = hasValidItemDifferenceForTotals(job, totals) || hasAdminMismatchOverride(job);
  const packingDone = hasPacking && (packingMatches || differenceResolved);
  const finalDone = packingPhotos.length > 0 || ["submitted-for-review", "approved-by-reviewer", "dispatch-pending", "dispatched", "delivered", "completed"].includes(job.currentStatus);
  const submitted = ["submitted-for-review", "approved-by-reviewer", "dispatch-pending", "dispatched", "delivered", "completed"].includes(job.currentStatus);

  const packingOpen = goodsDone && !submitted;
  const finalOpen = packingOpen && packingDone;
  els.packingEntryStep.classList.toggle("hidden", !packingOpen);
  els.finalPackingStep.classList.toggle("hidden", !finalOpen);
  els.goodsCheckSection.classList.toggle("collapsed-step", goodsDone && packingOpen);
  els.packingEntryStep.classList.toggle("collapsed-step", finalOpen);
  els.packingEntryStatusLabel.textContent = !goodsDone ? "Locked" : packingDone ? "Done" : "Open";
  els.finalPackingStatusLabel.textContent = !packingDone ? "Locked" : finalDone ? "Done" : "Open";
  els.goodsCheckStatusLabel.textContent = goodsDone ? "Done" : "Open";
  [els.packingCameraButton, els.packingCameraInput, els.packingFileInput, els.submitReviewButton].forEach((control) => {
    if (control) control.disabled = !finalOpen;
  });
  renderDispatcherStepTracker([
    { label: "Goods photo", state: goodsDone ? "done" : "active" },
    { label: "Packing", state: !goodsDone ? "locked" : packingDone ? "done" : "active" },
    { label: "Final photo", state: !packingDone ? "locked" : finalDone ? "done" : "active" },
  ]);
}

'''
    app = app.replace('function goodsStageLabel(status) {', funcs + 'function goodsStageLabel(status) {')
app = app.replace('  els.shortageItemsWrap.classList.toggle("hidden", !(mismatch && (job?.billItems || []).length));\n}', '  els.shortageItemsWrap.classList.toggle("hidden", !(mismatch && (job?.billItems || []).length));\n  updateDispatcherStepVisibility(job);\n}')
write('app.js', app)

styles = read('styles.css')
if 'dispatcher-step-tracker' not in styles:
    styles += '''

.dispatcher-step-tracker { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.dispatcher-step-chip { display: flex; align-items: center; gap: 8px; border: 1px solid var(--line); border-radius: 999px; background: #fff; padding: 8px 10px; color: var(--muted); font-size: 0.82rem; font-weight: 900; }
.dispatcher-step-chip span { display: inline-grid; width: 24px; height: 24px; place-items: center; border-radius: 999px; background: var(--grey-soft); color: var(--grey); }
.dispatcher-step-chip.active { border-color: rgba(36, 107, 255, 0.22); background: var(--blue-soft); color: var(--blue); }
.dispatcher-step-chip.active span { background: var(--blue); color: #fff; }
.dispatcher-step-chip.done { border-color: rgba(22, 133, 90, 0.22); background: var(--green-soft); color: var(--green); }
.dispatcher-step-chip.done span { background: var(--green); color: #fff; }
.dispatcher-step-chip.locked { opacity: 0.62; }
.dispatcher-step-panel { border: 1px solid var(--line); border-radius: 18px; background: #fff; padding: 10px; }
.workflow-step-card.collapsed-step, .dispatcher-step-panel.collapsed-step { padding: 8px 10px; }
.workflow-step-card.collapsed-step .muted-copy, .workflow-step-card.collapsed-step .upload-card, .workflow-step-card.collapsed-step #submitGoodsReviewButton { display: none; }
.dispatcher-step-panel.collapsed-step #bankPackingGrid, .dispatcher-step-panel.collapsed-step #shortageSection { display: none; }
.dispatcher-step-panel.collapsed-step .compact-total-grid { margin-top: 6px; position: static; padding: 6px 8px; }
.dispatcher-step-panel.collapsed-step .section-header { margin-bottom: 0; }
@media (max-width: 720px) { .dispatcher-step-tracker { grid-template-columns: 1fr; } .dispatcher-step-chip { justify-content: flex-start; min-height: 42px; } }
'''
write('styles.css', styles)

sw = read('sw.js')
sw = sw.replace('dispatch-desk-static-v14-dispatcher-compact', 'dispatch-desk-static-v15-dispatcher-steps')
sw = sw.replace('20260603-dispatcher-compact', '20260606-dispatcher-steps')
write('sw.js', sw)
