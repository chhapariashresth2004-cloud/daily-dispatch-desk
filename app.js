const state = {
  me: null,
  jobs: [],
  metrics: {},
  directory: [],
  users: [],
  reports: {},
  routes: [],
  routeBatches: [],
  deliveryPartners: [],
  settings: {},
  roleView: "",
  dispatcherTab: "my",
  reviewerTab: "overview",
  adminTab: "overview",
  selectedDispatcherJobId: "",
  selectedReviewerJobId: "",
  selectedAdminJobId: "",
  draftBillFileUrl: "",
  draftExtractedBillData: {},
  bulkDrafts: [],
  liveRefreshTimer: null,
  photoUploadBusy: false,
};

const transportModes = ["", "Transport", "Self", "Delivery Partner", "Bus", "Direct Delivery", "Local Delivery", "Not Required"];
const shortageReasons = ["", "Stock shortage", "One case not delivered", "Damaged item", "Billing mismatch", "Packing mistake", "Party hold", "Other"];
const exceptionReasons = [
  "",
  "Stock shortage",
  "One case not delivered",
  "Damaged item",
  "Billing mismatch",
  "Packing mistake",
  "Party hold",
  "Wrong MRP stock",
  "Substitute stock",
  "Other",
];
const differenceReasons = [
  "",
  "Transporter opened bundle",
  "Loose items counted separately",
  "Bundle repacked by transporter",
  "Bora opened",
  "Damage/repacking",
  "Manual counting difference",
  "Other",
];
const statuses = [
  "ready", "assigned", "goods-photo-uploaded", "goods-submitted-for-review",
  "goods-needs-correction", "goods-approved", "packing", "submitted-for-review",
  "needs-correction", "approved-by-reviewer", "dispatch-pending", "dispatched", "delivered", "completed", "cancelled",
];

const $ = (selector) => document.querySelector(selector);
const els = Object.fromEntries([...document.querySelectorAll("[id]")].map((el) => [el.id, el]));

bootstrap();

async function bootstrap() {
  bindEvents();
  fillStaticSelects();
  const response = await fetch("/api/me");
  if (!response.ok) return showLogin();
  state.me = (await response.json()).user;
  await reloadData();
  showApp();
}

function bindEvents() {
  els.loginForm.addEventListener("submit", login);
  els.logoutButton.addEventListener("click", logout);
  els.newDispatchButton.addEventListener("click", openNewDispatchDialog);
  els.closeNewDispatchButton.addEventListener("click", () => els.newDispatchDialog.close());
  els.billFileInput.addEventListener("change", uploadBill);
  els.clearDraftButton.addEventListener("click", clearDraft);
  els.createJobForm.addEventListener("submit", createJob);
  els.bulkImportButton.addEventListener("click", openBulkImportDialog);
  els.closeBulkImportButton.addEventListener("click", () => els.bulkImportDialog.close());
  els.bulkBillFilesInput.addEventListener("change", prepareBulkImports);
  els.bulkImportForm.addEventListener("submit", createBulkJobs);
  els.reviewerSearchInput.addEventListener("input", renderReviewer);
  els.adminSearchInput.addEventListener("input", renderAdmin);
  els.deliveryPartnerInput.addEventListener("input", autocompleteDeliveryPartner);
  els.goodsCameraButton.addEventListener("click", () => openCameraInput(els.goodsCameraInput));
  els.goodsCameraInput.addEventListener("change", (event) => uploadGoodsPhotos(event.target.files));
  els.goodsFileInput.addEventListener("change", (event) => uploadGoodsPhotos(event.target.files));
  els.submitGoodsReviewButton.addEventListener("click", submitGoodsReview);
  els.packingCameraButton.addEventListener("click", () => openCameraInput(els.packingCameraInput));
  els.packingCameraInput.addEventListener("change", (event) => uploadPackingPhotos(event.target.files));
  els.packingFileInput.addEventListener("change", (event) => uploadPackingPhotos(event.target.files));
  els.submitReviewButton.addEventListener("click", submitReview);
  els.unassignJobButton.addEventListener("click", unassignJob);
  [els.pack1Input, els.pack2Input, els.pack3Input, els.pack4Input, els.pack5Input, els.boraCasesListInput]
    .forEach((input) => input.addEventListener("input", syncPackingTotals));
  els.shortageItemSearchInput.addEventListener("input", renderShortageBillItems);
  els.openExceptionDialogButton.addEventListener("click", openExceptionDialog);
  els.closeExceptionDialogButton.addEventListener("click", () => els.itemExceptionDialog.close());
  els.itemExceptionForm.addEventListener("submit", addItemException);
  els.exceptionItemSearchInput.addEventListener("input", renderExceptionItemOptions);
  els.exceptionItemSelect.addEventListener("change", syncSelectedExceptionItem);
  document.querySelectorAll("[data-review-action]").forEach((button) => {
    button.addEventListener("click", () => reviewDecision(button.dataset.reviewAction));
  });
  document.querySelectorAll("[data-goods-review-action]").forEach((button) => {
    button.addEventListener("click", () => goodsReviewDecision(button.dataset.goodsReviewAction));
  });
  els.transportModeInput.addEventListener("change", syncTransportModeState);
  els.biltyPackageCountInput.addEventListener("input", syncDifferenceWarning);
  els.packageDifferenceReasonInput.addEventListener("change", syncDifferenceWarning);
  els.biltyPhotoInput.addEventListener("change", uploadBiltyPhoto);
  els.markDispatchedButton.addEventListener("click", markDispatched);
  els.markCompletedButton.addEventListener("click", markCompleted);
  els.routeBatchForm.addEventListener("submit", createRouteBatch);
  els.adminEditForm.addEventListener("submit", saveAdminEdit);
  els.deliveryPartnerDirectoryForm.addEventListener("submit", addDeliveryPartner);
  els.roleLabelForm.addEventListener("submit", saveRoleLabels);
}

function fillStaticSelects() {
  els.transportModeInput.innerHTML = transportModes.map((value) => `<option>${value}</option>`).join("");
  els.exceptionReasonInput.innerHTML = exceptionReasons.map((value) => `<option>${value}</option>`).join("");
  els.packageDifferenceReasonInput.innerHTML = differenceReasons.map((value) => `<option>${value}</option>`).join("");
  els.adminStatusInput.innerHTML = statuses.map((value) => `<option value="${value}">${statusLabel(value)}</option>`).join("");
  els.draftDispatchDateInput.value = today();
}

function openNewDispatchDialog() {
  fillDraftRoutes();
  els.newDispatchDialog.showModal();
}

function fillDraftRoutes() {
  els.draftRouteInput.innerHTML = `<option value=""></option>${state.routes.map((route) => `<option>${route.name}</option>`).join("")}`;
}

async function login(event) {
  event.preventDefault();
  const response = await fetch("/api/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ login: els.loginIdInput.value.trim(), password: els.passwordInput.value }),
  });
  const data = await response.json();
  if (!response.ok) return toast(data.error || "Internet issue. Try again", "error");
  state.me = data.user;
  await reloadData();
  showApp();
}

async function logout() {
  await fetch("/api/logout", { method: "POST" });
  state.me = null;
  stopLiveRefresh();
  showLogin();
}

async function reloadData() {
  const response = await fetch("/api/bootstrap");
  const data = await response.json();
  state.jobs = data.jobs || [];
  state.metrics = data.metrics || {};
  state.directory = data.directory || [];
  state.users = data.users || [];
  state.reports = data.reports || {};
  state.routes = data.routes || [];
  state.routeBatches = data.routeBatches || [];
  state.deliveryPartners = data.deliveryPartners || [];
  state.settings = data.settings || {};
  renderDeliveryPartnerDirectory();
}

function showLogin() {
  els.loginView.classList.remove("hidden");
  els.appShell.classList.add("hidden");
}

function showApp() {
  els.loginView.classList.add("hidden");
  els.appShell.classList.remove("hidden");
  els.currentUserName.textContent = state.me.name;
  els.currentUserRole.textContent = roleLabel(state.me.role);
  els.newDispatchButton.classList.toggle("hidden", !["reviewer", "admin"].includes(state.me.role));
  renderRoleNav();
  startLiveRefresh();
}

function renderRoleNav() {
  const views = {
    dispatcher: [["dispatcherDashboard", `${roleLabel("dispatcher")} Dashboard`, "Packing & photo"]],
    reviewer: [["reviewerDashboard", `${roleLabel("reviewer")} Dashboard`, "Quality control"]],
    admin: [["adminDashboard", "Admin Dashboard", "Full control"]],
  }[state.me.role];
  els.roleNav.innerHTML = "";
  views.forEach(([id, title, eyebrow], index) => {
    const button = document.createElement("button");
    button.className = `nav-button ${index === 0 ? "active" : ""}`;
    button.textContent = title;
    button.addEventListener("click", () => switchView(id, title, eyebrow));
    els.roleNav.appendChild(button);
  });
  switchView(...views[0]);
}

function switchView(view, title, eyebrow) {
  state.roleView = view;
  document.querySelectorAll(".page-view").forEach((panel) => panel.classList.add("hidden"));
  $(`#${view}View`).classList.remove("hidden");
  els.pageTitle.textContent = title;
  els.pageEyebrow.textContent = eyebrow;
  if (view === "dispatcherDashboard") renderDispatcher();
  if (view === "reviewerDashboard") renderReviewer();
  if (view === "adminDashboard") renderAdmin();
}

function renderTabs(container, tabs, active, onClick) {
  container.innerHTML = "";
  tabs.forEach(([id, title, count]) => {
    const button = document.createElement("button");
    button.className = `page-tab ${id === active ? "active" : ""}`;
    button.innerHTML = count === undefined
      ? `<span>${title}</span>`
      : `<strong>${count}</strong><span>${title}</span>`;
    button.addEventListener("click", () => onClick(id));
    container.appendChild(button);
  });
}

