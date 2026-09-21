// ================= STATE MANAGEMENT =================
const state = {
  config: {},
  preset: {},
  photos: [],
  currentCategory: "all",
  isProcessing: false,
  activeInspectorPhoto: null,
  inspectorSession: {
    filename: null,
    seq: 0,
    abortController: null,
  },
};

// ================= AIRBNB DLS TOAST NOTIFICATIONS =================
function showToast(message, type = "success") {
  let container = document.getElementById("toastContainer");
  if (!container) {
    container = document.createElement("div");
    container.id = "toastContainer";
    container.className = "fixed top-6 left-1/2 -translate-x-1/2 z-[9999] flex flex-col items-center gap-2.5 pointer-events-none w-full max-w-md px-4";
    document.body.appendChild(container);
  }

  const toast = document.createElement("div");
  toast.className = "flex items-center gap-2.5 bg-white border border-[#DDDDDD] px-5 py-2.5 rounded-full shadow-airbnb-modal transition-all duration-300 transform -translate-y-2 opacity-0 pointer-events-auto select-none";

  let iconHtml = "";
  if (type === "success") {
    iconHtml = `<div class="w-5 h-5 rounded-full bg-emerald-500 text-white flex items-center justify-center shrink-0"><i data-lucide="check" class="w-3 h-3 stroke-[3]"></i></div>`;
  } else if (type === "warning") {
    iconHtml = `<div class="w-5 h-5 rounded-full bg-amber-500 text-white flex items-center justify-center shrink-0"><i data-lucide="alert-triangle" class="w-3 h-3 stroke-[3]"></i></div>`;
  } else if (type === "error") {
    iconHtml = `<div class="w-5 h-5 rounded-full bg-[#FF385C] text-white flex items-center justify-center shrink-0"><i data-lucide="alert-circle" class="w-3 h-3 stroke-[3]"></i></div>`;
  } else {
    iconHtml = `<div class="w-5 h-5 rounded-full bg-[#222222] text-white flex items-center justify-center shrink-0"><i data-lucide="info" class="w-3 h-3 stroke-[3]"></i></div>`;
  }

  toast.innerHTML = `
    ${iconHtml}
    <span class="text-xs font-semibold text-[#222222] whitespace-nowrap">${message}</span>
  `;

  container.appendChild(toast);
  if (window.lucide) lucide.createIcons();

  // Trigger smooth enter animation
  requestAnimationFrame(() => {
    toast.classList.remove("-translate-y-2", "opacity-0");
    toast.classList.add("translate-y-0", "opacity-100");
  });

  // Auto dismiss after 3.2s
  setTimeout(() => {
    toast.classList.remove("translate-y-0", "opacity-100");
    toast.classList.add("-translate-y-2", "opacity-0");
    setTimeout(() => toast.remove(), 250);
  }, 3200);
}

// Override native window.alert with Airbnb toast
window.alert = function(msg) {
  showToast(msg, "info");
};
window.showToast = showToast;

// ================= INITIALIZATION =================
document.addEventListener("DOMContentLoaded", () => {
  if (window.lucide) lucide.createIcons();
  initEventListeners();
  loadConfig();
  loadPresets();
  loadPhotos();
});

function initEventListeners() {
  // Settings Drawer Toggle
  document.getElementById("btnSettingsToggle")?.addEventListener("click", toggleSettingsDrawer);
  document.getElementById("btnCloseSettings")?.addEventListener("click", toggleSettingsDrawer);

  // Save Settings
  document.getElementById("btnSaveConfig")?.addEventListener("click", saveConfig);

  // Refresh
  document.getElementById("btnRefresh")?.addEventListener("click", () => {
    loadPhotos();
    loadPresets();
  });

  // Start Pipeline
  document.getElementById("btnStartPipeline")?.addEventListener("click", (e) => {
    e.stopPropagation();
    startPipeline();
  });

  // Inspector Modal controls that don't use inline onclick
  document.getElementById("btnApplyPreview")?.addEventListener("click", updatePreview);
  document.getElementById("btnResetSliders")?.addEventListener("click", () => resetSliders(true));

  // Slider Input Values
  initSliderValueTrackers();

  // Custom Dropdowns (Model, Resolution, Quality)
  initCustomDropdowns();

  // Split Comparison Dragging in Modal
  initSplitSlider();
}

function initCustomDropdowns() {
  // Helper to bind toggle & outside click for any custom dropdown
  function bindDropdown(triggerId, menuId, chevronId) {
    const trigger = document.getElementById(triggerId);
    const menu = document.getElementById(menuId);
    const chevron = document.getElementById(chevronId);
    if (!trigger || !menu) return;

    trigger.addEventListener("click", (e) => {
      e.stopPropagation();
      const isHidden = menu.classList.contains("hidden");
      // Close any other open dropdown menus first
      document.querySelectorAll("#customModelMenu, #customResMenu, #customQualityMenu").forEach(m => {
        if (m !== menu) m.classList.add("hidden");
      });
      document.querySelectorAll("#customModelChevron, #customResChevron, #customQualityChevron").forEach(c => {
        if (c !== chevron) c.style.transform = "rotate(0deg)";
      });

      menu.classList.toggle("hidden");
      if (chevron) {
        chevron.style.transform = isHidden ? "rotate(180deg)" : "rotate(0deg)";
      }
    });

    document.addEventListener("click", (e) => {
      if (!menu.contains(e.target) && !trigger.contains(e.target)) {
        menu.classList.add("hidden");
        if (chevron) chevron.style.transform = "rotate(0deg)";
      }
    });
  }

  bindDropdown("btnCustomModelTrigger", "customModelMenu", "customModelChevron");
  bindDropdown("btnCustomResolutionTrigger", "customResMenu", "customResChevron");
  bindDropdown("btnCustomQualityTrigger", "customQualityMenu", "customQualityChevron");
}

window.selectVisionModel = function(value, name, desc) {
  const input = document.getElementById("inputModel");
  const nameEl = document.getElementById("customModelSelectedName");
  const descEl = document.getElementById("customModelSelectedDesc");
  const menu = document.getElementById("customModelMenu");
  const chevron = document.getElementById("customModelChevron");

  if (input) input.value = value;
  if (nameEl) nameEl.textContent = name;
  if (descEl) descEl.textContent = desc;
  if (menu) menu.classList.add("hidden");
  if (chevron) chevron.style.transform = "rotate(0deg)";

  // Update checkmarks
  document.querySelectorAll(".model-option").forEach((opt) => {
    const isMatch = opt.getAttribute("data-value") === value;
    const check = opt.querySelector(".model-check");
    if (check) {
      if (isMatch) check.classList.remove("hidden");
      else check.classList.add("hidden");
    }
  });
};

window.selectResolution = function(value, name, desc) {
  const input = document.getElementById("selectTargetWidth");
  const nameEl = document.getElementById("customResSelectedName");
  const descEl = document.getElementById("customResSelectedDesc");
  const menu = document.getElementById("customResMenu");
  const chevron = document.getElementById("customResChevron");

  if (input) input.value = value;
  if (nameEl) nameEl.textContent = name;
  if (descEl) descEl.textContent = desc;
  if (menu) menu.classList.add("hidden");
  if (chevron) chevron.style.transform = "rotate(0deg)";

  // Update checkmarks
  document.querySelectorAll(".res-option").forEach((opt) => {
    const isMatch = opt.getAttribute("data-value") === String(value);
    const check = opt.querySelector(".res-check");
    if (check) {
      if (isMatch) check.classList.remove("hidden");
      else check.classList.add("hidden");
    }
  });
};

window.selectQuality = function(value, name, desc) {
  const input = document.getElementById("selectJpegQuality");
  const nameEl = document.getElementById("customQualitySelectedName");
  const descEl = document.getElementById("customQualitySelectedDesc");
  const menu = document.getElementById("customQualityMenu");
  const chevron = document.getElementById("customQualityChevron");

  if (input) input.value = value;
  if (nameEl) nameEl.textContent = name;
  if (descEl) descEl.textContent = desc;
  if (menu) menu.classList.add("hidden");
  if (chevron) chevron.style.transform = "rotate(0deg)";

  // Update checkmarks
  document.querySelectorAll(".quality-option").forEach((opt) => {
    const isMatch = opt.getAttribute("data-value") === String(value);
    const check = opt.querySelector(".quality-check");
    if (check) {
      if (isMatch) check.classList.remove("hidden");
      else check.classList.add("hidden");
    }
  });
};

// Global Drawer & Modal Helpers
window.toggleSettingsDrawer = function() {
  const drawer = document.getElementById("settingsDrawer");
  if (drawer) {
    drawer.classList.toggle("hidden");
    if (!drawer.classList.contains("hidden")) {
      drawer.scrollIntoView({ behavior: "smooth" });
    }
  }
};

let howItWorksClosing = false;
window.openHowItWorks = function() {
  const modal = document.getElementById("howItWorksModal");
  const backdrop = document.getElementById("howItWorksBackdrop");
  const card = document.getElementById("howItWorksCard");
  if (!modal || !backdrop || !card) return;

  howItWorksClosing = false;
  modal.classList.remove("hidden");
  
  // Force browser layout reflow before triggering transition
  void modal.offsetHeight;

  requestAnimationFrame(() => {
    backdrop.classList.remove("opacity-0");
    backdrop.classList.add("opacity-100");

    card.classList.remove("opacity-0", "translate-y-8", "scale-[0.96]");
    card.classList.add("opacity-100", "translate-y-0", "scale-100");
  });

  if (window.lucide) lucide.createIcons();
};

window.closeHowItWorks = function() {
  if (howItWorksClosing) return;
  const modal = document.getElementById("howItWorksModal");
  const backdrop = document.getElementById("howItWorksBackdrop");
  const card = document.getElementById("howItWorksCard");
  if (!modal || !backdrop || !card) return;

  howItWorksClosing = true;
  backdrop.classList.remove("opacity-100");
  backdrop.classList.add("opacity-0");

  card.classList.remove("opacity-100", "translate-y-0", "scale-100");
  card.classList.add("opacity-0", "translate-y-6", "scale-[0.96]");

  setTimeout(() => {
    if (howItWorksClosing) {
      modal.classList.add("hidden");
      howItWorksClosing = false;
    }
  }, 500);
};

// Close modal on Escape key press
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    const modal = document.getElementById("howItWorksModal");
    if (modal && !modal.classList.contains("hidden")) {
      window.closeHowItWorks();
    }
  }
});

