from pathlib import Path

ROOT = Path(__file__).resolve().parent

index = ROOT / "index.html"
if index.exists():
    text = index.read_text(encoding="utf-8-sig")
    replacements = {
        "1 Ã—": "1 case",
        "2 Ã—": "2 case",
        "3 Ã—": "3 case",
        "4 Ã—": "4 case",
        "5 Ã—": "5 case",
        "1 ×": "1 case",
        "2 ×": "2 case",
        "3 ×": "3 case",
        "4 ×": "4 case",
        "5 ×": "5 case",
        "Quick package entry": "Step 2 package entry",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    index.write_text(text, encoding="utf-8")

app = ROOT / "app.js"
if app.exists():
    text = app.read_text(encoding="utf-8")
    lines_to_remove = [
        '  els.goodsCheckSection.classList.remove("collapsed-step");\n',
        '  els.goodsCheckSection.classList.toggle("collapsed-step", goodsDone && packingOpen);\n',
        '  els.packingEntryStep.classList.toggle("collapsed-step", finalOpen);\n',
    ]
    for line in lines_to_remove:
        text = text.replace(line, "")
    app.write_text(text, encoding="utf-8")

styles = ROOT / "styles.css"
if styles.exists():
    text = styles.read_text(encoding="utf-8")
    marker = "/* Dispatcher step fix: keep workflow visible as steps"
    if marker in text:
        text = text[:text.index(marker)].rstrip() + "\n"
    text += r'''

/* Dispatcher step fix: keep workflow visible as steps, not dropdown/collapsed sections. */
.workflow-step-card.collapsed-step,
.dispatcher-step-panel.collapsed-step {
  padding: 10px !important;
}

.workflow-step-card.collapsed-step .muted-copy,
.workflow-step-card.collapsed-step .upload-card,
.workflow-step-card.collapsed-step #submitGoodsReviewButton,
.dispatcher-step-panel.collapsed-step #bankPackingGrid,
.dispatcher-step-panel.collapsed-step #shortageSection {
  display: block !important;
}

.workflow-step-card.collapsed-step .compact-upload-card {
  display: grid !important;
}

.dispatcher-step-panel.collapsed-step .compact-total-grid {
  margin-top: 0 !important;
  position: sticky !important;
  padding: 8px !important;
}

.dispatcher-step-panel.collapsed-step .section-header {
  margin-bottom: 6px !important;
}

#goodsCheckSection,
#packingEntryStep,
#finalPackingStep {
  border: 1px solid rgba(36, 107, 255, 0.18) !important;
  border-radius: 18px !important;
  background: #fff !important;
  box-shadow: 0 8px 24px rgba(20, 35, 55, 0.04);
}

#bankPackingGrid .bank-pack-card:nth-child(-n+5) > span {
  font-size: 0 !important;
}
#bankPackingGrid .bank-pack-card:nth-child(1) > span::after { content: "1 case"; font-size: 0.94rem; }
#bankPackingGrid .bank-pack-card:nth-child(2) > span::after { content: "2 case"; font-size: 0.94rem; }
#bankPackingGrid .bank-pack-card:nth-child(3) > span::after { content: "3 case"; font-size: 0.94rem; }
#bankPackingGrid .bank-pack-card:nth-child(4) > span::after { content: "4 case"; font-size: 0.94rem; }
#bankPackingGrid .bank-pack-card:nth-child(5) > span::after { content: "5 case"; font-size: 0.94rem; }
'''
    styles.write_text(text, encoding="utf-8")

# remove temporary runner and workflow after applying
for temp in [ROOT / "apply_dispatcher_steps_fix.py", ROOT / ".github/workflows/apply-dispatcher-steps-fix.yml"]:
    if temp.exists():
        temp.unlink()