function renderDispatcher() {
  els.dispatcherMetrics.classList.add("hidden");
  const activeCount = myJobs().filter((job) => activeDispatcherStatuses().includes(job.currentStatus)).length;
  renderTabs(els.dispatcherTabs, [
    ["my", "My Work", myJobs().filter((job) => activeDispatcherStatuses().includes(job.currentStatus)).length],
    ["available", "Available", jobsBy("ready").length],
    ["correction", "Correction", myJobs().filter((job) => ["goods-needs-correction", "needs-correction"].includes(job.currentStatus)).length],
    ["submitted", "Submitted", myJobs().filter((job) => ["goods-submitted-for-review", "submitted-for-review"].includes(job.currentStatus)).length],
  ], state.dispatcherTab, (id) => { state.dispatcherTab = id; renderDispatcher(); });
  const jobs = {
    available: jobsBy("ready"),
    my: myJobs().filter((job) => activeDispatcherStatuses().includes(job.currentStatus)),
    correction: myJobs().filter((job) => ["goods-needs-correction", "needs-correction"].includes(job.currentStatus)),
    submitted: myJobs().filter((job) => ["goods-submitted-for-review", "submitted-for-review"].includes(job.currentStatus)),
  }[state.dispatcherTab];
  if (state.dispatcherTab === "available" && activeCount >= 2) {
    els.dispatcherList.innerHTML = `<div class="locked-state">Complete one job first.</div>`;
    state.selectedDispatcherJobId = "";
    return renderDispatcherDetail();
  }
  renderJobCards(els.dispatcherList, jobs, state.dispatcherTab === "available" ? claimJob : selectDispatcherJob);
  if (!jobs.some((job) => job.id === state.selectedDispatcherJobId)) state.selectedDispatcherJobId = jobs[0]?.id || "";
  renderDispatcherDetail();
}

function activeDispatcherStatuses() {
  return ["assigned", "goods-photo-uploaded", "goods-needs-correction", "goods-approved", "packing", "needs-correction"];
}

function myJobs() {
  return state.jobs.filter((job) => job.dispatcherId === state.me.id);
}

async function claimJob(jobId) {
  const response = await fetch(`/api/dispatches/${jobId}/claim`, { method: "POST" });
  const data = await response.json();
  if (!response.ok) return toast(data.error?.includes("2 active") ? "You already have 2 active jobs. Complete one job before taking another." : data.error, "error");
  state.selectedDispatcherJobId = jobId;
  state.dispatcherTab = "my";
  await refresh("Job claimed");
}

async function unassignJob() {
  const job = byId(state.selectedDispatcherJobId);
  if (!job) return;
  if (!confirm("Return this job to Available Work?")) return;
  const response = await fetch(`/api/dispatches/${job.id}/unassign`, { method: "POST" });
  const data = await response.json();
  if (!response.ok) return toast(data.error || "Internet issue. Try again", "error");
  state.selectedDispatcherJobId = "";
  await refresh("Job unassigned");
}

function selectDispatcherJob(jobId) {
  state.selectedDispatcherJobId = jobId;
  renderDispatcherDetail();
}

function renderDispatcherDetail() {
  const job = byId(state.selectedDispatcherJobId);
  els.dispatcherDetailContent.classList.toggle("hidden", !job);
  els.dispatcherEmptyState.classList.toggle("hidden", !!job);
  if (!job) {
    els.dispatcherDetailTitle.textContent = "Select a job";
    setStatus(els.dispatcherDetailStatus, "neutral");
    return;
  }
  els.dispatcherDetailTitle.textContent = `${job.partyName} — ${job.partyCity}`;
  setStatus(els.dispatcherDetailStatus, job.currentStatus);
  els.dispatcherReadonlyGrid.innerHTML = readonly([
    ["Order cases", job.orderCaseCount],
  ]);
  const goodsPhotos = job.goodsCheck?.photos || [];
  els.goodsPhotoLabel.textContent = goodsPhotos.length ? `${goodsPhotos.length} photo(s) uploaded` : "Upload goods photos";
  els.goodsCheckStatusLabel.textContent = goodsStageLabel(job.currentStatus);
  renderGoodsPhotoPreview(goodsPhotos);
  const canEditGoods = ["assigned", "goods-photo-uploaded", "goods-needs-correction", "packing", "needs-correction"].includes(job.currentStatus);
  [els.goodsCameraButton, els.goodsCameraInput, els.goodsFileInput, els.submitGoodsReviewButton].forEach((control) => control.disabled = !canEditGoods);
  const packingEditable = ["assigned", "goods-photo-uploaded", "goods-needs-correction", "goods-approved", "packing", "needs-correction"].includes(job.currentStatus);
  const packingVisible = packingEditable || ["submitted-for-review", "approved-by-reviewer", "dispatch-pending", "dispatched", "delivered", "completed"].includes(job.currentStatus);
  const goodsReady = goodsPhotos.length > 0;
  const goodsSatisfied = goodsReady || ["submitted-for-review", "approved-by-reviewer", "dispatch-pending", "dispatched", "delivered", "completed"].includes(job.currentStatus);
  els.goodsCheckSection.classList.toggle("completed-step", goodsSatisfied);
  els.goodsCheckSection.querySelector(".muted-copy").textContent = goodsSatisfied
    ? "Picked-goods photo uploaded. Continue with packing."
    : "You can prepare packing now. Picked-goods photo is still required before submit.";
  els.packingForm.classList.toggle("hidden", !packingVisible);
  els.packingProofWrap.classList.toggle("hidden", !packingVisible);
  els.dispatcherNoteInput.value = job.dispatcherNote || job.packingDetails.dispatcherNote || "";
  fillBankPackingInputs(job.packingDetails.packingBreakup || []);
  els.shortageNoteInput.value = job.shortageNote || "";
  els.packingPhotoLabel.textContent = job.packingDetails.packingPhotos?.length ? `${job.packingDetails.packingPhotos.length} photo(s) uploaded` : "Upload packing photos";
  renderPackingPhotoPreview(job.packingDetails.packingPhotos || []);
  syncPackingTotals();
  renderShortageBillItems();
  renderSelectedShortageItems();
  renderExceptionSummary();
  const untouchedClaim = job.currentStatus === "assigned"
    && !(job.packingDetails.packingBreakup || []).length
    && !(job.packingDetails.packingPhotos || []).length
    && !(job.goodsCheck?.photos || []).length;
  els.unassignJobButton.classList.toggle("hidden", !untouchedClaim);
}

function goodsStageLabel(status) {
  return {
    assigned: "Upload photo to start packing",
    "goods-photo-uploaded": "Photo uploaded",
    "goods-submitted-for-review": "Photo uploaded",
    "goods-needs-correction": "Needs correction",
    "goods-approved": "Photo uploaded",
    packing: "Photo uploaded",
    "submitted-for-review": "Photo uploaded",
    "needs-correction": "Photo uploaded",
    "approved-by-reviewer": "Photo uploaded",
    "dispatch-pending": "Photo uploaded",
    dispatched: "Photo uploaded",
    delivered: "Photo uploaded",
    completed: "Photo uploaded",
  }[status] || "Waiting";
}

function collectPackingLines() {
  const lines = [1, 2, 3, 4, 5]
    .map((size) => ({
      packageType: size === 1 ? "Loose" : "Bundle",
      packageCount: Number(els[`pack${size}Input`].value || 0),
      casesPerPackage: size,
      totalCases: Number(els[`pack${size}Input`].value || 0) * size,
    }))
    .filter((line) => line.packageCount);
  parseBoraCases().forEach((casesPerPackage) => lines.push({
    packageType: "Bora",
    packageCount: 1,
    casesPerPackage,
    totalCases: casesPerPackage,
  }));
  return lines;
}

function syncPackingTotals() {
  const lines = collectPackingLines();
  const totals = lines.reduce((acc, line) => ({
    totalPackages: acc.totalPackages + line.packageCount,
    totalPackedCases: acc.totalPackedCases + line.totalCases,
  }), { totalPackages: 0, totalPackedCases: 0 });
  els.totalPackagesValue.textContent = totals.totalPackages;
  els.totalPackedCasesValue.textContent = totals.totalPackedCases;
  const job = byId(state.selectedDispatcherJobId);
  const mismatch = job && lines.length > 0 && totals.totalPackedCases !== Number(job.orderCaseCount || 0);
  els.shortageSection.classList.toggle("hidden", !mismatch);
  els.shortageItemsWrap.classList.toggle("hidden", !(mismatch && (job?.billItems || []).length));
}

function fillBankPackingInputs(lines) {
  [1, 2, 3, 4, 5].forEach((size) => els[`pack${size}Input`].value = "");
  const boraCases = [];
  els.boraCasesListInput.value = "";
  lines.forEach((line) => {
    if (line.packageType === "Bora") {
      for (let i = 0; i < Number(line.packageCount || 0); i += 1) boraCases.push(Number(line.casesPerPackage || 0));
    } else if ([1, 2, 3, 4, 5].includes(Number(line.casesPerPackage))) {
      const size = Number(line.casesPerPackage);
      els[`pack${size}Input`].value = Number(els[`pack${size}Input`].value || 0) + Number(line.packageCount || 0);
    }
  });
  els.boraCasesListInput.value = boraCases.filter(Boolean).join(",");
}

function parseBoraCases() {
  return String(els.boraCasesListInput.value || "")
    .split(/[,\s]+/)
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value) && value > 0);
}

function renderShortageBillItems() {
  const job = byId(state.selectedDispatcherJobId);
  const query = els.shortageItemSearchInput.value.trim().toLowerCase();
  const items = (job?.billItems || []).filter((item) => !query || String(item.name || item.productName || "").toLowerCase().includes(query));
  els.shortageBillItems.innerHTML = items.map((item, index) => {
    const name = item.name || item.productName || `Item ${index + 1}`;
    const qty = item.quantity ?? item.qty ?? "";
    return `<button type="button" class="secondary-button shortage-pick" data-shortage-item="${index}">${name} · billed ${qty}</button>`;
  }).join("");
  els.shortageBillItems.querySelectorAll("[data-shortage-item]").forEach((button) => {
    button.addEventListener("click", () => addShortageItem(items[Number(button.dataset.shortageItem)]));
  });
}