// Native Folder / File Picker Dialogs
window.browseFolder = async function(inputId) {
  const input = document.getElementById(inputId);
  const currentVal = input ? input.value.trim() : "C:/";
  try {
    const res = await fetch("/api/browse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type: "folder", initial_dir: currentVal })
    });
    const data = await res.json();
    if (data.status === "ok" && data.path) {
      if (input) input.value = data.path;
      showToast(`Selected folder!`, "info");
    }
  } catch (err) {
    console.error("Browse folder error:", err);
  }
};

// Preset Card State Manager (Airbnb-style UI)
function setPresetCardState(stateName, errorMsg = "") {
  const initialEl = document.getElementById("presetStateInitial");
  const loadingEl = document.getElementById("presetStateLoading");
  const successEl = document.getElementById("presetStateSuccess");
  const errorEl = document.getElementById("presetStateError");
  const errorMsgEl = document.getElementById("presetErrorMessage");

  if (!initialEl || !loadingEl || !successEl || !errorEl) return;

  initialEl.classList.add("hidden");
  loadingEl.classList.add("hidden");
  successEl.classList.add("hidden");
  errorEl.classList.add("hidden");

  if (stateName === "loading") {
    loadingEl.classList.remove("hidden");
  } else if (stateName === "success") {
    successEl.classList.remove("hidden");
  } else if (stateName === "error") {
    errorEl.classList.remove("hidden");
    if (errorMsgEl) {
      errorMsgEl.textContent = errorMsg || "The selected file could not be processed. Please choose a valid processed HALD image.";
    }
  } else {
    initialEl.classList.remove("hidden");
  }

  if (window.lucide) lucide.createIcons();
}

window.setPresetCardState = setPresetCardState;

window.browseFile = async function(inputId) {
  const input = document.getElementById(inputId);
  const currentVal = input ? input.value.trim() : "C:/";
  try {
    const res = await fetch("/api/browse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type: "file", initial_dir: currentVal })
    });
    const data = await res.json();
    if (data.status === "ok" && data.path) {
      if (input) input.value = data.path;
      const lower = data.path.toLowerCase();
      if (lower.endsWith(".png") || lower.endsWith(".jpg") || lower.endsWith(".jpeg") || lower.endsWith(".tif") || lower.endsWith(".tiff")) {
        setPresetCardState("loading");
        try {
          const installRes = await fetch("/api/presets/install-master", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ hald_path: data.path, preset_name: "Master Studio Preset" })
          });
          const installData = await installRes.json();
          if (installRes.ok && installData.installed) {
            setPresetCardState("success");
            showToast("Custom preset successfully installed as the active Studio Master Preset.", "success");
            loadPresets();
            loadConfig();
            return;
          } else {
            setPresetCardState("error", "The selected file could not be processed. Please choose a valid processed HALD image.");
            showToast("Preset could not be applied.", "error");
          }
        } catch (installErr) {
          console.error("Install master error:", installErr);
          setPresetCardState("error", "The selected file could not be processed. Please choose a valid processed HALD image.");
          showToast("Preset could not be applied.", "error");
        }
      } else {
        showToast("Selected preset file!", "info");
        setPresetCardState("success");
        loadPresets();
      }
    }
  } catch (err) {
    console.error("Browse file error:", err);
    setPresetCardState("error", "The selected file could not be processed. Please choose a valid processed HALD image.");
  }
};

// ================= API CALLS =================

function updateTopAiStatus() {
  const navAiDot = document.getElementById("navAiDot");
  const navAiModel = document.getElementById("navAiModel");
  if (!navAiDot || !navAiModel) return;

  const cfg = state.config || {};
  const hasApiKey = !!(cfg.ORCA_API_KEY && cfg.ORCA_API_KEY.trim());
  const isEnabled = cfg.ENABLE_AUTO_BALANCING !== false;

  if (!hasApiKey || !isEnabled) {
    // State B: API NOT CONFIGURED / DISABLED
    navAiDot.className = "w-2 h-2 rounded-full bg-rose-500";
    navAiModel.className = "text-xs text-[#717171] font-medium truncate max-w-[160px]";
    navAiModel.textContent = "AI Offline";
    return;
  }

  // Check recent telemetry across loaded photos for quota/credit limits or errors
  const photos = state.photos || [];
  const hasUnavailableCredits = photos.some((p) => {
    const adj = p.adjust_telemetry || {};
    const crop = p.crop_telemetry || {};
    return adj.ai_status === "ai_unavailable" || crop.crop_status === "ai_unavailable";
  });

  const hasFailedError = photos.some((p) => {
    const adj = p.adjust_telemetry || {};
    const crop = p.crop_telemetry || {};
    return adj.ai_status === "ai_failed" || crop.crop_status === "ai_failed";
  });

  if (hasUnavailableCredits) {
    // State C: API CREDIT / QUOTA / RATE LIMIT
    navAiDot.className = "w-2 h-2 rounded-full bg-amber-500";
    navAiModel.className = "text-xs text-amber-700 font-medium truncate max-w-[160px]";
    navAiModel.textContent = "AI Limited";
  } else if (hasFailedError) {
    // State D: UNEXPECTED API ERROR
    navAiDot.className = "w-2 h-2 rounded-full bg-rose-500";
    navAiModel.className = "text-xs text-rose-600 font-medium truncate max-w-[160px]";
    navAiModel.textContent = "AI Error";
  } else {
    // State A: API READY / AVAILABLE
    navAiDot.className = "w-2 h-2 rounded-full bg-emerald-500 animate-pulse";
    navAiModel.className = "text-xs text-[#717171] font-medium truncate max-w-[160px]";
    navAiModel.textContent = "AI Active";
  }
}

async function loadConfig() {
  try {
    const res = await fetch("/api/config");
    const data = await res.json();
    state.config = data;

    // Update Top Navigation Capsule AI Status
    updateTopAiStatus();
    
    // Update Settings Inputs
    if (data.ORCA_API_KEY) document.getElementById("inputApiKey").value = data.ORCA_API_KEY;
    if (data.ORCA_MODEL) {
      const modelVal = data.ORCA_MODEL;
      const modelNames = {
        "qwen/qwen3.8-27b": "Production • Qwen 27B Vision",
        "llama-3.2-90b-vision-preview": "Llama 3.2 90B Vision",
        "llama-3.2-11b-vision-preview": "Fast Lightweight Vision",
        "openai/gpt-4o": "OpenAI GPT-4o Flagship",
        "anthropic/claude-3-5-sonnet": "Anthropic Claude 3.5 Sonnet"
      };
      selectVisionModel(modelVal, modelVal, modelNames[modelVal] || "Custom Vision Model");
    }
    if (data.INPUT_FOLDER) document.getElementById("inputFolderInput").value = data.INPUT_FOLDER;
    if (data.OUTPUT_FOLDER) document.getElementById("inputFolderOutput").value = data.OUTPUT_FOLDER;
    if (data.PRESET_FOLDER) {
      const pInput = document.getElementById("inputFolderPresets");
      if (pInput) pInput.value = data.PRESET_FOLDER;
    }

    // AI Crop & Auto Balancing Toggles
    if (document.getElementById("toggleAiCrop")) {
      document.getElementById("toggleAiCrop").checked = data.ENABLE_AI_SMART_CROP !== false;
    }
    if (document.getElementById("toggleAutoBalancing")) {
      document.getElementById("toggleAutoBalancing").checked = data.ENABLE_AUTO_BALANCING !== false;
    }

    // Export Resolution & Quality Airbnb Dropdowns
    const resMap = {
      "0": { name: "Original (100% Full Res)", desc: "Full Camera Resolution" },
      "3840": { name: "4K Ultra HD (3840px)", desc: "Ultra High-Res Screen Master" },
      "2560": { name: "2K QHD (2560px)", desc: "Crisp 2K Display Ready" },
      "1920": { name: "Full HD (1920px)", desc: "Standard 1080p Web Export" }
    };
    const targetW = String(data.TARGET_MAX_WIDTH !== undefined ? data.TARGET_MAX_WIDTH : "0");
    const resInfo = resMap[targetW] || { name: `Custom (${targetW}px)`, desc: "Custom Target Resolution" };
    selectResolution(targetW, resInfo.name, resInfo.desc);

    const qualityMap = {
      "100": { name: "100% Studio Max", desc: "Lossless Quality • Full MB" },
      "98": { name: "98% High Quality", desc: "Near-Lossless High Detail" },
      "95": { name: "95% Balanced", desc: "Standard Web Compression" }
    };
    const qualityVal = String(data.JPEG_QUALITY !== undefined ? data.JPEG_QUALITY : "100");
    const qualInfo = qualityMap[qualityVal] || { name: `${qualityVal}% Quality`, desc: "Custom Export Quality" };
    selectQuality(qualityVal, qualInfo.name, qualInfo.desc);
  } catch (err) {
    console.error("Failed to load config:", err);
  }
}

async function saveConfig() {
  const targetWidthEl = document.getElementById("selectTargetWidth");
  const jpegQualityEl = document.getElementById("selectJpegQuality");
  const presetFolderEl = document.getElementById("inputFolderPresets");

  const payload = {
    ORCA_API_KEY: document.getElementById("inputApiKey").value.trim(),
    ORCA_MODEL: document.getElementById("inputModel").value.trim(),
    INPUT_FOLDER: document.getElementById("inputFolderInput").value.trim(),
    OUTPUT_FOLDER: document.getElementById("inputFolderOutput").value.trim(),
    PRESET_FOLDER: presetFolderEl ? presetFolderEl.value.trim() : "calibration",
    ENABLE_AI_SMART_CROP: document.getElementById("toggleAiCrop") ? document.getElementById("toggleAiCrop").checked : true,
    ENABLE_AUTO_BALANCING: document.getElementById("toggleAutoBalancing") ? document.getElementById("toggleAutoBalancing").checked : true,
    TARGET_MAX_WIDTH: targetWidthEl ? parseInt(targetWidthEl.value, 10) : 0,
    JPEG_QUALITY: jpegQualityEl ? parseInt(jpegQualityEl.value, 10) : 100,
  };

  try {
    const res = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      showToast("Settings saved!", "success");
      document.getElementById("settingsDrawer").classList.add("hidden");
      loadConfig();
      loadPresets();
      loadPhotos();
    }
  } catch (err) {
    showToast("Error saving settings!", "error");
  }
}

