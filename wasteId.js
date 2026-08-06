/**
 * wasteId.js  (classic script — shares global scope with the big inline
 * <script> in index.html, exactly like ecoFeatures.js: `state`, `toast`,
 * `saveProgress`, `updateUI` are all reachable here as free variables.)
 * ------------------------------------------------------------
 * "Eco Waste Identification" — replaces the old photo-upload feature.
 * Instead of uploading a photo (which needed Firebase Storage, a
 * paid-plan feature), the student taps one of 10 pre-made waste-item
 * cards and instantly sees the waste category, recyclability,
 * disposal method, and an environmental tip from a curated local
 * knowledge base (WASTE_FALLBACK below) — 100% offline, no API calls,
 * no file storage involved.
 * ------------------------------------------------------------
 */

const WASTE_ITEMS = [
  { id: "plastic_bottle", name: "Plastic Bottle", category: "Plastic", icon: "🍾", color: "#2ECC71" },
  { id: "glass_bottle",   name: "Glass Bottle",   category: "Glass",   icon: "🍶", color: "#4DD0E1" },
  { id: "newspaper",      name: "Newspaper",      category: "Paper",   icon: "📰", color: "#FFD700" },
  { id: "cardboard",      name: "Cardboard",      category: "Paper",   icon: "📦", color: "#D2A679" },
  { id: "banana_peel",    name: "Banana Peel",    category: "Organic", icon: "🍌", color: "#FFE066" },
  { id: "apple_core",     name: "Apple Core",     category: "Organic", icon: "🍎", color: "#FF6B6B" },
  { id: "metal_can",      name: "Metal Can",      category: "Metal",   icon: "🥫", color: "#B0BEC5" },
  { id: "battery",        name: "Battery",        category: "Hazardous", icon: "🔋", color: "#FF0099" },
  { id: "ewaste",         name: "E-Waste",        category: "Electronic", icon: "💻", color: "#BF5FFF" },
  { id: "food_waste",     name: "Food Waste",     category: "Organic", icon: "🍛", color: "#39FF14" },
];

// Curated local knowledge base — this IS the data source (not a fallback
// for anything). No external API is called for this module.
const WASTE_FALLBACK = {
  plastic_bottle: { wasteType: "Plastic Waste (PET)", biodegradable: false, recyclingMethod: "Rinse and place in the dry/recyclable bin — PET bottles are melted down and re-spun into fibre for clothing or new bottles.", environmentalImpact: "Takes 400+ years to break down and can fragment into microplastics that harm marine life.", disposalTips: "Crush to save space, remove the cap (recycled separately), and always use the dry-waste bin." },
  glass_bottle:   { wasteType: "Glass Waste", biodegradable: false, recyclingMethod: "Glass is 100% and endlessly recyclable — rinse and take to a glass recycling point or dry-waste bin.", environmentalImpact: "Doesn't biodegrade but is inert and non-toxic; recycling it saves significant energy versus making new glass.", disposalTips: "Don't mix broken glass with paper waste; wrap sharp pieces before disposal." },
  newspaper:      { wasteType: "Paper Waste", biodegradable: true, recyclingMethod: "Bundle and recycle with dry waste — paper fibres can be reprocessed 5-7 times into new paper products.", environmentalImpact: "Biodegrades naturally, but recycling still saves trees, water, and energy compared to making new paper.", disposalTips: "Keep dry and separate from wet waste; great for composting in small amounts too." },
  cardboard:      { wasteType: "Paper/Cardboard Waste", biodegradable: true, recyclingMethod: "Flatten boxes and recycle with dry waste; clean cardboard is one of the most widely recycled materials.", environmentalImpact: "Biodegradable, but recycling reduces the need to cut down more trees for pulp.", disposalTips: "Remove tape and labels where possible, and keep it dry before disposal." },
  banana_peel:    { wasteType: "Organic (Wet) Waste", biodegradable: true, recyclingMethod: "Perfect for home composting — breaks down into nutrient-rich compost in a few weeks.", environmentalImpact: "If sent to a landfill instead of composted, it produces methane, a potent greenhouse gas.", disposalTips: "Add to a compost bin or wet-waste bin; never mix with recyclables." },
  apple_core:     { wasteType: "Organic (Wet) Waste", biodegradable: true, recyclingMethod: "Compostable — can be turned into fertiliser via home or community composting.", environmentalImpact: "Decomposes naturally, but in landfills contributes to methane emissions.", disposalTips: "Put it in the wet/organic waste bin, or start a small compost pit at home." },
  metal_can:      { wasteType: "Metal Waste", biodegradable: false, recyclingMethod: "Rinse and recycle — aluminium and steel cans can be recycled indefinitely without losing quality.", environmentalImpact: "Doesn't biodegrade, but recycling metal uses up to 95% less energy than mining new ore.", disposalTips: "Rinse out food residue and place in the dry/recyclable bin; crush to save space." },
  battery:        { wasteType: "Hazardous Waste", biodegradable: false, recyclingMethod: "Never put in regular trash — take to a designated e-waste/battery collection point for safe processing.", environmentalImpact: "Contains heavy metals (lead, cadmium, mercury) that can leach into soil and water, causing serious pollution.", disposalTips: "Store used batteries in a small container at home and drop them at a collection centre periodically." },
  ewaste:         { wasteType: "Electronic Waste", biodegradable: false, recyclingMethod: "Take to a certified e-waste recycler who can safely recover metals and dispose of toxic components.", environmentalImpact: "Contains lead, mercury, and other toxins; improper disposal contaminates soil and groundwater.", disposalTips: "Never bin electronics with household trash; look for e-waste drives or authorised collection centres." },
  food_waste:     { wasteType: "Organic (Wet) Waste", biodegradable: true, recyclingMethod: "Compost at home or use a community composting/biogas program where available.", environmentalImpact: "One of the largest contributors to landfill methane emissions worldwide.", disposalTips: "Separate wet waste daily; consider a small kitchen compost bin to reduce what goes to landfill." },
};