function addShortageItem(item) {
  const current = collectSelectedShortageItems();
  current.push({
    productName: item.name || item.productName || "",
    billedQuantity: item.quantity ?? item.qty ?? "",
    shortQuantity: 0,
    reason: "",
    note: "",
  });
  renderSelectedShortageItems(current);
}

function renderSelectedShortageItems(items = byId(state.selectedDispatcherJobId)?.shortageItems || []) {
  els.shortageSelectedItems.innerHTML = items.map((item, index) => `
    <div class="shortage-selected-row" data-exception-type="${item.exceptionType || "short"}" data-actual-qty="${item.actualQuantity ?? ""}" data-billed-mrp="${item.billedMrp ?? ""}" data-actual-mrp="${item.actualMrp ?? ""}">
      <strong>${item.productName}</strong>
      <span>Billed ${item.billedQuantity}</span>
      <input data-shortage-qty="${index}" type="number" min="0" value="${item.shortQuantity || ""}" placeholder="Short qty" />
      <select data-shortage-reason="${index}">${shortageReasons.map((reason) => `<option ${reason === item.reason ? "selected" : ""}>${reason}</option>`).join("")}</select>
      <input data-shortage-note="${index}" value="${item.note || ""}" placeholder="Note" />
    </div>
  `).join("");
}

function collectSelectedShortageItems() {
  return [...els.shortageSelectedItems.querySelectorAll(".shortage-selected-row")].map((row, index) => ({
    productName: row.querySelector("strong").textContent,
    billedQuantity: row.querySelector("span").textContent.replace("Billed ", ""),
    shortQuantity: Number(row.querySelector(`[data-shortage-qty="${index}"]`).value || 0),
    actualQuantity: Number(row.dataset.actualQty || 0),
    reason: row.querySelector(`[data-shortage-reason="${index}"]`).value,
    note: row.querySelector(`[data-shortage-note="${index}"]`).value.trim(),
    exceptionType: row.dataset.exceptionType || "short",
    billedMrp: Number(row.dataset.billedMrp || 0),
    actualMrp: Number(row.dataset.actualMrp || 0),
  }));
}

function openExceptionDialog() {
  renderExceptionItemOptions();
  els.itemExceptionDialog.showModal();
}

function renderExceptionItemOptions() {
  const job = byId(state.selectedDispatcherJobId);
  const query = els.exceptionItemSearchInput.value.trim().toLowerCase();
  const items = (job?.billItems || []).filter((item) => !query || String(item.name || item.productName || "").toLowerCase().includes(query));
  els.exceptionItemSelect.innerHTML = `<option value=""></option>${items.map((item, index) => `<option value="${index}">${item.name || item.productName || `Item ${index + 1}`}</option>`).join("")}`;
  els.exceptionItemSelect.dataset.filteredItems = JSON.stringify(items);
}

function syncSelectedExceptionItem() {
  const items = JSON.parse(els.exceptionItemSelect.dataset.filteredItems || "[]");
  const item = items[Number(els.exceptionItemSelect.value)];
  if (!item) return;
  els.exceptionBilledQtyInput.value = item.quantity ?? item.qty ?? "";
  els.exceptionBilledMrpInput.value = item.mrp ?? item.billedMrp ?? "";
}

function addItemException(event) {
  event.preventDefault();
  const items = JSON.parse(els.exceptionItemSelect.dataset.filteredItems || "[]");
  const item = items[Number(els.exceptionItemSelect.value)] || {};
  const current = collectSelectedShortageItems();
  current.push({
    productName: item.name || item.productName || "Manual item",
    billedQuantity: Number(els.exceptionBilledQtyInput.value || 0),
    shortQuantity: Math.max(0, Number(els.exceptionBilledQtyInput.value || 0) - Number(els.exceptionActualQtyInput.value || 0)),
    actualQuantity: Number(els.exceptionActualQtyInput.value || 0),
    reason: els.exceptionReasonInput.value,
    note: els.exceptionNoteInput.value.trim(),
    exceptionType: els.exceptionTypeInput.value,
    billedMrp: Number(els.exceptionBilledMrpInput.value || 0),
    actualMrp: Number(els.exceptionActualMrpInput.value || 0),
  });
  renderSelectedShortageItems(current);
  renderExceptionSummary(current);
  els.itemExceptionDialog.close();
  els.itemExceptionForm.reset();
}

function renderExceptionSummary(items = collectSelectedShortageItems()) {
  els.exceptionSummaryList.innerHTML = items.map((item) => `
    <article class="exception-pill">
      <strong>${item.productName}</strong>
      <span>${item.exceptionType || "difference"} ? billed ${item.billedQuantity || 0} ? delivered ${deliveredQuantity(item)} ? short ${item.shortQuantity || 0}</span>
    </article>
  `).join("");
}

function renderPackingPhotoPreview(photos) {
  if (!photos.length) {
    els.packingPhotoPreviewGrid.innerHTML = `<p class="muted-copy">No photos uploaded yet.</p>`;
    return;
  }
  els.packingPhotoPreviewGrid.innerHTML = photos.map((photo, index) => `
    <a class="photo-preview-card" href="${photo.fileUrl}" target="_blank">
      <img src="${photo.fileUrl}" alt="Packing photo ${index + 1}" loading="lazy" decoding="async" />
      <span>${photo.photoType === "pre-dispatch" ? "Pre-dispatch" : "Final packing"}</span>
    </a>
  `).join("");
}

async function savePacking({ refreshAfter = true } = {}) {
  const job = byId(state.selectedDispatcherJobId);
  if (!job) return false;
  const response = await fetch(`/api/dispatches/${job.id}/packing`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      packingType: "Mixed",
      packingBreakup: collectPackingLines(),
      orderCaseCount: job.orderCaseCount,
      dispatcherNote: els.dispatcherNoteInput.value.trim(),
      shortageReason: collectSelectedShortageItems().length ? "Item difference recorded" : "",
      shortageNote: els.shortageNoteInput.value.trim(),
      shortageItems: collectSelectedShortageItems(),
    }),
  });
  const data = await response.json();
  if (!response.ok) {
    toast(data.error || "Internet issue. Try again", "error");
    return false;
  }
  upsertJob(data);
  if (refreshAfter) await refresh("Saved");
  return true;
}

async function uploadPackingPhotos(fileList) {
  const files = [...(fileList || [])];
  if (!files.length) return;
  setPhotoBusy("packing", true);
  let uploaded = 0;
  try {
    const saved = await savePacking({ refreshAfter: false });
    if (!saved) return;
    for (const file of files) {
      const optimized = await optimizePhotoForUpload(file);
      if (await uploadDispatcherPhoto("product-photo", optimized, "Packing photo uploaded", "final-packing", false)) uploaded += 1;
    }
  } finally {
    els.packingCameraInput.value = "";
    els.packingFileInput.value = "";
    setPhotoBusy("packing", false);
  }
  renderDispatcher();
  if (uploaded) toast("Packing photo uploaded");
}

async function uploadGoodsPhotos(fileList) {
  const files = [...(fileList || [])];
  if (!files.length) return;
  setPhotoBusy("goods", true);
  let uploaded = 0;
  try {
    for (const file of files) {
      const optimized = await optimizePhotoForUpload(file);
      if (await uploadDispatcherPhoto("product-photo", optimized, "Goods photo uploaded", "goods-check", false)) uploaded += 1;
    }
  } finally {
    els.goodsCameraInput.value = "";
    els.goodsFileInput.value = "";
    setPhotoBusy("goods", false);
  }
  renderDispatcher();
  if (uploaded) toast("Goods photo uploaded");
}

function openCameraInput(input) {
  input.value = "";
  input.click();
}

function setPhotoBusy(kind, busy) {
  state.photoUploadBusy = busy;
  const isGoods = kind === "goods";
  const label = isGoods ? els.goodsPhotoLabel : els.packingPhotoLabel;
  const cameraButton = isGoods ? els.goodsCameraButton : els.packingCameraButton;
  const fileInput = isGoods ? els.goodsFileInput : els.packingFileInput;
  cameraButton.disabled = busy;
  fileInput.disabled = busy;
  if (busy) label.textContent = "Uploading photo...";
}

async function optimizePhotoForUpload(file) {
  if (!file?.type?.startsWith("image/")) return file;
  try {
    const image = await loadImageForCompression(file);
    if (file.size <= 450_000) return file;
    const maxSide = 1024;
    const scale = Math.min(1, maxSide / Math.max(image.width, image.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(image.width * scale));
    canvas.height = Math.max(1, Math.round(image.height * scale));
    const ctx = canvas.getContext("2d", { alpha: false });
    ctx.drawImage(image.source, 0, 0, canvas.width, canvas.height);
    image.cleanup();
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.66));
    return blob ? new File([blob], file.name.replace(/\.[^.]+$/, ".jpg"), { type: "image/jpeg" }) : file;
  } catch (_) {
    return file;
  }
}

async function loadImageForCompression(file) {
  if ("createImageBitmap" in window) {
    const bitmap = await createImageBitmap(file);
    return {
      source: bitmap,
      width: bitmap.width,
      height: bitmap.height,
      cleanup: () => bitmap.close?.(),
    };
  }
  const url = URL.createObjectURL(file);
  const image = new Image();
  await new Promise((resolve, reject) => {
    image.onload = resolve;
    image.onerror = reject;
    image.src = url;
  });
  return {
    source: image,
    width: image.naturalWidth || image.width,
    height: image.naturalHeight || image.height,
    cleanup: () => URL.revokeObjectURL(url),
  };
}

async function uploadDispatcherPhoto(path, file, message, photoType = "final-packing", refreshAfter = true) {
  const job = byId(state.selectedDispatcherJobId);
  if (!job || !file) return false;
  const fd = new FormData();
  fd.append("file", file);
  fd.append("photoType", photoType);
  const response = await fetch(`/api/dispatches/${job.id}/${path}`, { method: "POST", body: fd });
  const data = await response.json();
  if (!response.ok) {
    toast(data.error || "Internet issue. Try again", "error");
    return false;
  }
  upsertJob(data);
  if (refreshAfter) await refresh(message);
  return true;
}