async function loadPresets() {
  try {
    const res = await fetch("/api/presets");
    const data = await res.json();
    state.preset = data;

    if (document.getElementById("navPresetName")) {
      document.getElementById("navPresetName").textContent = data.active_preset || "Master Preset";
    }
    if (document.getElementById("activePresetBadge")) {
      document.getElementById("activePresetBadge").textContent = data.active_preset || "Master Studio Preset";
    }
    if (document.getElementById("activePresetSummary")) {
      document.getElementById("activePresetSummary").textContent = data.summary || "Calibrated Studio Preset Active";
    }

    if (data.active_preset) {
      setPresetCardState("success");
    } else {
      setPresetCardState("initial");
    }

    // Diagnostics telemetry
    const diag = data.diagnostics || {};
    const badgeLut = document.getElementById("badgeLutStatus");
    const badgeSpatial = document.getElementById("badgeSpatialStatus");
    if (badgeLut) {
      badgeLut.textContent = diag.lut_size ? `✓ ${diag.lut_size}³ Float32` : `✓ 64³ Float32`;
    }
    if (badgeSpatial) {
      badgeSpatial.textContent = diag.spatial_active ? `✓ Spatial Engine Active` : `Standard Tone`;
    }
    if (window.lucide) lucide.createIcons();
  } catch (err) {
    console.error("Failed to load presets:", err);
  }
}

async function loadPhotos() {
  try {
    const res = await fetch("/api/photos/incoming");
    const data = await res.json();
    const timestamp = Date.now();
    state.photos = (data.photos || []).map((p) => ({
      ...p,
      cacheBuster: timestamp,
    }));

    const total = data.total || 0;
    const processed = data.processed_count || 0;
    const queued = total - processed;

    // Update Capsule & Category Counts
    if (document.getElementById("navPhotoCount")) {
      document.getElementById("navPhotoCount").textContent = `${total} Photo${total === 1 ? '' : 's'}`;
    }
    if (document.getElementById("catTotal")) document.getElementById("catTotal").textContent = total;
    if (document.getElementById("catReady")) document.getElementById("catReady").textContent = processed;
    if (document.getElementById("catQueue")) document.getElementById("catQueue").textContent = queued;

    updateTopAiStatus();
    renderGallery();
  } catch (err) {
    console.error("Failed to load photos:", err);
  }
}

// ================= AIRBNB DLS GALLERY RENDERING =================

function renderGallery() {
  const grid = document.getElementById("galleryGrid");
  if (!grid) return;
  grid.innerHTML = "";

  const displayPhotos = state.photos || [];

  if (displayPhotos.length === 0) {
    grid.innerHTML = `
      <div class="col-span-full py-20 text-center bg-[#F7F7F7] rounded-3xl border border-[#DDDDDD] shadow-airbnb-card">
        <div class="w-16 h-16 rounded-full bg-white border border-[#EBEBEB] text-[#717171] flex items-center justify-center mx-auto mb-4 shadow-sm">
          <i data-lucide="image-off" class="w-7 h-7"></i>
        </div>
        <h3 class="text-base font-bold text-[#222222]">No photos found</h3>
        <p class="text-xs text-[#717171] mt-1 max-w-md mx-auto">
          Place your photos in <span class="font-mono text-[#222222] font-semibold">${state.config.INPUT_FOLDER || 'D:/Media_Incoming'}</span> and click Refresh.
        </p>
        <button onclick="loadPhotos()" class="mt-5 px-6 py-2.5 rounded-full bg-[#222222] hover:bg-black text-white text-xs font-bold transition-all shadow-sm">
          Refresh Incoming Folder
        </button>
      </div>
    `;
    if (window.lucide) lucide.createIcons();
    return;
  }

  displayPhotos.forEach((photo, idx) => {
    grid.appendChild(createAirbnbPhotoCard(photo, idx));
  });

  if (window.lucide) lucide.createIcons();
}

function createAirbnbPhotoCard(photo, index) {
  const div = document.createElement("div");
  div.id = `card-${index}`;
  div.className = "flex flex-col select-none bg-white rounded-3xl p-5 border border-[#EBEBEB] hover:border-[#DDDDDD] hover:shadow-airbnb-card transition-all duration-300 space-y-4";

  const isProcessed = photo.is_processed;
  const isRunning = state.isProcessing && !isProcessed;
  const outUrlWithBuster = photo.output_url ? `${photo.output_url}?t=${photo.cacheBuster || Date.now()}` : "";

  // Determine active configuration flags and telemetry
  const isCropSetting = state.config.ENABLE_AI_SMART_CROP !== false;
  const isBalanceSetting = state.config.ENABLE_AUTO_BALANCING !== false;

  const adjTel = photo.adjust_telemetry || {};
  const cropTel = photo.crop_telemetry || {};

  const aiStatus = adjTel.ai_status || (isProcessed ? (isBalanceSetting ? "ai_analyzed" : "ai_disabled") : "idle");
  const cropStatus = cropTel.crop_status || (isProcessed ? (isCropSetting ? "ai_crop" : "crop_disabled") : "idle");

  // Build Feature Badges (Compact Airbnb Pill Badges)
  let presetBadge = "";
  let adjustBadge = "";
  let cropBadge = "";

  if (isProcessed) {
    presetBadge = `<span class="px-3 py-1 rounded-full text-xs font-semibold bg-[#F7F7F7] text-[#222222] border border-[#EBEBEB] flex items-center gap-1.5" title="Stage 1 Preset Applied"><i data-lucide="check" class="w-3.5 h-3.5 text-emerald-600 stroke-[2.5]"></i><span>Preset</span></span>`;

    if (!isBalanceSetting || aiStatus === "ai_disabled") {
      adjustBadge = `<span class="px-3 py-1 rounded-full text-xs font-semibold bg-[#F7F7F7] text-[#717171] border border-[#EBEBEB]" title="Stage 2 AI Auto-Balance disabled">Auto-Balance: OFF</span>`;
    } else if (aiStatus === "ai_analyzed") {
      adjustBadge = `<span class="px-3 py-1 rounded-full text-xs font-semibold bg-[#F7F7F7] text-[#222222] border border-[#EBEBEB] flex items-center gap-1.5" title="${adjTel.reason || 'AI Auto-Balance Applied'}"><i data-lucide="sparkles" class="w-3.5 h-3.5 text-amber-500 fill-amber-500"></i><span>AI Auto-Balance</span></span>`;
    } else if (aiStatus === "ai_no_correction") {
      adjustBadge = `<span class="px-3 py-1 rounded-full text-xs font-semibold bg-[#F7F7F7] text-[#222222] border border-[#EBEBEB] flex items-center gap-1.5" title="${adjTel.reason || 'Optimal lighting — Preset preserved'}"><span>AI Balance: Optimal</span></span>`;
    } else if (aiStatus === "ai_unavailable" || aiStatus === "ai_failed") {
      adjustBadge = `<span class="px-3 py-1 rounded-full text-xs font-semibold bg-[#F7F7F7] text-[#717171] border border-[#EBEBEB] flex items-center gap-1.5" title="AI unavailable — Preset preserved"><span>AI Balance unavailable</span></span>`;
    }

    if (!isCropSetting || cropStatus === "crop_disabled") {
      cropBadge = `<span class="px-3 py-1 rounded-full text-xs font-semibold bg-[#F7F7F7] text-[#717171] border border-[#EBEBEB]" title="Full frame preserved">Crop: Full Frame</span>`;
    } else if (cropStatus === "ai_crop") {
      cropBadge = `<span class="px-3 py-1 rounded-full text-xs font-semibold bg-[#F7F7F7] text-[#222222] border border-[#EBEBEB] flex items-center gap-1.5" title="${cropTel.reason || 'AI Smart Crop Applied'}"><i data-lucide="crop" class="w-3.5 h-3.5 text-[#222222]"></i><span>AI Crop</span></span>`;
    } else if (cropStatus === "ai_unavailable" || cropStatus === "ai_rejected" || cropStatus === "ai_failed") {
      cropBadge = `<span class="px-3 py-1 rounded-full text-xs font-semibold bg-[#F7F7F7] text-[#717171] border border-[#EBEBEB] flex items-center gap-1.5" title="Crop unavailable — Full frame preserved"><span>Crop unavailable</span></span>`;
    } else if (cropStatus === "fallback_crop") {
      cropBadge = `<span class="px-3 py-1 rounded-full text-xs font-semibold bg-[#F7F7F7] text-[#222222] border border-[#EBEBEB] flex items-center gap-1.5" title="Fallback Crop"><span>Crop: Fallback</span></span>`;
    }
  }

  let processedStatusText = "3D LUT Preset Applied";
  let afterOverlayBadge = "After (3D LUT)";
  let skeletonSubtext = "100% Exact 3D Hald LUT Processing...";
  let idleSubtext = "100% Exact 3D Hald LUT Preset Only";

  if (isProcessed) {
    if (aiStatus === "ai_unavailable" || cropStatus === "ai_unavailable") {
      processedStatusText = "Stage 1 Preset Applied (AI Unavailable — Base Preserved)";
      afterOverlayBadge = "After (Preset Base)";
    } else if (aiStatus === "ai_failed" || cropStatus === "ai_failed") {
      processedStatusText = "Stage 1 Preset Applied (AI Error — Base Preserved)";
      afterOverlayBadge = "After (Preset Base)";
    } else if (aiStatus === "ai_no_correction") {
      processedStatusText = "Stage 1 Preset Applied • Optimal Lighting Preserved";
      afterOverlayBadge = "After AI (Optimal)";
    } else if (aiStatus === "ai_analyzed" && cropStatus === "ai_crop") {
      processedStatusText = "Color Graded, AI Balanced & Cropped";
      afterOverlayBadge = "After AI (Calibrated)";
    } else if (aiStatus === "ai_analyzed") {
      processedStatusText = "Color Graded & AI Balanced";
      afterOverlayBadge = "After AI (Balanced)";
    } else if (cropStatus === "ai_crop") {
      processedStatusText = "Color Graded & AI Cropped";
      afterOverlayBadge = "After AI (Cropped)";
    }
  }

  let rightContainerHtml = "";
  if (isProcessed) {
    rightContainerHtml = `
      <div class="relative aspect-[3/2] w-full rounded-2xl overflow-hidden bg-black/5 border border-rose-100 hover:border-[#FF385C]/50 cursor-pointer group shadow-xs" onclick="openInspectorByName('${photo.filename}')">
        <img src="${outUrlWithBuster}" alt="AI Graded" class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500" loading="lazy" />
        <span class="absolute bottom-3 right-3 px-3 py-1 rounded-full bg-[#FF385C] text-[10px] font-extrabold tracking-wider text-white uppercase shadow-sm">
          ${afterOverlayBadge}
        </span>
      </div>
    `;
  } else if (isRunning) {
    rightContainerHtml = `
      <div class="relative aspect-[3/2] w-full rounded-2xl overflow-hidden skeleton border border-[#DDDDDD] flex flex-col items-center justify-center p-6 text-center">
        <div class="w-10 h-10 rounded-full bg-white/90 text-[#FF385C] flex items-center justify-center shadow-xs mb-2 animate-spin">
          <i data-lucide="loader-2" class="w-5 h-5"></i>
        </div>
        <span class="text-xs font-bold text-[#222222]">AI Grading in Progress...</span>
        <span class="text-[10px] text-[#717171] mt-0.5">${skeletonSubtext}</span>
      </div>
    `;
  } else {
    rightContainerHtml = `
      <div class="relative aspect-[3/2] w-full rounded-2xl overflow-hidden bg-[#F9F9F9] border-2 border-dashed border-[#DDDDDD] flex flex-col items-center justify-center p-6 text-center">
        <div class="w-11 h-11 rounded-full bg-white border border-[#EBEBEB] text-[#717171] flex items-center justify-center shadow-xs mb-2">
          <i data-lucide="sparkles" class="w-5 h-5"></i>
        </div>
        <h5 class="text-xs font-bold text-[#222222]">Ready for AI Color Grading</h5>
        <p class="text-[10px] text-[#717171] mt-0.5">${idleSubtext}</p>
      </div>
    `;
  }

  div.innerHTML = `
    <!-- Card Header Info -->
    <div class="flex flex-wrap items-center justify-between gap-2 pb-1">
      <div class="flex items-center gap-3">
        <h4 class="text-base font-bold text-[#222222] font-mono" title="${photo.filename}">
          ${photo.filename}
        </h4>
        <span class="text-xs text-[#717171] font-medium font-mono">${photo.size_mb} MB</span>
      </div>

      <!-- Feature Badges -->
      <div class="flex flex-wrap items-center gap-1.5">
        ${isProcessed ? `${presetBadge} ${adjustBadge} ${cropBadge}` : `
          <span class="text-xs font-semibold text-[#222222] flex items-center gap-1.5 bg-[#F7F7F7] px-3 py-1 rounded-full border border-[#EBEBEB]">
            <i data-lucide="star" class="w-3.5 h-3.5 ${isRunning ? 'fill-[#FF385C] text-[#FF385C] animate-spin' : 'fill-amber-500 text-amber-500'}"></i>
            <span>${isRunning ? 'Grading...' : 'In Queue'}</span>
          </span>
        `}
      </div>
    </div>

    <!-- 2 Landscape Photos Side-by-Side (Before & After) in One Row -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4 lg:gap-6">
      
      <!-- Left: Before Photo (Always Original Landscape Photo) -->
      <div class="relative aspect-[3/2] w-full rounded-2xl overflow-hidden bg-[#F7F7F7] border border-[#EBEBEB] group shadow-xs">
        <img src="${photo.input_url}" alt="Original" class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500" loading="lazy" />
        <span class="absolute bottom-3 left-3 px-3 py-1 rounded-full bg-black/70 backdrop-blur-md text-[10px] font-extrabold tracking-wider text-white uppercase shadow-sm">
          Before (Original)
        </span>
      </div>

      <!-- Right: After Photo (Processed, Skeleton Shimmer, or Placeholder) -->
      ${rightContainerHtml}

    </div>

    <!-- Card Footer Actions & Status -->
    <div class="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-[#F0F0F0] text-xs">
      <div class="flex items-center gap-2">
        <span class="text-[#717171]">Status:</span>
        <span class="font-bold ${isProcessed ? (aiStatus === 'ai_unavailable' || aiStatus === 'ai_failed' ? 'text-amber-800' : 'text-emerald-700') : (isRunning ? 'text-[#FF385C]' : 'text-[#717171]')}">
          ${isProcessed ? processedStatusText : (isRunning ? 'AI Calibrating...' : 'Awaiting Run')}
        </span>
      </div>

      <div class="flex items-center gap-2.5">
        ${
          isProcessed
            ? `<button onclick="openInspectorByName('${photo.filename}')" class="px-4 py-2 rounded-full bg-[#F7F7F7] hover:bg-[#EBEBEB] text-[#222222] text-xs font-bold flex items-center gap-1.5 transition-colors border border-[#DDDDDD] shadow-2xs" title="Inspect & Tune Sliders">
                 <i data-lucide="sliders" class="w-3.5 h-3.5 text-[#717171]"></i> Inspect & Fine-Tune
               </button>
               <a href="${outUrlWithBuster}" download="${photo.output_filename}" class="px-4 py-2 rounded-full bg-[#FF385C] hover:bg-[#E00B41] text-white text-xs font-bold flex items-center gap-1.5 transition-colors shadow-xs" title="Download Master Photo">
                 <i data-lucide="download" class="w-3.5 h-3.5"></i> Download Master
               </a>`
            : (isRunning
                ? `<span class="text-[11px] font-bold text-[#FF385C] bg-rose-50 px-3.5 py-1.5 rounded-full border border-rose-200 animate-pulse">Processing...</span>`
                : `<span class="text-[11px] font-bold text-[#717171] bg-[#F7F7F7] px-3.5 py-1.5 rounded-full border border-[#EBEBEB]">Ready to Run</span>`
              )
        }
      </div>
    </div>
  `;

  return div;
}

