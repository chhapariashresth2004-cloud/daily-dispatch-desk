from pathlib import Path

ROOT = Path(__file__).resolve().parent
app = ROOT / "app.js"
styles = ROOT / "styles.css"

text = app.read_text(encoding="utf-8")
old = '''function renderDispatcherDetail() {
  const job = byId(state.selectedDispatcherJobId);
  els.dispatcherDetailContent.classList.toggle("hidden", !job);
  els.dispatcherEmptyState.classList.toggle("hidden", !!job);
  if (!job) {
    els.dispatcherDetailTitle.textContent = "Select a job";
    setStatus(els.dispatcherDetailStatus, "neutral");
    return;
  }
'''
new = '''function renderDispatcherDetail() {
  const job = byId(state.selectedDispatcherJobId);
  const dispatcherLayout = document.querySelector(".dispatcher-layout");
  dispatcherLayout?.classList.toggle("has-dispatcher-job", !!job);
  ensureDispatcherBackButton();
  const backButton = document.getElementById("mobileDispatcherBackButton");
  backButton?.classList.toggle("hidden", !job);
  els.dispatcherDetailContent.classList.toggle("hidden", !job);
  els.dispatcherEmptyState.classList.toggle("hidden", !!job);
  if (!job) {
    els.dispatcherDetailTitle.textContent = "Select a job";
    setStatus(els.dispatcherDetailStatus, "neutral");
    return;
  }
'''
if new not in text:
    if old not in text:
        raise SystemExit("renderDispatcherDetail start block not found")
    text = text.replace(old, new)

anchor = "function renderDispatcherDetail() {"
helper = '''function ensureDispatcherBackButton() {
  if (document.getElementById("mobileDispatcherBackButton")) return;
  const header = document.querySelector(".dispatcher-layout .detail-panel > .section-header");
  if (!header) return;
  const button = document.createElement("button");
  button.id = "mobileDispatcherBackButton";
  button.type = "button";
  button.className = "secondary-button mobile-dispatcher-back hidden";
  button.textContent = "Back to jobs";
  button.addEventListener("click", () => {
    state.selectedDispatcherJobId = "";
    renderDispatcher();
  });
  header.appendChild(button);
}

'''
if "function ensureDispatcherBackButton" not in text:
    if anchor not in text:
        raise SystemExit("renderDispatcherDetail anchor not found")
    text = text.replace(anchor, helper + anchor)
app.write_text(text, encoding="utf-8")

css = styles.read_text(encoding="utf-8")
marker = "/* Dispatcher fixed mobile work screen */"
if marker not in css:
    css += r'''

/* Dispatcher fixed mobile work screen */
.mobile-dispatcher-back {
  display: none;
}

@media (max-width: 720px) {
  .dispatcher-layout.has-dispatcher-job {
    display: block;
  }

  .dispatcher-layout.has-dispatcher-job > .panel:first-child {
    display: none !important;
  }

  .dispatcher-layout.has-dispatcher-job > .detail-panel {
    min-height: calc(100vh - 74px);
    padding: 10px 10px 86px !important;
    border-radius: 0;
    box-shadow: none;
  }

  .dispatcher-layout.has-dispatcher-job > .detail-panel > .section-header {
    position: sticky;
    top: 0;
    z-index: 20;
    margin: -10px -10px 8px;
    padding: 10px;
    background: rgba(244, 247, 251, 0.98);
    border-bottom: 1px solid var(--line);
    backdrop-filter: blur(8px);
  }

  .mobile-dispatcher-back:not(.hidden) {
    display: inline-flex;
    min-height: 38px;
    padding: 8px 10px;
    font-size: 0.82rem;
  }

  .dispatcher-layout.has-dispatcher-job #dispatcherReadonlyGrid {
    display: none;
  }

  .dispatcher-layout.has-dispatcher-job #dispatcherDetailContent {
    height: calc(100vh - 150px);
    overflow: auto;
    padding-bottom: 92px;
  }

  .dispatcher-layout.has-dispatcher-job #goodsCheckSection:not(.hidden),
  .dispatcher-layout.has-dispatcher-job #packingEntryStep:not(.hidden),
  .dispatcher-layout.has-dispatcher-job #finalPackingStep:not(.hidden) {
    min-height: calc(100vh - 265px);
    display: flex;
    flex-direction: column;
    justify-content: flex-start;
  }

  .dispatcher-layout.has-dispatcher-job .compact-upload-card {
    margin-top: auto;
  }

  .dispatcher-layout.has-dispatcher-job .photo-action-row,
  .dispatcher-layout.has-dispatcher-job #finalPackingStep > .button-row:last-child {
    position: sticky;
    bottom: 8px;
    z-index: 25;
    display: grid !important;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
    padding: 8px;
    margin: 8px -2px 0;
    border: 1px solid var(--line);
    border-radius: 18px;
    background: rgba(255, 255, 255, 0.98);
    box-shadow: 0 12px 30px rgba(20, 35, 55, 0.12);
  }

  .dispatcher-layout.has-dispatcher-job #finalPackingStep > .button-row:last-child {
    grid-template-columns: 1fr;
  }

  .dispatcher-layout.has-dispatcher-job .photo-action-row .secondary-button,
  .dispatcher-layout.has-dispatcher-job .photo-action-row .file-button,
  .dispatcher-layout.has-dispatcher-job #submitReviewButton {
    width: 100%;
    min-height: 52px;
    justify-content: center;
    font-size: 1rem;
  }

  .dispatcher-layout.has-dispatcher-job #bankPackingGrid.bank-packing-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
  }

  .dispatcher-layout.has-dispatcher-job #bankPackingGrid .bank-pack-card input {
    min-height: 48px;
    font-size: 1.1rem;
  }

  .dispatcher-layout.has-dispatcher-job #bankPackingGrid .bora-card {
    grid-column: 1 / -1;
  }

  .dispatcher-layout.has-dispatcher-job .compact-total-grid {
    position: sticky;
    top: 56px;
    z-index: 18;
  }
}
'''
styles.write_text(css, encoding="utf-8")

for temp in [ROOT / "apply_fixed_mobile_work_screen.py", ROOT / ".github/workflows/apply-fixed-mobile-work-screen.yml"]:
    if temp.exists():
        temp.unlink()