async function submitReview() {
  const job = byId(state.selectedDispatcherJobId);
  if (!job) return;
  const saved = await savePacking({ refreshAfter: false });
  if (!saved) return;
  const response = await fetch(`/api/dispatches/${job.id}/submit-review`, { method: "POST" });
  const data = await response.json();
  if (!response.ok) return toast(data.error, "error");
  await refresh("Submitted");
}

async function submitGoodsReview() {
  const job = byId(state.selectedDispatcherJobId);
  if (!job) return;
  const response = await fetch(`/api/dispatches/${job.id}/submit-goods-review`, { method: "POST" });
  const data = await response.json();
  if (!response.ok) return toast(data.error || "Internet issue. Try again", "error");
  await refresh("Goods submitted");
}

function renderReviewer() {
  renderMetrics(els.reviewerMetrics, [
    ["Total Jobs", state.jobs.length],
    ["Submitted for Review", jobsBy("submitted-for-review").length],
    ["Open Jobs", state.jobs.filter((j) => ["ready", "assigned", "goods-photo-uploaded", "goods-needs-correction", "goods-approved", "packing", "needs-correction"].includes(j.currentStatus)).length],
    ["Dispatch / Delivery Pending", state.jobs.filter((j) => ["approved-by-reviewer", "dispatch-pending", "dispatched", "delivered"].includes(j.currentStatus)).length],
    ["Completed Today", jobsBy("completed").length],
    ["Needs Correction", state.jobs.filter((j) => ["goods-needs-correction", "needs-correction"].includes(j.currentStatus)).length],
  ]);
  renderTabs(els.reviewerTabs, [
    ["overview", "Overview"],
    ["review", "Packing Review", jobsBy("submitted-for-review").length],
    ["dispatch", "Dispatch", state.jobs.filter((j) => ["approved-by-reviewer", "dispatch-pending", "dispatched", "delivered"].includes(j.currentStatus)).length],
    ["completed", "Completed", state.jobs.filter((j) => ["completed", "cancelled"].includes(j.currentStatus)).length],
    ["activity", "Log"],
  ], state.reviewerTab, (id) => { state.reviewerTab = id; renderReviewer(); });
  const activity = state.reviewerTab === "activity";
  const overview = state.reviewerTab === "overview";
  els.reviewerActivityPanel.classList.toggle("hidden", !activity);
  els.reviewerDetailPanel.classList.toggle("hidden", activity || overview);
  els.reviewerList.parentElement.classList.toggle("hidden", activity);
  if (activity) return renderAllActivity(els.reviewerActivityLog);
  if (overview) return renderReviewerOverview();
  const jobs = reviewerTabJobs();
  els.reviewerList.replaceChildren(createJobTable(jobs));
  if (!jobs.some((job) => job.id === state.selectedReviewerJobId)) state.selectedReviewerJobId = jobs[0]?.id || "";
  els.reviewerDetailPanel.classList.toggle("hidden", !jobs.length);
  renderReviewerDetail();
}

function reviewerTabJobs() {
  const searchableJobs = filterJobs(state.jobs, els.reviewerSearchInput.value);
  return {
    review: [
      ...searchableJobs.filter((j) => j.currentStatus === "submitted-for-review"),
      ...searchableJobs.filter((j) => ["goods-approved", "packing", "needs-correction"].includes(j.currentStatus)),
    ],
    dispatch: searchableJobs.filter((j) => ["approved-by-reviewer", "dispatch-pending", "dispatched", "delivered"].includes(j.currentStatus)),
    completed: searchableJobs.filter((j) => ["completed", "cancelled"].includes(j.currentStatus)),
  }[state.reviewerTab] || [];
}

function createJobTable(jobs) {
  return table(
    ["Party", "City", "Cases", "Status"],
    jobs.map((j) => [j.partyName, j.partyCity, j.orderCaseCount, badge(j.currentStatus)]),
    jobs.map((j) => j.id),
    (id) => { state.selectedReviewerJobId = id; renderReviewerDetail(); },
  );
}

function renderReviewerOverview() {
  const searchableJobs = filterJobs(state.jobs, els.reviewerSearchInput.value);
  const groups = [
    ["Submitted for Review", searchableJobs.filter((job) => job.currentStatus === "submitted-for-review")],
    ["Open Jobs", searchableJobs.filter((job) => ["ready", "assigned", "goods-photo-uploaded", "goods-needs-correction", "goods-approved", "packing", "needs-correction"].includes(job.currentStatus))],
    ["Sent to Transport / Dispatch", searchableJobs.filter((job) => ["approved-by-reviewer", "dispatch-pending", "dispatched", "delivered"].includes(job.currentStatus))],
    ["Completed", searchableJobs.filter((job) => job.currentStatus === "completed")],
  ];
  els.reviewerList.innerHTML = groups.map(([title, jobs]) => `
    <section class="overview-group">
      <div class="section-header compact-header">
        <div><p class="eyebrow">${jobs.length} job${jobs.length === 1 ? "" : "s"}</p><h3>${title}</h3></div>
      </div>
      <div class="overview-job-list">
        ${jobs.slice(0, 5).map((job) => `
          <button class="overview-job-row" type="button" data-reviewer-job="${job.id}">
            <strong>${job.partyName}</strong>
            <span>${job.partyCity}</span>
            ${badge(job.currentStatus)}
          </button>
        `).join("") || `<p class="muted-copy">No jobs.</p>`}
      </div>
    </section>
  `).join("");
  els.reviewerList.querySelectorAll("[data-reviewer-job]").forEach((button) => {
    button.addEventListener("click", () => {
      const job = byId(button.dataset.reviewerJob);
      state.reviewerTab = reviewerTabForStatus(job?.currentStatus);
      state.selectedReviewerJobId = button.dataset.reviewerJob;
      renderReviewer();
    });
  });
}

function reviewerTabForStatus(status) {
  if (["completed", "cancelled"].includes(status)) return "completed";
  if (["approved-by-reviewer", "dispatch-pending", "dispatched", "delivered"].includes(status)) return "dispatch";
  return "review";
}

function renderReviewerDetail() {
  const job = byId(state.selectedReviewerJobId);
  if (!job) return;
  els.reviewerDetailTitle.textContent = `${job.partyName} — ${job.partyCity}`;
  els.reviewerBillGrid.innerHTML = readonly([
    ["Invoice date", job.invoiceDate || "—"],
    ["Amount", job.invoiceAmount ?? "—"],
    ["Order cases", job.orderCaseCount],
  ]);
  els.reviewerBillItems.innerHTML = renderBillItems(job.billItems || []);
  els.reviewerBillLink.innerHTML = fileLink(job.billFileUrl, "Open bill");
  els.reviewerPackingGrid.innerHTML = readonly([
    ["Total packages", job.totalPackages || 0],
    ["Total packed cases", job.totalPackedCases || 0],
    ["Dispatcher", userName(job.dispatcherId)],
  ]);
  els.reviewerGoodsGrid.innerHTML = readonly([
    ["Goods photos", job.goodsCheck?.photos?.length || 0],
    ["Goods stage", goodsStageLabel(job.currentStatus)],
  ]);
  els.reviewerPackingTable.innerHTML = renderPackingReviewTable(job.packingDetails.packingBreakup || []);
  const hasPacking = (job.packingDetails.packingBreakup || []).length > 0;
  const hasCaseMismatch = hasPacking && job.totalPackedCases !== job.orderCaseCount;
  const hasItemDifference = (job.shortageItems || []).length > 0;
  els.reviewerShortageBlock.classList.toggle("hidden", !(job.shortageReason || hasCaseMismatch || hasItemDifference));
  els.reviewerShortageBlock.innerHTML = renderReviewerDifferenceBlock(job, hasCaseMismatch);
  els.reviewerPackingPhotoLink.innerHTML = (job.packingDetails.packingPhotos || []).map((photo, index) => fileLink(photo.fileUrl, `${photo.photoType === "pre-dispatch" ? "Pre-dispatch" : "Final packing"} photo ${index + 1}`)).join("<br>");
  els.reviewerGoodsPhotoLink.innerHTML = (job.goodsCheck?.photos || []).map((photo, index) => fileLink(photo.fileUrl, `Goods photo ${index + 1}`)).join("<br>") || `<span class="muted-copy">No goods photos yet.</span>`;
  els.goodsReviewerNoteInput.value = job.goodsCheck?.reviewerNote || "";
  els.reviewerNoteInput.value = job.reviewerNote || job.reviewDetails.reviewerNote || "";
  els.deliveryPartnerInput.value = job.deliveryPartnerName || "";
  els.transportModeInput.value = job.transportMode || (job.extractedBillData?.transporter ? "Transport" : "");
  els.transportNameInput.value = job.transportName || job.extractedBillData?.transporter || "";
  els.deliveryRouteInput.value = job.deliveryRoute || "";
  els.biltyPackageCountInput.value = job.biltyDetails.biltyPackageCount ?? "";
  els.freightAmountInput.value = job.biltyDetails.freightAmount ?? job.extractedBillData?.freightAmount ?? "";
  els.optionalReferenceInput.value = job.biltyDetails.optionalReferenceNumber || "";
  els.packageDifferenceReasonInput.value = job.packageDifferenceReason || "";
  els.packageDifferenceNoteInput.value = job.packageDifferenceNote || "";
  els.biltyPhotoLabel.textContent = job.biltyDetails.biltyPhotoUrl ? "Bilty photo uploaded" : "Upload bilty photo";
  const awaitingReview = job.currentStatus === "submitted-for-review";
  const approvedOrLater = ["approved-by-reviewer", "dispatch-pending", "dispatched", "delivered", "completed"].includes(job.currentStatus);
  els.goodsReviewDecisionForm.classList.add("hidden");
  els.reviewDecisionForm.classList.toggle("hidden", !awaitingReview);
  els.reviewApprovedBanner.classList.toggle("hidden", !approvedOrLater);
  const canSend = ["approved-by-reviewer", "dispatch-pending"].includes(job.currentStatus);
  const canComplete = ["dispatched", "delivered"].includes(job.currentStatus);
  [
    els.deliveryPartnerInput,
    els.transportModeInput,
    els.transportNameInput,
    els.deliveryRouteInput,
    els.markDispatchedButton,
  ].forEach((control) => control.disabled = !canSend);
  [
    els.biltyPackageCountInput,
    els.optionalReferenceInput,
    els.biltyPhotoInput,
    els.markCompletedButton,
  ].forEach((control) => control.disabled = !canComplete);
  els.reviewerCompletionForm.classList.toggle("hidden", !canComplete);
  syncTransportModeState();
  syncDifferenceWarning();
}