function setPipelineButtonMode(mode) {
  const btn = document.getElementById("btnStartPipeline");
  if (!btn) return;

  if (mode === "stop") {
    btn.innerHTML = `<i data-lucide="square" class="w-3.5 h-3.5 fill-current"></i><span>Stop</span>`;
    btn.className = "flex items-center gap-2 px-5 py-2.5 rounded-full bg-[#222222] hover:bg-black text-white text-xs font-bold transition-transform hover:scale-105 active:scale-95 shadow-sm";
    btn.title = "Stop Batch Processing";
    btn.disabled = false;
  } else {
    btn.innerHTML = `<i data-lucide="play" class="w-3.5 h-3.5 fill-current"></i><span>Start</span>`;
    btn.className = "flex items-center gap-2 px-5 py-2.5 rounded-full bg-[#FF385C] hover:bg-[#E00B41] text-white text-xs font-bold transition-transform hover:scale-105 active:scale-95 shadow-sm";
    btn.title = "Start AI Processing";
    btn.disabled = false;
  }
  if (window.lucide) lucide.createIcons();
}

function stopPipeline() {
  if (!state.isProcessing) return;

  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }
  state.isProcessing = false;
  setPipelineButtonMode("start");

  showToast("Processing stopped!", "info");

  const progressCard = document.getElementById("progressCard");
  if (progressCard) progressCard.classList.add("hidden");

  renderGallery();
  loadPhotos();
}

async function startPipeline() {
  // If already running, clicking the button triggers Stop!
  if (state.isProcessing) {
    stopPipeline();
    return;
  }

  // Run Pre-flight Validation
  try {
    const valRes = await fetch("/api/validate");
    const valData = await valRes.json();

    if (!valData.valid) {
      if (valData.errors && valData.errors.length > 0) {
        valData.errors.forEach((err, i) => {
          setTimeout(() => {
            showToast(err, "error");
          }, i * 350);
        });
      } else {
        showToast("Validation failed. Please check folder configuration.", "error");
      }
      return;
    }

    if (valData.warnings && valData.warnings.length > 0) {
      valData.warnings.forEach((warn, i) => {
        setTimeout(() => {
          showToast(warn, "info");
        }, i * 300);
      });
    }
  } catch (err) {
    showToast("Validation check error: " + err, "error");
    return;
  }

  state.isProcessing = true;
  setPipelineButtonMode("stop");

  // Show Batch Progress Card
  const progressCard = document.getElementById("progressCard");
  const progressProcessingContent = document.getElementById("progressProcessingContent");
  const progressSuccessContent = document.getElementById("progressSuccessContent");
  const progressCardWrapper = document.getElementById("progressCardWrapper");

  if (progressCard) {
    progressCard.classList.remove("hidden");
    if (progressProcessingContent) progressProcessingContent.classList.remove("hidden");
    if (progressSuccessContent) progressSuccessContent.classList.add("hidden");
    if (progressCardWrapper) {
      progressCardWrapper.className = "bg-white rounded-3xl p-6 border border-[#FF385C]/30 shadow-airbnb-card transition-all duration-300";
    }
    progressCard.scrollIntoView({ behavior: "smooth" });
  }

  // Render Gallery keeping Original visible and showing Skeleton only on Right (After)
  renderGallery();

  // Connect to SSE Endpoint
  const eventSource = new EventSource("/api/process/stream");
  state.eventSource = eventSource;

  const batchStats = {
    total: 0,
    processed: 0,
    stage1Applied: 0,
    aiAnalyzed: 0,
    aiNoCorrection: 0,
    aiUnavailable: 0,
    aiFailed: 0,
    aiDisabled: 0,
    cropAi: 0,
    cropFullFrame: 0,
    cropDisabled: 0,
    creditNotice: null
  };

  eventSource.onmessage = (event) => {
    const data = JSON.parse(event.data);

    if (data.type === "error") {
      eventSource.close();
      state.eventSource = null;
      state.isProcessing = false;
      setPipelineButtonMode("start");
      showToast(data.message || "Processing error occurred.", "error");
      loadPhotos();
      return;
    } else if (data.type === "init") {
      batchStats.total = data.total;
      updateProgress(0, data.total, `Loaded Preset: ${data.preset}`);
    } else if (data.type === "photo_start") {
      const pct = Math.round(((data.index - 1) / data.total) * 100);
      updateProgress(pct, data.total, `Grading ${data.filename}...`, data.filename);
      highlightStep(1);
    } else if (data.type === "step_preset") {
      highlightStep(1);
      document.getElementById("progressStepText").textContent = `Applying 3D Hald LUT to ${data.filename}...`;
    } else if (data.type === "step_adjust") {
      highlightStep(2);
      document.getElementById("progressStepText").textContent = `Balancing Luminance & Preserving Mood for ${data.filename}...`;
    } else if (data.type === "step_crop") {
      highlightStep(3);
      document.getElementById("progressStepText").textContent = `Smart Landscape Golden-Ratio Crop for ${data.filename}...`;
    } else if (data.type === "photo_done") {
      highlightStep(4);
      const pct = Math.round((data.index / data.total) * 100);
      updateProgress(pct, data.total, `Finished ${data.filename} (${data.dimensions})`, data.filename);

      batchStats.processed++;
      batchStats.stage1Applied++;
      const adjTel = data.adjust_telemetry || {};
      const cropTel = data.crop_telemetry || {};

      const aiSt = adjTel.ai_status || "ai_disabled";
      if (aiSt === "ai_analyzed") batchStats.aiAnalyzed++;
      else if (aiSt === "ai_no_correction") batchStats.aiNoCorrection++;
      else if (aiSt === "ai_unavailable") {
        batchStats.aiUnavailable++;
        if (adjTel.api_error && !batchStats.creditNotice) batchStats.creditNotice = adjTel.api_error;
      } else if (aiSt === "ai_failed") {
        batchStats.aiFailed++;
      } else {
        batchStats.aiDisabled++;
      }

      const crSt = cropTel.crop_status || "crop_disabled";
      if (crSt === "ai_crop") batchStats.cropAi++;
      else if (crSt === "crop_disabled") batchStats.cropDisabled++;
      else batchStats.cropFullFrame++;

      // Update in-memory state
      const target = state.photos.find((p) => p.filename === data.filename);
      if (target) {
        target.is_processed = true;
        target.output_url = data.output_url;
        target.output_filename = data.output_filename;
        target.adjust_telemetry = data.adjust_telemetry;
        target.crop_telemetry = data.crop_telemetry;
      }
      // Re-render gallery to display completed After photo immediately
      renderGallery();
    } else if (data.type === "complete") {
      eventSource.close();
      state.eventSource = null;
      state.isProcessing = false;
      setPipelineButtonMode("start");

      // Swap progress content with clean Success State inside the box!
      if (progressProcessingContent) progressProcessingContent.classList.add("hidden");
      if (progressSuccessContent) {
        progressSuccessContent.classList.remove("hidden");
        const subtext = document.getElementById("progressSuccessSubtext");
        if (subtext) {
          const totalCount = data.total || batchStats.total || state.photos.length || 0;
          subtext.innerHTML = totalCount === 1
            ? "1 photo successfully developed with 3D HALD preset and saved to output folder."
            : `${totalCount} photos successfully developed with 3D HALD preset and saved to output folder.`;
        }
      }
      if (progressCardWrapper) {
        progressCardWrapper.className = "bg-white rounded-3xl p-6 border border-[#DDDDDD] shadow-airbnb-card transition-all duration-300";
      }
      if (window.lucide) lucide.createIcons();

      // Re-load photos and re-render gallery
      loadPhotos();

      // Trigger Airbnb Celebration
      celebrateCompletion();
    }
  };

  eventSource.onerror = (err) => {
    console.error("SSE error:", err);
    eventSource.close();
    state.eventSource = null;
    state.isProcessing = false;
    setPipelineButtonMode("start");
    showToast("Processing connection interrupted.", "error");
    loadPhotos();
  };
}