let _wasteModalId = null;

function renderWasteGrid() {
  const grid = document.getElementById("wasteid-grid");
  if (!grid) return;
  grid.innerHTML = WASTE_ITEMS.map((item) => `
    <div class="waste-card" data-id="${item.id}" onclick="openWasteModal('${item.id}')" style="--waste-color:${item.color}">
      <div class="waste-card-icon">${item.icon}</div>
      <div class="waste-card-name">${item.name}</div>
      <div class="waste-card-cat">${item.category}</div>
      ${state.wasteIdsDone && state.wasteIdsDone[item.id] ? '<div class="waste-card-done">✅ Identified</div>' : ""}
    </div>`).join("");
}

function openWasteModal(id) {
  const item = WASTE_ITEMS.find((w) => w.id === id);
  if (!item) return;
  _wasteModalId = id;

  document.getElementById("wm-icon").textContent = item.icon;
  document.getElementById("wm-icon").style.background = item.color + "22";
  document.getElementById("wm-title").textContent = item.name;
  document.getElementById("wm-body").innerHTML = `<div class="wm-loading">📘 Looking up this item…</div>`;
  document.getElementById("waste-modal-backdrop").style.display = "flex";

  runWasteAnalysis(item);
}

function runWasteAnalysis(item) {
  const data = WASTE_FALLBACK[item.id];
  if (_wasteModalId !== item.id) return; // modal was closed/changed in the meantime

  renderWasteResult(item, data);
  awardWasteBadge(item);
  logWasteActivity(item, data);
}

function renderWasteResult(item, data) {
  const bio = !!data.biodegradable;
  document.getElementById("wm-body").innerHTML = `
    <div class="wm-source">📘 Local Environmental Knowledge Base</div>
    <div class="wm-row"><span class="wm-label">Waste Type</span><span class="wm-value">${data.wasteType || item.category}</span></div>
    <div class="wm-row"><span class="wm-label">Category</span><span class="wm-badge ${bio ? "bio" : "nonbio"}">${bio ? "🌿 Biodegradable" : "🚫 Non-biodegradable"}</span></div>
    <div class="wm-section"><div class="wm-section-title">♻️ Recycling Method</div><div>${data.recyclingMethod || "—"}</div></div>
    <div class="wm-section"><div class="wm-section-title">🌍 Environmental Impact</div><div>${data.environmentalImpact || "—"}</div></div>
    <div class="wm-section"><div class="wm-section-title">🗑️ Disposal Tips</div><div>${data.disposalTips || "—"}</div></div>
  `;
}

function awardWasteBadge(item) {
  state.wasteIdsDone = state.wasteIdsDone || {};
  if (state.wasteIdsDone[item.id]) return; // already earned XP for this one
  state.wasteIdsDone[item.id] = true;
  state.xp = (state.xp || 0) + 15;
  if (typeof saveProgress === "function") saveProgress();
  if (typeof updateUI === "function") updateUI();
  if (typeof toast === "function") toast("Waste identified! +15 XP ♻️");
  renderWasteGrid();
  renderWasteBadgeProgress();
}

function renderWasteBadgeProgress() {
  const el = document.getElementById("waste-progress-label");
  if (!el) return;
  const done = state.wasteIdsDone ? Object.keys(state.wasteIdsDone).length : 0;
  el.textContent = `${done}/${WASTE_ITEMS.length} waste items identified`;
  if (done === WASTE_ITEMS.length) {
    const badgeEl = document.getElementById("waste-full-badge");
    if (badgeEl) badgeEl.style.display = "inline-flex";
  }
}

async function logWasteActivity(item, data) {
  // Wait for the Firestore bridge instead of silently dropping the log if
  // the module script (window.EcoClient) hasn't finished loading yet — this
  // is a real possibility since a student can tap a waste card within a
  // second of the page loading, well before a slow CDN fetch resolves.
  const client = window.EcoClient || (window.EcoReady && await window.EcoReady);
  if (!client || !client.logWasteIdentification) return;
  client.logWasteIdentification({
    studentName: state.name,
    studentClass: state.cls || "",
    itemName: item.name,
    wasteType: data.wasteType || item.category,
    biodegradable: !!data.biodegradable,
  }).catch((e) => console.warn("Could not log waste activity to Firestore:", e));
}

function closeWasteModal() {
  _wasteModalId = null;
  document.getElementById("waste-modal-backdrop").style.display = "none";
}

window.openWasteModal = openWasteModal;
window.closeWasteModal = closeWasteModal;
window.renderWasteGrid = renderWasteGrid;

// Re-render the grid whenever the Waste ID view is shown.
const _origShowViewForWaste = window.showView;
window.showView = function (v) {
  _origShowViewForWaste(v);
  if (v === "wasteid") {
    renderWasteGrid();
    renderWasteBadgeProgress();
  }
};

window.addEventListener("DOMContentLoaded", () => {
  if (document.getElementById("wasteid-grid")) {
    renderWasteGrid();
    renderWasteBadgeProgress();
  }
});