function renderBillItems(items) {
  if (!items.length) return `<p class="muted-copy">Bill items not captured.</p>`;
  return `<div class="bill-items-grid">${items.map((item) => `<div><strong>${item.name || item.productName || "Item"}</strong><span>${item.quantity ?? item.qty ?? ""}</span></div>`).join("")}</div>`;
}

function renderPackingReviewTable(lines) {
  if (!lines.length) return `<p class="muted-copy">No packing breakup added.</p>`;
  return `
    <table class="mini-table">
      <thead><tr><th>Type</th><th>Packages</th><th>Cases / Package</th><th>Total Cases</th></tr></thead>
      <tbody>${lines.map((line) => `<tr><td>${line.packageType}</td><td>${line.packageCount}</td><td>${line.casesPerPackage}</td><td>${line.totalCases}</td></tr>`).join("")}</tbody>
    </table>
  `;
}

function renderReviewerDifferenceBlock(job, hasCaseMismatch) {
  const rows = (job.shortageItems || []).map((item) => `
    <div class="difference-card">
      <strong>${item.productName || "Item"}</strong>
      <div class="difference-stats">
        <span><em>Billed</em>${item.billedQuantity || 0}</span>
        <span><em>Delivered</em>${deliveredQuantity(item)}</span>
        <span><em>Short</em>${item.shortQuantity || 0}</span>
      </div>
      <small>${item.exceptionType || "short"}${item.reason ? ` ? ${item.reason}` : ""}${item.note ? ` ? ${item.note}` : ""}</small>
    </div>
  `).join("");
  return `
    <strong>Item difference</strong>
    ${job.shortageReason ? `<p>${job.shortageReason}${job.shortageNote ? ` ? ${job.shortageNote}` : ""}</p>` : ""}
    ${hasCaseMismatch ? `<p>Packed cases ${job.totalPackedCases || 0} vs order cases ${job.orderCaseCount || 0}</p>` : ""}
    ${rows || `<p>No item-level details recorded.</p>`}
  `;
}

async function reviewDecision(decision) {
  const job = byId(state.selectedReviewerJobId);
  if (!job) return;
  const response = await fetch(`/api/dispatches/${job.id}/review-decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision, reviewerNote: els.reviewerNoteInput.value.trim() }),
  });
  const data = await response.json();
  if (!response.ok) return toast(data.error, "error");
  if (decision === "approve") {
    state.reviewerTab = "dispatch";
    state.selectedReviewerJobId = job.id;
  }
  await refresh("Review saved");
}

async function goodsReviewDecision(decision) {
  const job = byId(state.selectedReviewerJobId);
  if (!job) return;
  const response = await fetch(`/api/dispatches/${job.id}/goods-review-decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision, reviewerNote: els.goodsReviewerNoteInput.value.trim() }),
  });
  const data = await response.json();
  if (!response.ok) return toast(data.error || "Internet issue. Try again", "error");
  await refresh("Goods review saved");
}

function reviewerDispatchPayload() {
  return {
    deliveryPartnerName: els.deliveryPartnerInput.value.trim(),
    transportMode: els.transportModeInput.value,
    transportName: els.transportNameInput.value.trim(),
    deliveryRoute: els.deliveryRouteInput.value,
    biltyPackageCount: els.biltyPackageCountInput.value,
    freightAmount: els.freightAmountInput.value,
    optionalReferenceNumber: els.optionalReferenceInput.value.trim(),
    packageDifferenceReason: els.packageDifferenceReasonInput.value,
    packageDifferenceNote: els.packageDifferenceNoteInput.value.trim(),
  };
}

async function saveReviewerDispatch({ refreshAfter = true } = {}) {
  const job = byId(state.selectedReviewerJobId);
  if (!job) return false;
  const response = await fetch(`/api/dispatches/${job.id}/reviewer-dispatch`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(reviewerDispatchPayload()),
  });
  const data = await response.json();
  if (!response.ok) {
    toast(data.error, "error");
    return false;
  }
  upsertJob(data);
  if (refreshAfter) await refresh("Details saved");
  return true;
}

async function uploadBiltyPhoto() {
  const job = byId(state.selectedReviewerJobId);
  const file = els.biltyPhotoInput.files?.[0];
  if (!job || !file) return;
  const saved = await saveReviewerDispatch({ refreshAfter: false });
  if (!saved) return;
  const fd = new FormData();
  fd.append("file", file.type?.startsWith("image/") ? await optimizePhotoForUpload(file) : file);
  const response = await fetch(`/api/dispatches/${job.id}/bilty-photo`, { method: "POST", body: fd });
  const data = await response.json();
  if (!response.ok) return toast(data.error, "error");
  els.biltyPhotoInput.value = "";
  upsertJob(data);
  await refresh("Bilty photo uploaded");
}

function syncDifferenceWarning() {
  const job = byId(state.selectedReviewerJobId);
  if (!job) return;
  const biltyCount = Number(els.biltyPackageCountInput.value || 0);
  const totalPackages = Number(job.totalPackages || 0);
  const hasCount = els.biltyPackageCountInput.value !== "";
  const difference = biltyCount - totalPackages;
  els.packageDiffBlock.classList.toggle("hidden", !hasCount || difference === 0);
  els.packageDiffText.textContent = hasCount && difference !== 0
    ? `Bilty differs by ${Math.abs(difference)} package${Math.abs(difference) === 1 ? "" : "s"}. Select reason.`
    : "";
}

function syncTransportModeState() {
  const isSelfLike = els.transportModeInput.value && els.transportModeInput.value !== "Transport";
  const job = byId(state.selectedReviewerJobId);
  const canSend = !!job && ["approved-by-reviewer", "dispatch-pending"].includes(job.currentStatus);
  els.transportNameInput.disabled = !canSend || isSelfLike;
  els.transportNameInput.placeholder = isSelfLike ? "N/A" : "";
  if (isSelfLike) els.transportNameInput.value = "";
  if (!isSelfLike && !els.transportNameInput.value && job?.extractedBillData?.transporter) {
    els.transportNameInput.value = job.extractedBillData.transporter;
  }
  const canComplete = !!job && ["dispatched", "delivered"].includes(job.currentStatus);
  const biltyNA = isSelfLike && canComplete;
  [els.biltyPackageCountInput, els.freightAmountInput, els.optionalReferenceInput, els.biltyPhotoInput].forEach((control) => {
    control.disabled = biltyNA || !canComplete;
  });
  els.biltyPackageCountInput.placeholder = biltyNA ? "N/A" : "";
  els.optionalReferenceInput.placeholder = biltyNA ? "N/A" : "";
  if (biltyNA) {
    els.biltyPackageCountInput.value = "";
    els.freightAmountInput.value = "";
    els.optionalReferenceInput.value = "";
    els.biltyPhotoLabel.textContent = "Not required";
    els.packageDiffBlock.classList.add("hidden");
  }
}

async function markDispatched() {
  const saved = await saveReviewerDispatch({ refreshAfter: false });
  if (!saved) return;
  await reviewerStatusAction("mark-dispatched", els.transportModeInput.value === "Self" ? "Completed" : "Sent to dispatch");
}
async function markCompleted() {
  const job = byId(state.selectedReviewerJobId);
  if (!job) return;
  const requiresBilty = (job.transportMode || els.transportModeInput.value) === "Transport";
  if (requiresBilty) {
    const saved = await saveReviewerDispatch({ refreshAfter: false });
    if (!saved) return;
  }
  await reviewerStatusAction("mark-completed", "Completed");
}

async function reviewerStatusAction(action, success) {
  const job = byId(state.selectedReviewerJobId);
  if (!job) return;
  const response = await fetch(`/api/dispatches/${job.id}/${action}`, { method: "POST" });
  const data = await response.json();
  if (!response.ok) return toast(data.error, "error");
  await refresh(success);
}

function renderAdmin() {
  renderMetrics(els.adminMetrics, [
    ["Total Jobs", state.jobs.length],
    ["Ready", jobsBy("ready").length],
    ["Pending Review", jobsBy("submitted-for-review").length],
    ["Dispatch Pending", jobsBy("dispatch-pending").length],
    ["Completed", jobsBy("completed").length],
  ]);
  renderTabs(els.adminTabs, [
    ["overview", "Today"],
    ["jobs", "All Jobs"],
    ["routes", "Routes"],
    ["reports", "Reports"],
    ["users", "Users"],
    ["activity", "Logs"],
    ["settings", "Settings"],
  ], state.adminTab, (id) => { state.adminTab = id; renderAdmin(); });
  ["adminOverviewPanel", "adminJobsPanel", "adminRoutesPanel", "adminUsersPanel", "adminReportsPanel", "adminActivityPanel", "adminSettingsPanel"].forEach((id) => els[id].classList.add("hidden"));
  if (state.adminTab === "overview") renderAdminOverview();
  if (state.adminTab === "jobs") renderAdminJobs();
  if (state.adminTab === "routes") renderRoutes();
  if (state.adminTab === "users") renderUsers();
  if (state.adminTab === "reports") renderReports();
  if (state.adminTab === "activity") { els.adminActivityPanel.classList.remove("hidden"); renderAllActivity(els.adminActivityLog); }
  if (state.adminTab === "settings") {
    els.adminSettingsPanel.classList.remove("hidden");
    renderDeliveryPartnerDirectory();
    els.dispatcherRoleLabelInput.value = roleLabel("dispatcher");
    els.reviewerRoleLabelInput.value = roleLabel("reviewer");
  }
}