window.dismissProgressCard = function() {
  const card = document.getElementById("progressCard");
  if (card) card.classList.add("hidden");
};

function updateProgress(percent, total, text, filename = "") {
  const progressBarFill = document.getElementById("progressBarFill");
  const progressPercentBadge = document.getElementById("progressPercentBadge");
  const progressStepText = document.getElementById("progressStepText");
  const progressCurrentFilename = document.getElementById("progressCurrentFilename");

  if (progressBarFill) progressBarFill.style.width = `${percent}%`;
  if (progressPercentBadge) progressPercentBadge.textContent = `${percent}%`;
  if (progressStepText) progressStepText.textContent = text;
  if (progressCurrentFilename && filename) {
    progressCurrentFilename.textContent = `[${filename}]`;
  }
}

function highlightStep(stepNum) {
  // Connector progress width: step 1 = 0%, step 2 = 33%, step 3 = 66%, step 4 = 100%
  const progressPct = Math.round(((stepNum - 1) / 3) * 100);
  const connector = document.getElementById("stepConnectorProgress");
  if (connector) connector.style.width = `${progressPct}%`;

  for (let i = 1; i <= 4; i++) {
    const node = document.getElementById(`stepNode${i}`);
    if (!node) continue;
    const circle = node.querySelector(".step-circle");
    const num = node.querySelector(".step-num");
    const check = node.querySelector(".step-check");
    const label = node.querySelector(".step-label");

    if (i === stepNum) {
      // Current Active Step (Rausch Red ring & pulsing effect)
      if (circle) circle.className = "step-circle w-7 h-7 rounded-full bg-[#FF385C] border-2 border-[#FF385C] text-white text-[11px] font-extrabold flex items-center justify-center ring-4 ring-[#FF385C]/20 shadow-sm transition-all duration-300 scale-110";
      if (num) num.classList.remove("hidden");
      if (check) check.classList.add("hidden");
      if (label) label.className = "step-label text-[11px] font-extrabold text-[#FF385C] transition-colors";
    } else if (i < stepNum) {
      // Completed Step (Emerald Green checkmark)
      if (circle) circle.className = "step-circle w-7 h-7 rounded-full bg-emerald-500 border-2 border-emerald-500 text-white text-[11px] font-bold flex items-center justify-center transition-all duration-300";
      if (num) num.classList.add("hidden");
      if (check) check.classList.remove("hidden");
      if (label) label.className = "step-label text-[11px] font-bold text-emerald-700 transition-colors";
    } else {
      // Pending Step
      if (circle) circle.className = "step-circle w-7 h-7 rounded-full bg-white border-2 border-[#DDDDDD] text-[#717171] text-[11px] font-bold flex items-center justify-center transition-all duration-300";
      if (num) num.classList.remove("hidden");
      if (check) check.classList.add("hidden");
      if (label) label.className = "step-label text-[11px] font-medium text-[#717171] transition-colors";
    }
  }
}

// ================= CELEBRATION EFFECT =================

function celebrateCompletion() {
  if (typeof confetti === "function") {
    confetti({
      particleCount: 140,
      spread: 90,
      origin: { y: 0.5, x: 0.5 },
      colors: ["#ff385c", "#e00b41", "#ffb400", "#008489", "#26b7fc", "#ffffff"],
    });

    setTimeout(() => {
      confetti({
        particleCount: 70,
        angle: 60,
        spread: 60,
        origin: { x: 0 },
        colors: ["#ff385c", "#ffb400", "#008489"],
      });
      confetti({
        particleCount: 70,
        angle: 120,
        spread: 60,
        origin: { x: 1 },
        colors: ["#ff385c", "#ffb400", "#008489"],
      });
    }, 250);
  }

  playSuccessSound();
}

function playSuccessSound() {
  try {
    const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const now = audioCtx.currentTime;
    const notes = [523.25, 659.25, 783.99, 1046.50]; // C5, E5, G5, C6

    notes.forEach((freq, idx) => {
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();

      osc.type = "sine";
      osc.frequency.setValueAtTime(freq, now + idx * 0.08);

      gain.gain.setValueAtTime(0.001, now + idx * 0.08);
      gain.gain.exponentialRampToValueAtTime(0.18, now + idx * 0.08 + 0.04);
      gain.gain.exponentialRampToValueAtTime(0.001, now + idx * 0.08 + 0.8);

      osc.connect(gain);
      gain.connect(audioCtx.destination);

      osc.start(now + idx * 0.08);
      osc.stop(now + idx * 0.08 + 0.85);
    });
  } catch (e) {
    console.log("Audio synthesis notice:", e);
  }
}

// ================= SINGLE PHOTO INSPECTOR MODAL =================

window.openInspectorByName = function(filename) {
  const photo = state.photos.find((p) => p.filename === filename);
  if (!photo) return;
  if (!photo.is_processed) {
    showToast("Click 'Start' first to process!", "info");
    return;
  }
  openInspector(photo);
};

let inspectorClosing = false;
let livePreviewDebounceTimer = null;

function hasActiveTrims() {
  const trimIds = ["slideExposure", "slideTemp", "slideTint", "slideHighlights", "slideShadows", "slideVibrance", "slideClarity"];
  return trimIds.some((id) => {
    const el = document.getElementById(id);
    return el && Math.abs(parseFloat(el.value) || 0) > 0.0001;
  });
}

function hasActiveCrop() {
  const cropIds = ["slideCropTop", "slideCropBottom", "slideCropLeft", "slideCropRight"];
  return cropIds.some((id) => {
    const el = document.getElementById(id);
    return el && (parseFloat(el.value) || 0) > 0.0001;
  });
}

function updateResetButtonsVisibility() {
  const activeTrims = hasActiveTrims();
  const activeCrop = hasActiveCrop();

  const btnResetAi = document.getElementById("btnResetAiBalance");
  const btnResetCrop = document.getElementById("btnResetCrop");
  const containerResetBase = document.getElementById("containerResetBase");

  if (btnResetAi) {
    if (activeTrims) {
      btnResetAi.classList.remove("hidden");
    } else {
      btnResetAi.classList.add("hidden");
    }
  }

  if (btnResetCrop) {
    if (activeCrop) {
      btnResetCrop.classList.remove("hidden");
    } else {
      btnResetCrop.classList.add("hidden");
    }
  }

  if (containerResetBase) {
    if (activeTrims && activeCrop) {
      containerResetBase.classList.remove("hidden");
    } else {
      containerResetBase.classList.add("hidden");
    }
  }
}

function setSliderValues(adj = {}) {
  const defaults = {
    slideExposure: adj.exposure !== undefined ? adj.exposure : 0.0,
    slideContrast: adj.contrast !== undefined ? adj.contrast : 0,
    slideShadows: adj.shadows !== undefined ? adj.shadows : 0,
    slideHighlights: adj.highlights !== undefined ? adj.highlights : 0,
    slideTemp: adj.temperature !== undefined ? adj.temperature : 0,
    slideTint: adj.tint !== undefined ? adj.tint : 0,
    slideVibrance: adj.vibrance !== undefined ? adj.vibrance : 0,
    slideClarity: adj.clarity !== undefined ? adj.clarity : 0,
    slideCropTop: adj.crop_top !== undefined ? adj.crop_top : 0,
    slideCropBottom: adj.crop_bottom !== undefined ? adj.crop_bottom : 0,
    slideCropLeft: adj.crop_left !== undefined ? adj.crop_left : 0,
    slideCropRight: adj.crop_right !== undefined ? adj.crop_right : 0,
  };

  Object.entries(defaults).forEach(([id, val]) => {
    const el = document.getElementById(id);
    if (el) {
      el.value = val;
      const valId = "val" + id.replace("slide", "");
      const span = document.getElementById(valId);
      if (span) {
        if (id === "slideExposure") {
          const num = parseFloat(val) || 0;
          span.textContent = num > 0 ? `+${num.toFixed(2)}` : (num < 0 ? num.toFixed(2) : "0.00");
        } else if (id.startsWith("slideCrop")) {
          span.textContent = `${Math.round((parseFloat(val) || 0) * 100)}%`;
        } else {
          span.textContent = val;
        }
      }
    }
  });

  updateResetButtonsVisibility();
}

