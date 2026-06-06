from pathlib import Path

ROOT = Path(__file__).resolve().parent
app = ROOT / "app.js"
styles = ROOT / "styles.css"

text = app.read_text(encoding="utf-8")
line = '  dispatcherLayout?.classList.toggle("has-dispatcher-job", !!job);'
insert = line + '\n  document.body.classList.toggle("dispatcher-mobile-work-open", !!job);'
if "dispatcher-mobile-work-open" not in text:
    if line not in text:
        raise SystemExit("dispatcher layout class line not found")
    text = text.replace(line, insert)
app.write_text(text, encoding="utf-8")

css = styles.read_text(encoding="utf-8")
marker = "/* Hard no-scroll dispatcher phone work mode */"
block = r'''

/* Hard no-scroll dispatcher phone work mode */
@media (max-width: 720px) {
  body.dispatcher-mobile-work-open {
    overflow: hidden !important;
    height: 100dvh !important;
    position: fixed;
    inset: 0;
    width: 100%;
  }

  body.dispatcher-mobile-work-open .app-shell,
  body.dispatcher-mobile-work-open .workspace,
  body.dispatcher-mobile-work-open #dispatcherDashboardView {
    height: 100dvh !important;
    min-height: 100dvh !important;
    overflow: hidden !important;
  }

  body.dispatcher-mobile-work-open .sidebar,
  body.dispatcher-mobile-work-open .topbar,
  body.dispatcher-mobile-work-open #dispatcherMetrics,
  body.dispatcher-mobile-work-open #dispatcherTabs,
  body.dispatcher-mobile-work-open .dispatcher-layout > .panel:first-child {
    display: none !important;
  }

  body.dispatcher-mobile-work-open .workspace {
    padding: 0 !important;
  }

  body.dispatcher-mobile-work-open .dispatcher-layout,
  body.dispatcher-mobile-work-open .dispatcher-layout.has-dispatcher-job {
    display: block !important;
    height: 100dvh !important;
    overflow: hidden !important;
    margin: 0 !important;
  }

  body.dispatcher-mobile-work-open .dispatcher-layout.has-dispatcher-job > .detail-panel {
    position: fixed !important;
    inset: 0 !important;
    width: 100vw !important;
    height: 100dvh !important;
    min-height: 100dvh !important;
    overflow: hidden !important;
    padding: 8px 8px 78px !important;
    border: 0 !important;
    border-radius: 0 !important;
    box-shadow: none !important;
    background: var(--bg) !important;
  }

  body.dispatcher-mobile-work-open .dispatcher-layout.has-dispatcher-job > .detail-panel > .section-header {
    position: relative !important;
    top: auto !important;
    z-index: 20;
    min-height: 48px;
    margin: 0 0 6px !important;
    padding: 4px 2px 6px !important;
    background: var(--bg) !important;
    border-bottom: 1px solid var(--line);
  }

  body.dispatcher-mobile-work-open #dispatcherDetailTitle {
    font-size: 1rem !important;
    line-height: 1.15 !important;
    margin: 0 !important;
  }

  body.dispatcher-mobile-work-open #dispatcherDetailStatus {
    display: none !important;
  }

  body.dispatcher-mobile-work-open .mobile-dispatcher-back:not(.hidden) {
    display: inline-flex !important;
    min-height: 36px !important;
    padding: 7px 10px !important;
    font-size: 0.82rem !important;
    white-space: nowrap;
  }

  body.dispatcher-mobile-work-open #dispatcherDetailContent {
    height: calc(100dvh - 62px) !important;
    overflow: hidden !important;
    display: grid !important;
    grid-template-rows: auto 1fr;
    gap: 6px !important;
    padding: 0 0 74px !important;
  }

  body.dispatcher-mobile-work-open #dispatcherReadonlyGrid {
    display: none !important;
  }

  body.dispatcher-mobile-work-open .dispatcher-step-tracker {
    display: grid !important;
    grid-template-columns: repeat(3, minmax(0, 1fr)) !important;
    gap: 5px !important;
  }

  body.dispatcher-mobile-work-open .dispatcher-step-chip {
    min-height: 32px !important;
    padding: 5px 4px !important;
    gap: 4px !important;
    font-size: 0.68rem !important;
    justify-content: center !important;
  }

  body.dispatcher-mobile-work-open .dispatcher-step-chip span {
    width: 18px !important;
    height: 18px !important;
    font-size: 0.68rem !important;
  }

  body.dispatcher-mobile-work-open #goodsCheckSection:not(.hidden),
  body.dispatcher-mobile-work-open #packingEntryStep:not(.hidden),
  body.dispatcher-mobile-work-open #finalPackingStep:not(.hidden) {
    height: calc(100dvh - 150px) !important;
    min-height: 0 !important;
    overflow: hidden !important;
    display: flex !important;
    flex-direction: column !important;
    padding: 10px !important;
    border-radius: 18px !important;
    background: #fff !important;
  }

  body.dispatcher-mobile-work-open .compact-header {
    margin-bottom: 4px !important;
  }

  body.dispatcher-mobile-work-open .compact-header h4 {
    margin: 0 !important;
    font-size: 1rem !important;
  }

  body.dispatcher-mobile-work-open .muted-copy {
    margin: 2px 0 6px !important;
    font-size: 0.82rem !important;
  }

  body.dispatcher-mobile-work-open .compact-upload-card {
    margin-top: auto !important;
    min-height: 162px !important;
    padding: 10px !important;
  }

  body.dispatcher-mobile-work-open .photo-preview-grid {
    grid-column: 1 / -1 !important;
    display: flex !important;
    gap: 8px !important;
    max-height: 76px !important;
    overflow-x: auto !important;
    overflow-y: hidden !important;
  }

  body.dispatcher-mobile-work-open .photo-preview-card {
    flex: 0 0 72px !important;
    width: 72px !important;
    padding: 5px !important;
  }

  body.dispatcher-mobile-work-open .photo-preview-card img {
    height: 52px !important;
  }

  body.dispatcher-mobile-work-open .photo-action-row,
  body.dispatcher-mobile-work-open #finalPackingStep > .button-row:last-child {
    position: fixed !important;
    left: 8px !important;
    right: 8px !important;
    bottom: 8px !important;
    z-index: 50 !important;
    display: grid !important;
    grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
    gap: 8px !important;
    padding: 8px !important;
    margin: 0 !important;
    border: 1px solid var(--line) !important;
    border-radius: 18px !important;
    background: rgba(255, 255, 255, 0.98) !important;
    box-shadow: 0 14px 34px rgba(20, 35, 55, 0.18) !important;
  }

  body.dispatcher-mobile-work-open #finalPackingStep > .button-row:last-child {
    grid-template-columns: 1fr !important;
  }

  body.dispatcher-mobile-work-open .photo-action-row .secondary-button,
  body.dispatcher-mobile-work-open .photo-action-row .file-button,
  body.dispatcher-mobile-work-open #submitReviewButton {
    width: 100% !important;
    min-height: 54px !important;
    justify-content: center !important;
    font-size: 1rem !important;
  }

  body.dispatcher-mobile-work-open #packingEntryStep {
    gap: 6px !important;
  }

  body.dispatcher-mobile-work-open #packingEntryStep .compact-total-grid {
    position: static !important;
    display: grid !important;
    grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
    padding: 7px !important;
    margin: 0 !important;
  }

  body.dispatcher-mobile-work-open #bankPackingGrid.bank-packing-grid {
    flex: 1 1 auto;
    display: grid !important;
    grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
    gap: 7px !important;
    overflow: hidden !important;
    margin-top: 4px !important;
  }

  body.dispatcher-mobile-work-open #bankPackingGrid .bank-pack-card {
    padding: 7px !important;
    min-height: 72px !important;
  }

  body.dispatcher-mobile-work-open #bankPackingGrid .bank-pack-card input {
    min-height: 42px !important;
    padding: 7px 8px !important;
    font-size: 1rem !important;
  }

  body.dispatcher-mobile-work-open #bankPackingGrid .bora-card {
    grid-column: 1 / -1 !important;
    min-height: 72px !important;
  }

  body.dispatcher-mobile-work-open #shortageSection:not(.hidden) {
    max-height: 118px !important;
    overflow: hidden !important;
    padding: 8px !important;
  }

  body.dispatcher-mobile-work-open .note-field {
    display: none !important;
  }
}
'''
if marker not in css:
    css += block
styles.write_text(css, encoding="utf-8")

for temp in [ROOT / "apply_hard_mobile_no_scroll.py", ROOT / ".github/workflows/apply-hard-mobile-no-scroll.yml"]:
    if temp.exists():
        temp.unlink()