function renderAdminOverview() {
  els.adminOverviewPanel.classList.remove("hidden");
  const jobs = filterJobs(state.jobs, els.adminSearchInput.value);
  const previousDate = els.adminOverviewPanel.querySelector("#adminOverviewDateInput")?.value;
  const selectedDate = previousDate || today();
  const dayJobs = jobs.filter((job) => job.dispatchDate === selectedDate);
  const issueJobs = dayJobs.filter((job) => job.shortageReason || (job.shortageItems || []).length || job.currentStatus === "needs-correction");
  const totalPackages = dayJobs.reduce((sum, job) => sum + Number(job.totalPackages || 0), 0);
  const totalPackedCases = dayJobs.reduce((sum, job) => sum + Number(job.totalPackedCases || 0), 0);
  els.adminOverviewPanel.innerHTML = `
    <div class="section-header">
      <div><p class="eyebrow">Daily dispatch view</p><h3>${selectedDate}</h3></div>
      <label class="field compact-date-field"><span>Date</span><input id="adminOverviewDateInput" type="date" value="${selectedDate}" /></label>
    </div>
    <div class="metric-grid compact-summary-grid top-gap">
      ${[
        ["Dispatches", dayJobs.length],
        ["Packages", totalPackages],
        ["Packed Cases", totalPackedCases],
        ["Issues", issueJobs.length],
        ["Sent to Dispatch", dayJobs.filter((job) => ["dispatched", "delivered", "completed"].includes(job.currentStatus)).length],
        ["Completed", dayJobs.filter((job) => job.currentStatus === "completed").length],
      ].map(([label, value]) => `<article class="metric-card"><span>${label}</span><strong>${value}</strong></article>`).join("")}
    </div>
    <div class="responsive-table-wrap top-gap" id="adminTodayTable"></div>
  `;
  els.adminOverviewPanel.querySelector("#adminOverviewDateInput").addEventListener("input", renderAdminOverview);
  els.adminOverviewPanel.querySelector("#adminTodayTable").replaceChildren(createAdminJobTable(dayJobs, (id) => {
    state.selectedAdminJobId = id;
    state.adminTab = "jobs";
    renderAdmin();
  }));
}

function renderAdminJobs() {
  els.adminJobsPanel.classList.remove("hidden");
  const jobs = filterJobs(state.jobs, els.adminSearchInput.value);
  els.adminJobsTable.replaceChildren(createAdminJobTable(jobs));
  if (!jobs.some((job) => job.id === state.selectedAdminJobId)) state.selectedAdminJobId = jobs[0]?.id || "";
  renderAdminEdit();
}

function createAdminJobTable(jobs, onClick = (id) => { state.selectedAdminJobId = id; renderAdminEdit(); }) {
  return table(
    ["Entry", "Party", "City", "Status", "Dispatcher"],
    jobs.map((job) => [job.dailyEntryNo || "—", job.partyName, job.partyCity, badge(job.currentStatus), userName(job.dispatcherId)]),
    jobs.map((job) => job.id),
    onClick,
  );
}

function renderAdminEdit() {
  const job = byId(state.selectedAdminJobId);
  if (!job) return;
  els.adminEditTitle.textContent = `${job.partyName} — ${job.partyCity}`;
  els.adminPartyInput.value = job.partyName || "";
  els.adminCityInput.value = job.partyCity || "";
  els.adminCasesInput.value = job.orderCaseCount || "";
  const dispatchers = state.users.filter((user) => user.role === "dispatcher");
  els.adminDispatcherInput.innerHTML = `<option value=""></option>${dispatchers.map((user) => `<option value="${user.id}">${user.name}</option>`).join("")}`;
  els.adminDispatcherInput.value = job.dispatcherId || "";
  els.adminStatusInput.value = job.currentStatus;
  els.adminTimingGrid.innerHTML = readonly([
    ["Dispatcher time", formatMinutes(minutesBetween(job.timestamps.jobClaimedAt, job.timestamps.submittedForReviewAt))],
    ["Reviewer time", formatMinutes(minutesBetween(job.timestamps.submittedForReviewAt, job.timestamps.reviewerApprovedAt))],
    ["Total cycle time", formatMinutes(minutesBetween(job.timestamps.billUploadedAt, job.timestamps.completedAt || job.timestamps.deliveredAt || job.timestamps.dispatchedAt))],
  ]);
}

async function saveAdminEdit(event) {
  event.preventDefault();
  const job = byId(state.selectedAdminJobId);
  if (!job) return;
  const response = await fetch(`/api/dispatches/${job.id}/admin`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      partyName: els.adminPartyInput.value.trim(),
      place: els.adminCityInput.value.trim(),
      totalCases: Number(els.adminCasesInput.value || 0),
      dispatcherId: els.adminDispatcherInput.value,
      currentStatus: els.adminStatusInput.value,
    }),
  });
  const data = await response.json();
  if (!response.ok) return toast(data.error, "error");
  await refresh("Edit saved");
}

function renderRoutes() {
  els.adminRoutesPanel.classList.remove("hidden");
  els.routeConfigList.innerHTML = state.routes.map((route) => `
    <label class="field">
      <span>Route ${route.id}</span>
      <input data-route-input="${route.id}" value="${route.name}" />
    </label>
  `).join("");
  els.routeConfigList.innerHTML += `<button class="secondary-button" type="submit">Save Route Names</button>`;
  els.routeConfigList.onsubmit = saveRouteNames;
  els.routeBatchRouteInput.innerHTML = state.routes.map((route) => `<option>${route.name}</option>`).join("");
  els.routeBatchList.innerHTML = state.routeBatches.map((batch) => `<article class="report-card"><strong>${batch.route_name}</strong><span>${batch.delivery_partner_name || "No partner"} ? ${batch.status}</span></article>`).join("") || `<p class="muted-copy">No batches yet.</p>`;
}

async function saveRouteNames(event) {
  event.preventDefault();
  for (const input of els.routeConfigList.querySelectorAll("[data-route-input]")) {
    const response = await fetch(`/api/routes/${input.dataset.routeInput}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: input.value.trim() }),
    });
    if (!response.ok) {
      const data = await response.json();
      return toast(data.error, "error");
    }
  }
  await refresh("Route names saved");
}

async function createRouteBatch(event) {
  event.preventDefault();
  const tokens = els.routeBatchJobsInput.value.split(",").map((v) => v.trim()).filter(Boolean);
  const jobIds = state.jobs.filter((job) => tokens.includes(job.invoiceNumber) || tokens.includes(job.id)).map((job) => job.id);
  const response = await fetch("/api/route-batches", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ routeName: els.routeBatchRouteInput.value, deliveryPartnerName: els.routeBatchPartnerInput.value.trim(), jobIds }),
  });
  const data = await response.json();
  if (!response.ok) return toast(data.error, "error");
  await refresh("Route batch created");
}

function renderUsers() {
  els.adminUsersPanel.classList.remove("hidden");
  els.userManagementList.innerHTML = `
    <form id="createUserForm" class="user-create-card">
      <h3>Add team member</h3>
      <label class="field"><span>Name</span><input data-new-user-name required /></label>
      <label class="field"><span>User ID / Login</span><input data-new-user-login required autocomplete="off" /></label>
      <label class="field"><span>Password</span><input data-new-user-password type="text" required autocomplete="new-password" /></label>
      <label class="field"><span>Role</span><select data-new-user-role>
        <option value="dispatcher">${roleLabel("dispatcher")}</option>
        <option value="reviewer">${roleLabel("reviewer")}</option>
        <option value="admin">Admin</option>
      </select></label>
      <button class="primary-button" type="submit">Add User</button>
    </form>
  ` + state.users.map((user) => `
    <article class="user-row" data-user-row="${user.id}">
      <label class="field"><span>Name</span><input value="${escapeAttr(user.name)}" data-user-name /></label>
      <label class="field"><span>User ID / Login</span><input value="${escapeAttr(user.emailOrMobile || "")}" data-user-login autocomplete="off" /></label>
      <label class="field"><span>New Password</span><input data-user-password type="text" placeholder="Leave blank to keep same" autocomplete="new-password" /></label>
      <label class="field"><span>Role</span>
        <select data-user-role>
          ${["reviewer", "dispatcher", "admin"].map((role) => `<option value="${role}" ${role === user.role ? "selected" : ""}>${role}</option>`).join("")}
        </select>
      </label>
      <label class="field"><span>Active</span>
        <select data-user-active>
          <option value="true" ${user.activeStatus ? "selected" : ""}>Active</option>
          <option value="false" ${!user.activeStatus ? "selected" : ""}>Inactive</option>
        </select>
      </label>
      <button class="secondary-button" type="button" data-save-user="${user.id}">Save</button>
    </article>
  `).join("");
  els.userManagementList.querySelectorAll("[data-save-user]").forEach((button) => {
    button.addEventListener("click", () => saveUser(button.dataset.saveUser));
  });
  els.userManagementList.querySelector("#createUserForm").addEventListener("submit", createUser);
}

async function createUser(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const response = await fetch("/api/users", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: form.querySelector("[data-new-user-name]").value.trim(),
      login: form.querySelector("[data-new-user-login]").value.trim(),
      password: form.querySelector("[data-new-user-password]").value,
      role: form.querySelector("[data-new-user-role]").value,
    }),
  });
  const data = await response.json();
  if (!response.ok) return toast(data.error || "Internet issue. Try again", "error");
  await refresh("User added");
}

async function saveUser(userId) {
  const row = els.userManagementList.querySelector(`[data-user-row="${userId}"]`);
  const response = await fetch(`/api/users/${userId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: row.querySelector("[data-user-name]").value.trim(),
      login: row.querySelector("[data-user-login]").value.trim(),
      password: row.querySelector("[data-user-password]").value,
      role: row.querySelector("[data-user-role]").value,
      activeStatus: row.querySelector("[data-user-active]").value === "true",
    }),
  });
  const data = await response.json();
  if (!response.ok) return toast(data.error, "error");
  await refresh("User updated");
}