function updateStage2Badge(stateType = "base", sceneType = "General", confidence = 0, aiStatus = null, apiError = null, reason = null) {
  const badge = document.getElementById("badgeStage2State");
  const lblScene = document.getElementById("lblSceneType");
  const lblConf = document.getElementById("lblConfidence");
  const lblDetail = document.getElementById("lblAiStatusDetail");

  if (lblScene) lblScene.textContent = sceneType || "General";
  if (lblConf) lblConf.textContent = `${Math.round((confidence || 0) * 100)}%`;

  if (badge) {
    if (aiStatus === "ai_unavailable" || aiStatus === "ai_failed") {
      badge.textContent = "Unavailable";
      badge.className = "px-3 py-1 rounded-full text-xs font-semibold bg-[#F7F7F7] text-[#717171] border border-[#EBEBEB]";
    } else if (aiStatus === "ai_no_correction") {
      badge.textContent = "Optimal";
      badge.className = "px-3 py-1 rounded-full text-xs font-semibold bg-[#F7F7F7] text-[#222222] border border-[#EBEBEB]";
    } else if (aiStatus === "ai_analyzed" || stateType === "ai") {
      badge.textContent = "Applied";
      badge.className = "px-3 py-1 rounded-full text-xs font-semibold bg-[#F7F7F7] text-[#222222] border border-[#EBEBEB]";
    } else {
      badge.textContent = "Preset Base";
      badge.className = "px-3 py-1 rounded-full text-xs font-semibold bg-[#F7F7F7] text-[#717171] border border-[#EBEBEB]";
    }
  }

  if (lblDetail) {
    if (aiStatus === "ai_unavailable") {
      lblDetail.classList.remove("hidden");
      lblDetail.textContent = "Preset result preserved because AI adjustment was unavailable.";
    } else if (aiStatus === "ai_failed") {
      lblDetail.classList.remove("hidden");
      lblDetail.textContent = "Preset result preserved.";
    } else if (aiStatus === "ai_no_correction") {
      lblDetail.classList.remove("hidden");
      lblDetail.textContent = "Scene lighting is balanced — preset tones preserved.";
    } else {
      lblDetail.classList.add("hidden");
      lblDetail.textContent = "";
    }
  }
}

function updateCropBadge(stateType = "full_frame", method = "None", areaRatio = 1.0, cropStatus = null, apiError = null, reason = null) {
  const badge = document.getElementById("badgeCropState");
  const lblSource = document.getElementById("lblCropSource");
  const lblArea = document.getElementById("lblCropArea");
  const lblDetail = document.getElementById("lblCropDetail");

  if (lblSource) lblSource.textContent = (cropStatus === "ai_crop" || stateType === "crop") ? (method || "Smart Landscape") : "Full Frame";
  if (lblArea) lblArea.textContent = `${Math.round((areaRatio !== undefined ? areaRatio : 1.0) * 100)}%`;

  if (badge) {
    if (cropStatus === "ai_crop" || stateType === "crop") {
      badge.textContent = "AI Crop";
      badge.className = "px-3 py-1 rounded-full text-xs font-semibold bg-[#F7F7F7] text-[#222222] border border-[#EBEBEB]";
    } else {
      badge.textContent = "Full Frame";
      badge.className = "px-3 py-1 rounded-full text-xs font-semibold bg-[#F7F7F7] text-[#717171] border border-[#EBEBEB]";
    }
  }

  if (lblDetail) {
    if (cropStatus === "ai_unavailable" || cropStatus === "ai_rejected" || cropStatus === "ai_failed") {
      lblDetail.classList.remove("hidden");
      lblDetail.textContent = "Full frame preserved.";
    } else {
      lblDetail.classList.add("hidden");
      lblDetail.textContent = "";
    }
  }
}

window.openInspector = function(photo) {
  if (!photo) return;

  // Cancel any prior in-flight fetch for an older inspector session
  if (state.inspectorSession.abortController) {
    try {
      state.inspectorSession.abortController.abort();
    } catch (_) {}
  }
  const sessionSeq = ++state.inspectorSession.seq;
  state.inspectorSession.filename = photo.filename;
  state.inspectorSession.abortController = new AbortController();

  state.activeInspectorPhoto = photo;

  const filenameEl = document.getElementById("modalFilename");
  const origImg = document.getElementById("modalOriginalImg");
  const procImg = document.getElementById("modalProcessedImg");
  const modal = document.getElementById("inspectorModal");
  const backdrop = document.getElementById("inspectorBackdrop");
  const card = document.getElementById("inspectorCard");

  if (filenameEl) filenameEl.textContent = photo.filename;
  if (origImg) origImg.src = photo.input_url;
  if (procImg) {
    procImg.src = photo.output_url ? `${photo.output_url}?t=${Date.now()}` : photo.input_url;
    procImg.style.filter = "none";
  }

  // Populate sliders with this photo's saved adjustment values
  setSliderValues(photo.adjustments || {});
  
  const adjTel = photo.adjust_telemetry || {};
  const cropTel = photo.crop_telemetry || {};

  const hasAdjustments = photo.adjustments && ['exposure', 'temperature', 'tint', 'shadows', 'highlights', 'vibrance', 'clarity'].some(k => typeof photo.adjustments[k] === 'number' && Math.abs(photo.adjustments[k]) > 0.001);
  const aiStatus = adjTel.ai_status || (hasAdjustments ? "ai_analyzed" : "ai_disabled");
  const sceneType = adjTel.scene_type || "General";
  const confidence = adjTel.confidence !== undefined ? adjTel.confidence : (hasAdjustments ? 0.85 : 0);
  const apiError = adjTel.api_error || null;
  const reason = adjTel.reason || null;

  updateStage2Badge(hasAdjustments ? "ai" : "base", sceneType, confidence, aiStatus, apiError, reason);

  const hasCrop = photo.adjustments && ['crop_top', 'crop_bottom', 'crop_left', 'crop_right'].some(k => typeof photo.adjustments[k] === 'number' && photo.adjustments[k] > 0.001);
  const cropStatus = cropTel.crop_status || (hasCrop ? "ai_crop" : "crop_disabled");
  const cropMethod = cropTel.method || (hasCrop ? "Smart Landscape" : "Full Frame");
  const cropArea = cropTel.crop_area_ratio !== undefined ? cropTel.crop_area_ratio : 1.0;
  const cropApiError = cropTel.api_error || null;
  const cropReason = cropTel.reason || null;

  updateCropBadge(hasCrop ? "crop" : "full_frame", cropMethod, cropArea, cropStatus, cropApiError, cropReason);

  updateResetButtonsVisibility();

  if (!modal || !backdrop || !card) return;

  inspectorClosing = false;
  modal.classList.remove("hidden");
  void modal.offsetHeight; // Force layout reflow

  requestAnimationFrame(() => {
    backdrop.classList.remove("opacity-0");
    backdrop.classList.add("opacity-100");

    card.classList.remove("opacity-0", "translate-y-8", "scale-[0.96]");
    card.classList.add("opacity-100", "translate-y-0", "scale-100");
  });

  // Reset split slider to 50%
  updateSplitPosition(50);

  if (window.lucide) lucide.createIcons();
};

window.closeInspector = function() {
  if (inspectorClosing) return;
  const modal = document.getElementById("inspectorModal");
  const backdrop = document.getElementById("inspectorBackdrop");
  const card = document.getElementById("inspectorCard");
  if (!modal || !backdrop || !card) return;

  if (state.inspectorSession.abortController) {
    try {
      state.inspectorSession.abortController.abort();
    } catch (_) {}
    state.inspectorSession.abortController = null;
  }
  state.inspectorSession.filename = null;
  state.inspectorSession.seq++;

  inspectorClosing = true;
  backdrop.classList.remove("opacity-100");
  backdrop.classList.add("opacity-0");

  card.classList.remove("opacity-100", "translate-y-0", "scale-100");
  card.classList.add("opacity-0", "translate-y-6", "scale-[0.96]");

  setTimeout(() => {
    if (inspectorClosing) {
      modal.classList.add("hidden");
      inspectorClosing = false;
      state.activeInspectorPhoto = null;
    }
  }, 450);
};

// Real-Time Live Preview Engine
function applyLiveCssPreview() {
  const exp = parseFloat(document.getElementById("slideExposure")?.value || "0");
  const contrast = parseFloat(document.getElementById("slideContrast")?.value || "0");
  const temp = parseFloat(document.getElementById("slideTemp")?.value || "0");
  const vibrance = parseFloat(document.getElementById("slideVibrance")?.value || "0");

  const brightness = 1 + (exp * 0.35);
  const contrastFactor = 1 + (contrast / 80);
  const saturate = 1 + (vibrance / 60);
  const hueRotate = temp * 0.25;

  const img = document.getElementById("modalProcessedImg");
  if (img) {
    img.style.filter = `brightness(${brightness}) contrast(${contrastFactor}) saturate(${saturate}) hue-rotate(${hueRotate}deg)`;
  }
}

function triggerLivePreview() {
  applyLiveCssPreview();

  if (livePreviewDebounceTimer) {
    clearTimeout(livePreviewDebounceTimer);
  }

  livePreviewDebounceTimer = setTimeout(() => {
    updatePreview(false);
  }, 160);
}

function initSliderValueTrackers() {
  const map = {
    slideExposure: "valExposure",
    slideContrast: "valContrast",
    slideShadows: "valShadows",
    slideHighlights: "valHighlights",
    slideTemp: "valTemp",
    slideTint: "valTint",
    slideVibrance: "valVibrance",
    slideClarity: "valClarity",
    slideCropTop: "valCropTop",
    slideCropBottom: "valCropBottom",
    slideCropLeft: "valCropLeft",
    slideCropRight: "valCropRight",
  };

  Object.entries(map).forEach(([sliderId, valId]) => {
    const slider = document.getElementById(sliderId);
    const valSpan = document.getElementById(valId);
    if (slider) {
      slider.addEventListener("input", (e) => {
        if (valSpan) {
          if (sliderId === "slideExposure") {
            const num = parseFloat(e.target.value) || 0;
            valSpan.textContent = num > 0 ? `+${num.toFixed(2)}` : (num < 0 ? num.toFixed(2) : "0.00");
          } else if (sliderId.startsWith("slideCrop")) {
            const num = parseFloat(e.target.value) || 0;
            valSpan.textContent = `${Math.round(num * 100)}%`;
          } else {
            valSpan.textContent = e.target.value;
          }
        }
        updateResetButtonsVisibility();
        triggerLivePreview();
      });
    }
  });
}