function renderReports() {
  els.adminReportsPanel.classList.remove("hidden");
  const selectedDate = document.querySelector("#reportDateInput")?.value || today();
  const jobTimings = (state.reports.jobTimings || []).filter((job) => !selectedDate || job.dispatchDate === selectedDate);
  const daySummary = (state.reports.dailySummary || []).find((day) => day.date === selectedDate) || {};
  els.adminReports.innerHTML = `
    <article class="report-card report-hero">
      <div class="section-header">
        <div><p class="eyebrow">Interactive reports</p><h3>${selectedDate}</h3></div>
        <label class="field compact-date-field"><span>Date</span><input id="reportDateInput" type="date" value="${selectedDate}" /></label>
      </div>
      <div class="report-kpi-grid">
        ${[
          ["Dispatches", daySummary.jobs || 0],
          ["Packages", daySummary.packages || 0],
          ["Freight", formatMoney(daySummary.freightAmount || 0)],
          ["Dispatcher time", formatMinutes(daySummary.dispatcherMinutes || 0)],
          ["Reviewer time", formatMinutes(daySummary.reviewerMinutes || 0)],
          ["Total cycle time", formatMinutes(daySummary.totalMinutes || 0)],
        ].map(([label, value]) => `<div><span>${label}</span><strong>${value}</strong></div>`).join("")}
      </div>
    </article>
    ${renderBarReport("Dispatcher productivity", state.reports.dispatcherWise || [], (row) => row.completedJobs || 0, "jobs")}
    ${renderBarReport("Reviewer approvals", state.reports.reviewerWise || [], (row) => row.approvals || 0, "checks")}
    ${renderBarReport("Transport usage", state.reports.transporterWise || [], (row) => row.total || 0, "jobs")}
    <article class="report-card report-table-card">
      <h4>Dispatch timing</h4>
      ${jobTimings.length ? `
        <table class="mini-table">
          <thead><tr><th>Party</th><th>Dispatcher</th><th>Reviewer</th><th>Total</th><th>Freight</th></tr></thead>
          <tbody>${jobTimings.map((job) => `<tr><td>${job.partyName} · ${job.partyCity}</td><td>${formatMinutes(job.dispatcherMinutes)}</td><td>${formatMinutes(job.reviewerMinutes)}</td><td>${formatMinutes(job.totalMinutes)}</td><td>${formatMoney(job.freightAmount || 0)}</td></tr>`).join("")}</tbody>
        </table>
      ` : `<p class="muted-copy">No jobs for this date.</p>`}
    </article>
  `;
  document.querySelector("#reportDateInput").addEventListener("input", renderReports);
}

function renderAllActivity(container) {
  const logs = state.jobs.flatMap((job) => job.activityLogs.map((log) => ({ ...log, job }))).sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  container.innerHTML = logs.map((log) => `<article class="timeline-entry"><strong>${log.userName} · ${actionLabel(log.actionType)}</strong><span>${log.job.invoiceNumber || "—"} · ${log.job.partyName}</span><time>${formatDateTime(log.createdAt)}</time></article>`).join("");
}


function openBulkImportDialog() {
  state.bulkDrafts = [];
  els.bulkImportRows.innerHTML = `<p class="muted-copy">Choose bill PDFs to begin.</p>`;
  els.bulkBillUploadLabel.textContent = "Choose multiple bill PDFs";
  els.bulkImportDialog.showModal();
}

async function prepareBulkImports() {
  const files = [...(els.bulkBillFilesInput.files || [])];
  if (!files.length) return;
  els.bulkBillUploadLabel.textContent = `${files.length} bill(s) selected`;
  els.bulkImportRows.innerHTML = `<p class="muted-copy">Reading bills...</p>`;
  state.bulkDrafts = [];
  for (const file of files) {
    const fd = new FormData();
    fd.append("file", file);
    const response = await fetch("/api/bills/extract", { method: "POST", body: fd });
    const data = await response.json();
    state.bulkDrafts.push(response.ok
      ? { fileName: file.name, fileUrl: data.fileUrl, extracted: data.extracted, route: suggestRouteForTransport(data.extracted.transporter || "") }
      : { fileName: file.name, error: data.error || "Could not read bill", extracted: {}, route: "" });
  }
  renderBulkImportRows();
}

function renderBulkImportRows() {
  els.bulkImportRows.innerHTML = state.bulkDrafts.map((draft, index) => `
    <article class="bulk-import-row" data-bulk-row="${index}">
      <strong>${draft.fileName}</strong>
      ${draft.error ? `<span class="muted-copy">${draft.error}</span>` : `
        <label class="field"><span>Party</span><input data-bulk-party value="${escapeHtml(draft.extracted.party || "")}" /></label>
        <label class="field"><span>City</span><input data-bulk-city value="${escapeHtml(draft.extracted.place || "")}" /></label>
        <label class="field"><span>Cases</span><input data-bulk-cases type="number" min="0" value="${draft.extracted.cases || ""}" /></label>
        <label class="field"><span>Route</span><select data-bulk-route>${routeOptions(draft.route)}</select></label>
      `}
      <button class="danger-button remove-bulk-row" type="button" data-remove-bulk="${index}">Remove</button>
    </article>
  `).join("");
  els.bulkImportRows.querySelectorAll("[data-remove-bulk]").forEach((button) => {
    button.addEventListener("click", () => removeBulkDraft(Number(button.dataset.removeBulk)));
  });
}

function renderGoodsPhotoPreview(photos) {
  if (!photos.length) {
    els.goodsPhotoPreviewGrid.innerHTML = `<p class="muted-copy">No goods photos uploaded yet.</p>`;
    return;
  }
  els.goodsPhotoPreviewGrid.innerHTML = photos.map((photo, index) => `
    <a class="photo-preview-card" href="${photo.fileUrl}" target="_blank">
      <img src="${photo.fileUrl}" alt="Goods photo ${index + 1}" loading="lazy" decoding="async" />
      <span>Goods photo ${index + 1}</span>
    </a>
  `).join("");
}

function removeBulkDraft(index) {
  state.bulkDrafts.splice(index, 1);
  renderBulkImportRows();
  if (!state.bulkDrafts.length) els.bulkImportRows.innerHTML = `<p class="muted-copy">No bills selected.</p>`;
}

async function createBulkJobs(event) {
  event.preventDefault();
  const rows = [...els.bulkImportRows.querySelectorAll("[data-bulk-row]")];
  let created = 0;
  for (const row of rows) {
    const draft = state.bulkDrafts[Number(row.dataset.bulkRow)];
    if (draft.error) continue;
    const payload = {
      dispatchDate: today(),
      deliveryRoute: row.querySelector("[data-bulk-route]").value,
      partyName: row.querySelector("[data-bulk-party]").value.trim(),
      partyCity: row.querySelector("[data-bulk-city]").value.trim(),
      place: row.querySelector("[data-bulk-city]").value.trim(),
      invoiceNumber: draft.extracted.invoice || "",
      invoiceDate: draft.extracted.billDate || "",
      orderCaseCount: Number(row.querySelector("[data-bulk-cases]").value || 0),
      invoiceAmount: Number(draft.extracted.totalAmount || 0) || null,
      billFileUrl: draft.fileUrl,
      extractedBillData: draft.extracted,
      billItems: draft.extracted.items || [],
    };
    const response = await fetch("/api/dispatches", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const data = await response.json();
    if (!response.ok) return toast(data.error || `Could not create ${draft.fileName}`, "error");
    created += 1;
  }
  els.bulkImportDialog.close();
  els.bulkBillFilesInput.value = "";
  state.bulkDrafts = [];
  await refresh(`${created} open job${created === 1 ? "" : "s"} created`);
}

async function uploadBill() {
  const file = els.billFileInput.files?.[0];
  if (!file) return;
  els.billUploadLabel.textContent = file.name;
  const fd = new FormData();
  fd.append("file", file);
  const response = await fetch("/api/bills/extract", { method: "POST", body: fd });
  const data = await response.json();
  if (!response.ok) return toast(data.error, "error");
  state.draftBillFileUrl = data.fileUrl;
  state.draftExtractedBillData = data.extracted;
  els.draftPartyInput.value = data.extracted.party || "";
  els.draftCityInput.value = data.extracted.place || "";
  els.draftInvoiceDateInput.value = data.extracted.billDate || "";
  els.draftOrderCasesInput.value = data.extracted.cases || "";
  els.draftAmountInput.value = data.extracted.totalAmount || "";
}

async function createJob(event) {
  event.preventDefault();
  const payload = {
    dispatchDate: els.draftDispatchDateInput.value || today(),
    deliveryRoute: els.draftRouteInput.value,
    partyName: els.draftPartyInput.value.trim(),
    partyCity: els.draftCityInput.value.trim(),
    place: els.draftCityInput.value.trim(),
    partyMobileNumber: els.draftMobileInput.value.trim(),
    invoiceNumber: state.draftExtractedBillData.invoice || "",
    invoiceDate: els.draftInvoiceDateInput.value,
    orderCaseCount: Number(els.draftOrderCasesInput.value || 0),
    invoiceAmount: Number(els.draftAmountInput.value || 0) || null,
    billFileUrl: state.draftBillFileUrl,
    extractedBillData: state.draftExtractedBillData,
    billItems: state.draftExtractedBillData.items || [],
  };
  const response = await fetch("/api/dispatches", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  const data = await response.json();
  if (!response.ok) return toast(data.error || "Internet issue. Try again", "error");
  els.newDispatchDialog.close();
  clearDraft();
  await refresh("Open job created");
}

function clearDraft() {
  els.createJobForm.reset();
  els.draftDispatchDateInput.value = today();
  fillDraftRoutes();
  els.billUploadLabel.textContent = "Upload bill PDF";
  state.draftBillFileUrl = "";
  state.draftExtractedBillData = {};
}

function suggestRouteForTransport(transporter) {
  if (!transporter) return "";
  const counts = new Map();
  state.jobs
    .filter((job) => job.transportName && job.deliveryRoute && job.transportName.toLowerCase() === transporter.toLowerCase())
    .forEach((job) => counts.set(job.deliveryRoute, (counts.get(job.deliveryRoute) || 0) + 1));
  return [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] || "";
}

function routeOptions(selected = "") {
  return `<option value=""></option>${state.routes.map((route) => `<option ${route.name === selected ? "selected" : ""}>${route.name}</option>`).join("")}`;
}

function renderDeliveryPartnerDirectory() {
  const names = [...new Set(state.deliveryPartners.map((item) => item.name).filter(Boolean))];
  els.deliveryPartnerDirectory.innerHTML = names.map((name) => `<option value="${escapeHtml(name)}"></option>`).join("");
  if (els.deliveryPartnerDirectoryAdmin) {
    els.deliveryPartnerDirectoryAdmin.innerHTML = names.map((name) => `<span class="directory-chip">${escapeHtml(name)}</span>`).join("") || `<p class="muted-copy">No delivery partners saved yet.</p>`;
  }
}

async function saveRoleLabels(event) {
  event.preventDefault();
  const response = await fetch("/api/settings", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      dispatcherLabel: els.dispatcherRoleLabelInput.value.trim(),
      reviewerLabel: els.reviewerRoleLabelInput.value.trim(),
    }),
  });
  const data = await response.json();
  if (!response.ok) return toast(data.error || "Internet issue. Try again", "error");
  await refresh("Titles saved");
  els.currentUserRole.textContent = roleLabel(state.me.role);
  renderRoleNav();
}