function resetSliders(triggerUpdate = true) {
  setSliderValues({});

  const procImg = document.getElementById("modalProcessedImg");
  if (procImg) procImg.style.filter = "none";

  if (triggerUpdate && state.activeInspectorPhoto) {
    updatePreview(false);
  }
}

window.resetParametricSliders = function() {
  const trimIds = ["slideExposure", "slideTemp", "slideTint", "slideHighlights", "slideShadows", "slideVibrance", "slideClarity"];
  trimIds.forEach((id) => {
    const el = document.getElementById(id);
    if (el) {
      el.value = 0;
      const valId = "val" + id.replace("slide", "");
      const span = document.getElementById(valId);
      if (span) {
        if (id === "slideExposure") span.textContent = "0.00";
        else span.textContent = "0";
      }
    }
  });
  updateResetButtonsVisibility();
  triggerLivePreview();
};

window.resetAiBalance = function() {
  const trimIds = ["slideExposure", "slideTemp", "slideTint", "slideHighlights", "slideShadows", "slideVibrance", "slideClarity"];
  trimIds.forEach((id) => {
    const el = document.getElementById(id);
    if (el) {
      el.value = 0;
      const valId = "val" + id.replace("slide", "");
      const span = document.getElementById(valId);
      if (span) {
        if (id === "slideExposure") span.textContent = "0.00";
        else span.textContent = "0";
      }
    }
  });

  updateStage2Badge("base", "General", 0, "ai_disabled", null, null);

  if (state.activeInspectorPhoto) {
    if (!state.activeInspectorPhoto.adjustments) state.activeInspectorPhoto.adjustments = {};
    trimIds.forEach((id) => {
      let key = id.replace("slide", "").toLowerCase();
      if (key === "temp") key = "temperature";
      state.activeInspectorPhoto.adjustments[key] = 0;
    });
  }

  updateResetButtonsVisibility();
  updatePreview(true);
  showToast("AI Balance reset to 0 (Crop preserved)", "info");
};

window.resetSmartCrop = function() {
  const cropIds = ["slideCropTop", "slideCropBottom", "slideCropLeft", "slideCropRight"];
  cropIds.forEach((id) => {
    const el = document.getElementById(id);
    if (el) {
      el.value = 0;
      const valId = "val" + id.replace("slide", "");
      const span = document.getElementById(valId);
      if (span) span.textContent = "0%";
    }
  });

  updateCropBadge("full_frame", "Full Frame", 1.0, "crop_disabled", null, null);

  if (state.activeInspectorPhoto) {
    if (!state.activeInspectorPhoto.adjustments) state.activeInspectorPhoto.adjustments = {};
    state.activeInspectorPhoto.adjustments.crop_top = 0;
    state.activeInspectorPhoto.adjustments.crop_bottom = 0;
    state.activeInspectorPhoto.adjustments.crop_left = 0;
    state.activeInspectorPhoto.adjustments.crop_right = 0;
  }

  updateResetButtonsVisibility();
  updatePreview(true);
  showToast("Crop reset to Full Frame (AI Balance preserved)", "info");
};

async function resetToPresetBase() {
  if (!state.activeInspectorPhoto) return;
  const targetPhoto = state.activeInspectorPhoto;
  const currentFilename = targetPhoto.filename;
  const currentSeq = ++state.inspectorSession.seq;

  if (state.inspectorSession.abortController) {
    try { state.inspectorSession.abortController.abort(); } catch (_) {}
  }
  state.inspectorSession.abortController = new AbortController();

  const btn = document.getElementById("btnResetToBase");
  if (btn) {
    btn.innerHTML = `<i data-lucide="loader-2" class="w-3 h-3 animate-spin"></i> Resetting...`;
    if (window.lucide) lucide.createIcons();
  }

  try {
    const res = await fetch("/api/adjust/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename: currentFilename }),
      signal: state.inspectorSession.abortController.signal,
    });
    const data = await res.json();

    // Guard: ignore stale responses if inspector switched or closed
    if (state.inspectorSession.seq !== currentSeq || !state.activeInspectorPhoto || state.activeInspectorPhoto.filename !== currentFilename) {
      return;
    }

    if (data.status === "reset") {
      setSliderValues({});
      updateStage2Badge("base", "General", 0, "ai_disabled", null, null);
      updateCropBadge("full_frame", "Full Frame", 1.0, "crop_disabled", null, null);
      updateResetButtonsVisibility();
      const procImg = document.getElementById("modalProcessedImg");
      if (procImg) {
        procImg.src = data.preview_data_url;
        procImg.style.filter = "none";
      }
      showToast("Reset to Stage 1 Preset Base!", "success");
      loadPhotos();
    }
  } catch (err) {
    if (err.name === "AbortError") return;
    showToast("Reset failed: " + err, "error");
  } finally {
    if (btn && state.activeInspectorPhoto && state.activeInspectorPhoto.filename === currentFilename) {
      btn.innerHTML = `<i data-lucide="rotate-ccw" class="w-3.5 h-3.5"></i> Reset All to Stage 1 Preset Base`;
      if (window.lucide) lucide.createIcons();
    }
  }
}

async function applyAiBalance() {
  if (!state.activeInspectorPhoto) return;
  const targetPhoto = state.activeInspectorPhoto;
  const currentFilename = targetPhoto.filename;
  const currentSeq = ++state.inspectorSession.seq;

  if (state.inspectorSession.abortController) {
    try { state.inspectorSession.abortController.abort(); } catch (_) {}
  }
  state.inspectorSession.abortController = new AbortController();

  const btn = document.getElementById("btnApplyAiBalance");
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i> Analyzing...`;
    if (window.lucide) lucide.createIcons();
  }

  try {
    const res = await fetch("/api/adjust/ai-balance", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename: currentFilename }),
      signal: state.inspectorSession.abortController.signal,
    });
    const data = await res.json();

    // Guard: ignore stale responses if inspector switched or closed
    if (state.inspectorSession.seq !== currentSeq || !state.activeInspectorPhoto || state.activeInspectorPhoto.filename !== currentFilename) {
      return;
    }

    if (data.status === "ok") {
      setSliderValues(data.adjustments || {});
      updateStage2Badge(
        data.ai_status === "ai_analyzed" ? "ai" : "base",
        data.scene_type || "General",
        data.confidence || 0,
        data.ai_status,
        data.api_error,
        data.reason
      );
      updateResetButtonsVisibility();
      const procImg = document.getElementById("modalProcessedImg");
      if (procImg && data.preview_data_url) {
        procImg.src = data.preview_data_url;
        procImg.style.filter = "none";
      }

      if (data.ai_status === "ai_analyzed") {
        showToast(`AI Balanced: ${data.scene_type || 'Optimized'} (${Math.round((data.confidence || 0)*100)}% conf)`, "success");
      } else if (data.ai_status === "ai_no_correction") {
        showToast("Optimal lighting detected — Preset preserved", "info");
      } else if (data.ai_status === "ai_unavailable") {
        showToast("Vision AI Unavailable: Rate limit reached or API offline (Preset preserved)", "warning");
      } else if (data.ai_status === "ai_disabled") {
        showToast("AI Auto-Balancing is disabled or API key is missing in Settings", "warning");
      } else if (data.ai_status === "ai_failed") {
        showToast("AI Failed: " + (data.api_error || data.reason || "Server error") + " (Preset preserved)", "error");
      }
    } else {
      showToast("AI Balancing returned no adjustments", "info");
    }
  } catch (err) {
    if (err.name === "AbortError") return;
    showToast("AI Balancing failed: " + err, "error");
  } finally {
    if (btn && state.activeInspectorPhoto && state.activeInspectorPhoto.filename === currentFilename) {
      btn.disabled = false;
      btn.innerHTML = `<i data-lucide="sparkles" class="w-3.5 h-3.5 text-amber-400"></i> Apply AI Balance`;
      if (window.lucide) lucide.createIcons();
    }
  }
}

async function applyAutoSmartCrop() {
  if (!state.activeInspectorPhoto) return;
  const targetPhoto = state.activeInspectorPhoto;
  const currentFilename = targetPhoto.filename;
  const currentSeq = ++state.inspectorSession.seq;

  if (state.inspectorSession.abortController) {
    try { state.inspectorSession.abortController.abort(); } catch (_) {}
  }
  state.inspectorSession.abortController = new AbortController();

  const btn = document.getElementById("btnApplyAutoCrop");
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i> Cropping...`;
    if (window.lucide) lucide.createIcons();
  }

  const payload = {
    filename: currentFilename,
    exposure: parseFloat(document.getElementById("slideExposure")?.value || "0"),
    contrast: parseFloat(document.getElementById("slideContrast")?.value || "0"),
    shadows: parseFloat(document.getElementById("slideShadows")?.value || "0"),
    highlights: parseFloat(document.getElementById("slideHighlights")?.value || "0"),
    temperature: parseFloat(document.getElementById("slideTemp")?.value || "0"),
    tint: parseFloat(document.getElementById("slideTint")?.value || "0"),
    vibrance: parseFloat(document.getElementById("slideVibrance")?.value || "0"),
    clarity: parseFloat(document.getElementById("slideClarity")?.value || "0"),
    crop_top: 0.0,
    crop_bottom: 0.0,
    crop_left: 0.0,
    crop_right: 0.0,
  };

  try {
    const res = await fetch("/api/adjust/smart-crop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: state.inspectorSession.abortController.signal,
    });
    const data = await res.json();

    // Guard: ignore stale responses if inspector switched or closed
    if (state.inspectorSession.seq !== currentSeq || !state.activeInspectorPhoto || state.activeInspectorPhoto.filename !== currentFilename) {
      return;
    }

    if (data.status === "ok") {
      if (data.crop) {
        const c = data.crop;
        const cropObj = {
          crop_top: c.crop_top !== undefined ? c.crop_top : 0,
          crop_bottom: c.crop_bottom !== undefined ? c.crop_bottom : 0,
          crop_left: c.crop_left !== undefined ? c.crop_left : 0,
          crop_right: c.crop_right !== undefined ? c.crop_right : 0,
        };
        // Update crop slider values and labels
        ['Top', 'Bottom', 'Left', 'Right'].forEach((dir) => {
          const key = `crop_${dir.toLowerCase()}`;
          const val = cropObj[key];
          const el = document.getElementById(`slideCrop${dir}`);
          const span = document.getElementById(`valCrop${dir}`);
          if (el) el.value = val;
          if (span) span.textContent = `${Math.round(val * 100)}%`;
        });
      }
      const procImg = document.getElementById("modalProcessedImg");
      if (procImg && data.preview_data_url) {
        procImg.src = data.preview_data_url;
        procImg.style.filter = "none";
      }
      const tele = data.crop_telemetry || {};
      const cropStatus = data.crop_status || tele.crop_status || "ai_crop";
      const method = tele.method || "Smart Landscape";
      const areaRatio = tele.crop_area_ratio !== undefined ? tele.crop_area_ratio : 1.0;
      const areaPct = Math.round(areaRatio * 100);

      updateCropBadge(
        cropStatus === "ai_crop" ? "crop" : "full_frame",
        method,
        areaRatio,
        cropStatus,
        data.api_error || tele.api_error,
        tele.reason
      );
      updateResetButtonsVisibility();

      if (cropStatus === "ai_crop") {
        showToast(`Smart Crop: ${method} (${areaPct}% area)`, "success");
      } else if (cropStatus === "ai_unavailable") {
        showToast("Vision AI Unavailable: Rate limit reached or API offline (Full frame preserved)", "warning");
      } else if (cropStatus === "crop_disabled") {
        showToast("Smart Crop is disabled or API key is missing in Settings", "warning");
      } else if (cropStatus === "ai_rejected") {
        showToast(`Smart Crop: ${tele.reason || 'Full frame optimal'} (Full frame preserved)`, "info");
      } else if (cropStatus === "ai_failed") {
        showToast("Smart Crop Failed: " + (data.api_error || tele.reason || "Error") + " (Full frame preserved)", "error");
      } else {
        showToast("Smart Crop: Full frame preserved", "info");
      }
    } else {
      showToast("Smart Crop could not be calculated", "info");
    }
  } catch (err) {
    if (err.name === "AbortError") return;
    showToast("Smart Crop failed: " + err, "error");
  } finally {
    if (btn && state.activeInspectorPhoto && state.activeInspectorPhoto.filename === currentFilename) {
      btn.disabled = false;
      btn.innerHTML = `<i data-lucide="crop" class="w-3.5 h-3.5 text-amber-400"></i> Auto Smart Crop`;
      if (window.lucide) lucide.createIcons();
    }
  }
}