async function addDeliveryPartner(event) {
  event.preventDefault();
  const name = els.deliveryPartnerDirectoryInput.value.trim();
  if (!name) return;
  const response = await fetch("/api/delivery-partners", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  const data = await response.json();
  if (!response.ok) return toast(data.error || "Internet issue. Try again", "error");
  els.deliveryPartnerDirectoryInput.value = "";
  await refresh("Delivery partner added");
}

function autocompleteDeliveryPartner() {
  const value = els.deliveryPartnerInput.value.trim().toLowerCase();
  if (!value) return;
  const matches = state.deliveryPartners.filter((partner) => partner.name.toLowerCase().startsWith(value));
  if (matches.length === 1 && matches[0].name.toLowerCase() !== value) {
    els.deliveryPartnerInput.value = matches[0].name;
  }
}

function filterJobs(jobs, query) {
  const tokens = String(query || "").trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (!tokens.length) return jobs;
  return jobs.filter((job) => {
    const haystack = [
      job.partyName,
      job.partyCity,
      job.invoiceNumber,
      job.transportName,
      job.deliveryPartnerName,
      job.deliveryRoute,
      job.currentStatus,
      ...(job.billItems || []).map((item) => item.name || item.productName || ""),
      ...(job.shortageItems || []).map((item) => [item.productName, item.reason, item.note].join(" ")),
    ].join(" ").toLowerCase();
    return tokens.every((token) => haystack.includes(token));
  });
}

function renderBarReport(title, rows, valueOf, unit) {
  const max = Math.max(1, ...rows.map((row) => valueOf(row)));
  return `
    <article class="report-card chart-card">
      <h4>${title}</h4>
      ${rows.length ? rows.map((row) => {
        const value = valueOf(row);
        return `<div class="chart-row"><span>${row.name}</span><div><i style="width:${Math.max(6, Math.round((value / max) * 100))}%"></i></div><strong>${value} ${unit}</strong></div>`;
      }).join("") : `<p class="muted-copy">No data</p>`}
    </article>
  `;
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function roleLabel(role) {
  if (role === "dispatcher") return state.settings.dispatcher_label || "Dispatcher";
  if (role === "reviewer") return state.settings.reviewer_label || "Reviewer";
  return "Admin";
}

function formatMinutes(value = 0) {
  const minutes = Math.round(Number(value || 0));
  if (minutes < 60) return `${minutes}m`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

function formatMoney(value = 0) {
  return `₹${Number(value || 0).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

function deliveredQuantity(item) {
  const billed = Number(item.billedQuantity || 0);
  const short = Number(item.shortQuantity || 0);
  const actual = Number(item.actualQuantity || 0);
  return actual || Math.max(0, billed - short);
}

function minutesBetween(start, end) {
  if (!start || !end) return 0;
  return Math.max(0, Math.round((new Date(end) - new Date(start)) / 60000));
}

async function refresh(message = "") {
  await reloadData();
  if (state.roleView === "dispatcherDashboard") renderDispatcher();
  if (state.roleView === "reviewerDashboard") renderReviewer();
  if (state.roleView === "adminDashboard") renderAdmin();
  if (message) toast(message);
}

function startLiveRefresh() {
  stopLiveRefresh();
  state.liveRefreshTimer = setInterval(async () => {
    if (document.visibilityState !== "visible" || !state.me) return;
    if (state.photoUploadBusy) return;
    const focused = document.activeElement;
    const editing = focused && ["INPUT", "TEXTAREA", "SELECT"].includes(focused.tagName);
    const before = state.jobs.map((job) => `${job.id}:${job.updatedAt}`).join("|");
    try {
      await reloadData();
      const after = state.jobs.map((job) => `${job.id}:${job.updatedAt}`).join("|");
      if (before !== after && !editing) {
        if (state.roleView === "dispatcherDashboard") renderDispatcher();
        if (state.roleView === "reviewerDashboard") renderReviewer();
        if (state.roleView === "adminDashboard") renderAdmin();
      }
    } catch (_) {
      // Keep the screen usable if the local server briefly misses a poll.
    }
  }, 5000);
}

function stopLiveRefresh() {
  if (state.liveRefreshTimer) clearInterval(state.liveRefreshTimer);
  state.liveRefreshTimer = null;
}

function renderMetrics(container, items) {
  container.innerHTML = items.map(([label, value]) => `<article class="metric-card"><span>${label}</span><strong>${value}</strong></article>`).join("");
}

function renderJobCards(container, jobs, onClick) {
  container.innerHTML = "";
  if (!jobs.length) return container.innerHTML = `<div class="empty-state">No jobs here.</div>`;
  jobs.forEach((job) => {
    const card = document.importNode(els.jobCardTemplate.content, true).firstElementChild;
    card.querySelector('[data-field="party"]').textContent = job.partyName;
    card.querySelector('[data-field="meta"]').textContent = `${job.partyCity} • ${job.orderCaseCount} cases`;
    setStatus(card.querySelector('[data-field="status"]'), job.currentStatus);
    card.addEventListener("click", () => onClick(job.id));
    container.appendChild(card);
  });
}

function table(headers, rows, ids, onClick) {
  const t = document.createElement("table");
  t.className = "data-table";
  t.innerHTML = `<thead><tr>${headers.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody></tbody>`;
  rows.forEach((cells, index) => {
    const tr = document.createElement("tr");
    tr.innerHTML = cells.map((cell, i) => `<td data-label="${headers[i]}">${cell}</td>`).join("");
    tr.addEventListener("click", () => onClick(ids[index]));
    t.querySelector("tbody").appendChild(tr);
  });
  return t;
}

function readonly(items) {
  return items.map(([label, value]) => `<div><span>${label}</span><strong>${value}</strong></div>`).join("");
}

function byId(id) { return state.jobs.find((job) => job.id === id); }
function upsertJob(job) {
  const index = state.jobs.findIndex((item) => item.id === job.id);
  if (index === -1) state.jobs.unshift(job);
  else state.jobs[index] = job;
}
function jobsBy(status) { return state.jobs.filter((job) => job.currentStatus === status); }
function userName(id) { return state.directory.find((u) => u.id === id)?.name || "—"; }
function fileLink(url, label) { return url ? `<a href="${url}" target="_blank">${label}</a>` : "Not uploaded"; }
function badge(status) { return `<span class="status-pill ${status}">${statusLabel(status)}</span>`; }
function setStatus(el, status) { el.textContent = statusLabel(status); el.className = `status-pill ${status}`; }
function escapeAttr(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}
function today() { return new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10); }
function formatDateTime(value) { return new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)); }
function statusLabel(status) { return status.split("-").map((part) => part[0].toUpperCase() + part.slice(1)).join(" "); }
function actionLabel(action) { return action.replaceAll("_", " "); }
function toast(message, type = "success") {
  els.flashMessage.textContent = message;
  els.flashMessage.classList.remove("hidden");
  els.flashMessage.style.background = type === "error" ? "var(--red-soft)" : "var(--blue-soft)";
  els.flashMessage.style.color = type === "error" ? "var(--red)" : "var(--blue)";
  if (type === "error") highlightMissingField(message);
  showInlineToast(message, type);
  setTimeout(() => els.flashMessage.classList.add("hidden"), 2500);
}

function highlightMissingField(message) {
  const fieldMap = {
    "Upload goods photo": els.goodsPhotoPreviewGrid,
    "Upload packing photo": els.packingPhotoPreviewGrid,
    "Enter packing breakup": els.bankPackingGrid,
    "Select shortage reason": els.openExceptionDialogButton,
    "Packed cases do not match bill cases. Please correct the breakup or enter a valid reason.": els.openExceptionDialogButton,
    "Enter delivery partner name": els.deliveryPartnerInput,
    "Select transport mode": els.transportModeInput,
    "Select transport name": els.transportNameInput,
    "Upload bilty photo": els.biltyPhotoInput,
    "Enter freight amount": els.freightAmountInput,
    "Enter bilty package count": els.biltyPackageCountInput,
    "Select difference reason": els.packageDifferenceReasonInput,
  };
  const target = fieldMap[message];
  if (!target) return;
  target.classList.add("field-error");
  setTimeout(() => target.classList.remove("field-error"), 2200);
}

function showInlineToast(message, type) {
  document.querySelectorAll(".inline-toast").forEach((node) => node.remove());
  const anchor = document.activeElement instanceof HTMLElement ? document.activeElement : els.flashMessage;
  const rect = anchor.getBoundingClientRect();
  const popup = document.createElement("div");
  popup.className = `inline-toast ${type}`;
  popup.textContent = message;
  popup.style.left = `${Math.min(window.innerWidth - 220, Math.max(12, rect.left))}px`;
  popup.style.top = `${Math.max(12, rect.bottom + 8)}px`;
  document.body.appendChild(popup);
  setTimeout(() => popup.remove(), 2200);
}

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