window.applyAiBalance = applyAiBalance;
window.applyAutoSmartCrop = applyAutoSmartCrop;
window.resetToPresetBase = resetToPresetBase;

async function updatePreview(showButtonLoader = true) {
  if (!state.activeInspectorPhoto) return;
  const targetPhoto = state.activeInspectorPhoto;
  const currentFilename = targetPhoto.filename;
  const currentSeq = ++state.inspectorSession.seq;

  if (state.inspectorSession.abortController) {
    try { state.inspectorSession.abortController.abort(); } catch (_) {}
  }
  state.inspectorSession.abortController = new AbortController();

  const payload = {
    filename: currentFilename,
    exposure: parseFloat(document.getElementById("slideExposure")?.value || "0"),
    contrast: parseFloat(document.getElementById("slideContrast")?.value || "0"),
    shadows: parseFloat(document.getElementById("slideShadows")?.value || "0"),
    highlights: parseFloat(document.getElementById("slideHighlights")?.value || "0"),
    temperature: parseFloat(document.getElementById("slideTemp")?.value || "0"),
    tint: parseFloat(document.getElementById("slideTint")?.value || "0"),
    vibrance: parseFloat(document.getElementById("slideVibrance")?.value || "0"),
    clarity: parseFloat(document.getElementById("slideClarity")?.value || "0"),
    crop_top: parseFloat(document.getElementById("slideCropTop")?.value || "0"),
    crop_bottom: parseFloat(document.getElementById("slideCropBottom")?.value || "0"),
    crop_left: parseFloat(document.getElementById("slideCropLeft")?.value || "0"),
    crop_right: parseFloat(document.getElementById("slideCropRight")?.value || "0"),
  };

  const btn = document.getElementById("btnApplyPreview");
  try {
    if (showButtonLoader && btn) {
      btn.innerHTML = `<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i> Rendering...`;
      if (window.lucide) lucide.createIcons();
    }

    const res = await fetch("/api/adjust/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: state.inspectorSession.abortController.signal,
    });

    const data = await res.json();

    // Guard: ignore stale responses if inspector switched or closed
    if (state.inspectorSession.seq !== currentSeq || !state.activeInspectorPhoto || state.activeInspectorPhoto.filename !== currentFilename) {
      return;
    }

    if (data.status === "ok") {
      const procImg = document.getElementById("modalProcessedImg");
      if (procImg) {
        procImg.src = data.preview_data_url;
        procImg.style.filter = "none"; // Clear temporary CSS filter once rendered
      }
    }

    if (showButtonLoader && btn && state.activeInspectorPhoto && state.activeInspectorPhoto.filename === currentFilename) {
      btn.innerHTML = `<i data-lucide="wand-2" class="w-3.5 h-3.5 text-[#FF385C]"></i> Update Preview`;
      if (window.lucide) lucide.createIcons();
    }
  } catch (err) {
    if (err.name === "AbortError") return;
    console.error("Preview failed:", err);
  }
}

async function saveCustomAdjustments() {
  if (!state.activeInspectorPhoto) return;
  const targetPhoto = state.activeInspectorPhoto;
  const currentFilename = targetPhoto.filename;
  const currentSeq = ++state.inspectorSession.seq;

  const btn = document.getElementById("btnModalSave");
  if (btn) {
    btn.disabled = true;
    btn.classList.add("opacity-80", "cursor-not-allowed");
    btn.innerHTML = `<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i> Saving...`;
    if (window.lucide) lucide.createIcons();
  }

  const payload = {
    filename: currentFilename,
    exposure: parseFloat(document.getElementById("slideExposure")?.value || "0"),
    contrast: parseFloat(document.getElementById("slideContrast")?.value || "0"),
    shadows: parseFloat(document.getElementById("slideShadows")?.value || "0"),
    highlights: parseFloat(document.getElementById("slideHighlights")?.value || "0"),
    temperature: parseFloat(document.getElementById("slideTemp")?.value || "0"),
    tint: parseFloat(document.getElementById("slideTint")?.value || "0"),
    vibrance: parseFloat(document.getElementById("slideVibrance")?.value || "0"),
    clarity: parseFloat(document.getElementById("slideClarity")?.value || "0"),
    crop_top: parseFloat(document.getElementById("slideCropTop")?.value || "0"),
    crop_bottom: parseFloat(document.getElementById("slideCropBottom")?.value || "0"),
    crop_left: parseFloat(document.getElementById("slideCropLeft")?.value || "0"),
    crop_right: parseFloat(document.getElementById("slideCropRight")?.value || "0"),
  };

  try {
    const res = await fetch("/api/adjust/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const data = await res.json();
    if (data.status === "saved") {
      showToast(`Saved overrides: ${data.output_filename}`, "success");
      // Update in-memory photo state with saved adjustment parameters
      if (state.activeInspectorPhoto && state.activeInspectorPhoto.filename === currentFilename) {
        state.activeInspectorPhoto.adjustments = data.adjustments || payload;
      }
      const p = state.photos.find((x) => x.filename === payload.filename);
      if (p) {
        p.adjustments = data.adjustments || payload;
      }
      closeInspector();
      loadPhotos();
    } else {
      showToast("Save failed", "error");
    }
  } catch (err) {
    showToast("Save error: " + err, "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.classList.remove("opacity-80", "cursor-not-allowed");
      btn.innerHTML = `<i data-lucide="check" class="w-4 h-4"></i> Save Overrides`;
      if (window.lucide) lucide.createIcons();
    }
  }
}

// ================= SPLIT SLIDER COMPARISON =================

function updateSplitPosition(pct) {
  pct = Math.max(0, Math.min(100, pct));
  const clip = document.getElementById("modalBeforeClip");
  const line = document.getElementById("modalDividerLine");
  if (clip) clip.style.clipPath = `inset(0 ${100 - pct}% 0 0)`;
  if (line) line.style.left = `${pct}%`;
}

function initSplitSlider() {
  const container = document.getElementById("splitViewerContainer");
  if (!container) return;
  let isDragging = false;

  function move(e) {
    if (!isDragging) return;
    const rect = container.getBoundingClientRect();
    const clientX = e.clientX !== undefined ? e.clientX : (e.touches && e.touches[0] ? e.touches[0].clientX : 0);
    const x = clientX - rect.left;
    const pct = (x / rect.width) * 100;
    updateSplitPosition(pct);
  }

  container.addEventListener("mousedown", (e) => {
    isDragging = true;
    move(e);
  });
  window.addEventListener("mouseup", () => (isDragging = false));
  window.addEventListener("mousemove", move);

  container.addEventListener("touchstart", (e) => {
    isDragging = true;
    move(e);
  }, { passive: true });
  window.addEventListener("touchend", () => (isDragging = false));
  window.addEventListener("touchmove", move, { passive: true });
}

// ================= DNG / LUT DRAG & DROP =================

function initDropZone() {
  const dropZone = document.getElementById("dropZone");
  const fileInput = document.getElementById("presetFileInput");
  if (!dropZone || !fileInput) return;

  dropZone.addEventListener("click", () => fileInput.click());

  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("border-[#FF385C]", "bg-rose-50/30");
  });

  dropZone.addEventListener("dragleave", () => {
    dropZone.classList.remove("border-[#FF385C]", "bg-rose-50/30");
  });

  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("border-[#FF385C]", "bg-rose-50/30");
    if (e.dataTransfer.files.length > 0) {
      uploadPresetFile(e.dataTransfer.files[0]);
    }
  });

  fileInput.addEventListener("change", () => {
    if (fileInput.files.length > 0) {
      uploadPresetFile(fileInput.files[0]);
    }
  });
}

async function uploadPresetFile(file) {
  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch("/api/presets/upload", {
      method: "POST",
      body: formData,
    });
    const data = await res.json();
    if (data.status === "uploaded") {
      showToast(`Preset ${data.filename} uploaded & activated!`, "success");
      loadPresets();
    }
  } catch (err) {
    showToast("Upload failed: " + err, "error");
  }
}
