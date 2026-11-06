/* VideoStudio Pro — End-User Native Desktop Controller */
const state = {
  bootstrap: null,
  scan: null,
  recommendations: null,
  activeProfile: "balanced",
  productionMode: "auto",
  stageOverrides: {},
  globalModelQuery: "",
  _stagePools: {},
  wizardStep: 1,
  selectedVoice: "es-MX-JorgeNeural",
  savedWizardChannelId: null,
  pipelineTimer: null,
  updaterTimer: null,
  defaultStages: [
    { id: "trend-researcher", name: "1. Tendencias", role: "Busca un tema viral sin repetir en 30 días" },
    { id: "viral-scriptwriter", name: "2. Guión Viral", role: "Escribe la historia en 5 partes (62 a 72 s)" },
    { id: "viral-copywriter", name: "3. Título y Descripción", role: "Prepara título atractivo, etiquetas y debate" },
    { id: "visual-asset-reviewer", name: "4. Selección Visual", role: "Elige foto real inicial y escenas verticales" },
    { id: "video-renderer", name: "5. Montaje y Renderizado", role: "Une narración, música y subtítulos por GPU" },
    { id: "video-qa-validator", name: "6. Control de Calidad", role: "Revisa duración exacta y encuadre móvil" },
    { id: "thumbnail-designer", name: "7. Portada Viral", role: "Crea la miniatura con titular de alto impacto" },
    { id: "packaging-archiver", name: "8. Archivo y Protección", role: "Guarda el paquete y protege el tema 30 días" },
    { id: "social-media-publisher", name: "9. Publicación", role: "Sube a tus redes o deja listo en tu PC" },
  ],
};

async function api(path, method = "GET", body = null) {
  const opts = { method, headers: {} };
  if (body !== null) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || data.error || `Error inesperado (${res.status})`);
  }
  return data;
}

function toast(msg) {
  const el = document.getElementById("toastBox");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(window._toastTimeout);
  window._toastTimeout = setTimeout(() => el.classList.remove("show"), 3800);
}

function mediaUrl(absPath) {
  if (!absPath) return "";
  return `/api/media?path=${encodeURIComponent(absPath)}&t=${Date.now()}`;
}

function esc(str) {
  return String(str ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

window.openExternalUrl = function (url) {
  if (!url) return;
  api("/api/system/open-url", "POST", { target: url }).catch(() => {});
};

window.togglePasswordField = function (inputId, btnEl) {
  const inp = document.getElementById(inputId);
  if (!inp) return;
  const isPass = inp.type === "password";
  inp.type = isPass ? "text" : "password";
  btnEl.textContent = isPass ? "Ocultar" : "Ver";
};

/* ==================== INITIALIZATION ==================== */
async function initApp() {
  bindNavigation();
  bindStudioControls();
  bindWizardControls();
  bindSettingsAndUpdater();

  await refreshBootstrap();
  renderPipelineStagesIdle();
  await refreshModelScan(false);
  await refreshGallery();
  pollPipeline();
}

async function refreshBootstrap() {
  const data = await api("/api/bootstrap");
  state.bootstrap = data;
  state.activeProfile = data.settings.model_profile || "balanced";
  state.productionMode = data.settings.production_mode || "auto";
  state.stageOverrides = data.settings.stage_models || {};

  document.getElementById("topVersionBadge").textContent = `v${data.version.version}`;
  const hw = data.hardware || {};
  const gpuBadge = document.getElementById("gpuTopBadge");
  if (hw.video_encoder === "h264_nvenc") {
    gpuBadge.textContent = `⚡ ${hw.gpu_name.replace("NVIDIA GeForce ", "")} Activa`;
  } else if (hw.video_encoder === "h264_amf") {
    gpuBadge.textContent = `⚡ ${hw.gpu_name}`;
  } else {
    gpuBadge.textContent = `Procesador (${hw.cpu_cores || 4} núcleos)`;
  }

  syncProdModeUI(state.productionMode);
  document.getElementById("settingsGithubRepo").value = data.settings.github_repo || data.version.github_repo || "";

  renderCacheBar(data.cache);
  renderChannelsDropdownAndTab(data.channels);
  renderProvidersCards(data.providers);
  renderUpdaterBar(data.updater);
  renderWizardHardware(hw, data.stock, data.legacy_cli);
  renderWizardVoices();
  updateSubtitleSimulator();

  if (!data.settings.wizard_completed) {
    openWizard(1);
  }
}

/* ==================== NAVIGATION ==================== */
function bindNavigation() {
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".nav-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
      if (btn.dataset.tab === "gallery") refreshGallery();
    });
  });

  document.getElementById("btnQuickPurge").addEventListener("click", async () => {
    const res = await api("/api/storage/purge?full=true", "POST");
    renderCacheBar(res.updated_health);
    toast(`Archivos temporales liberados (${res.freed_mb} MB).`);
  });
}

function renderCacheBar(cache) {
  if (!cache) return;
  document.getElementById("sidebarCacheText").textContent = `${Math.round(cache.used_mb || 0)} / ${cache.cap_mb} MB`;
  document.getElementById("sidebarCacheBar").style.width = `${Math.min(100, cache.percent)}%`;
}

/* ==================== TOP BAR GITHUB 1-CLICK UPDATER ==================== */
function renderUpdaterBar(u) {
  if (!u) return;
  const dot = document.getElementById("updaterDot");
  const txt = document.getElementById("updaterText");
  const cta = document.getElementById("btnOneClickUpdate");

  dot.className = "updater-dot";
  cta.style.display = "none";

  if (u.status === "update_available") {
    dot.classList.add("update");
    txt.textContent = `Nueva versión v${u.latest_version} (${u.asset_size_mb} MB)`;
    cta.style.display = "inline-flex";
    cta.textContent = `Actualizar a v${u.latest_version}`;
    cta.disabled = false;
  } else if (u.status === "downloading") {
    dot.classList.add("update");
    txt.textContent = `Descargando actualización: ${u.progress_percent}% (${u.speed_mbps} MB/s)`;
    cta.style.display = "inline-flex";
    cta.textContent = `${u.progress_percent}%`;
    cta.disabled = true;
  } else if (u.status === "ready_to_install") {
    dot.classList.add("update");
    txt.textContent = `Actualización lista para instalar`;
    cta.style.display = "inline-flex";
    cta.textContent = `Reiniciar y actualizar`;
    cta.disabled = false;
  } else if (u.status === "error") {
    dot.classList.add("error");
    txt.textContent = u.message || `Versión v${u.current_version}`;
  } else {
    dot.classList.add("pending");
    txt.textContent = u.message || `Versión v${u.current_version} · Al día`;
  }
}

function bindSettingsAndUpdater() {
  document.getElementById("btnCheckUpdates").addEventListener("click", async () => {
    document.getElementById("updaterText").textContent = "Comprobando...";
    const u = await api("/api/updater/check", "POST");
    renderUpdaterBar(u);
    toast(u.message || "Versión comprobada.");
  });

  document.getElementById("btnOneClickUpdate").addEventListener("click", async () => {
    const cur = await api("/api/updater/status");
    if (cur.status === "ready_to_install") {
      toast("Abriendo instalador de la nueva versión...");
      await api("/api/updater/install", "POST");
      return;
    }
    await api("/api/updater/download", "POST");
    clearInterval(state.updaterTimer);
    state.updaterTimer = setInterval(async () => {
      const st = await api("/api/updater/status");
      renderUpdaterBar(st);
      if (st.status === "ready_to_install") {
        clearInterval(state.updaterTimer);
        toast("Descarga verificada. Actualizando aplicación...");
        await api("/api/updater/install", "POST");
      } else if (st.status === "error") {
        clearInterval(state.updaterTimer);
        toast(st.error || "No se pudo completar la descarga.");
      }
    }, 650);
  });

  document.getElementById("btnSaveGitRepo").addEventListener("click", async () => {
    const repo = document.getElementById("settingsGithubRepo").value.trim();
    await api("/api/settings", "POST", { github_repo: repo });
    const u = await api("/api/updater/check", "POST");
    renderUpdaterBar(u);
    toast("Repositorio guardado correctamente.");
  });

  document.getElementById("btnSaveStockSettings").addEventListener("click", async () => {
    const pix = document.getElementById("settingsPixabayKey").value.trim();
    const pex = document.getElementById("settingsPexelsKey").value.trim();
    const res = await api("/api/stock/save", "POST", { pixabay_key: pix, pexels_key: pex });
    toast(res.validation.pixabay.message || res.validation.pexels.message || "Claves de escenas guardadas.");
  });

  document.getElementById("btnGetPixabayKey").addEventListener("click", () => {
    openExternalUrl("https://pixabay.com/api/docs/");
  });
}

/* ==================== MULTI-IA ROUTER & FREE/PAID SCANNER ==================== */
function renderProvidersCards(providersMap) {
  const entries = Object.values(providersMap || {});
  const renderInto = (containerId, compact = false) => {
    const el = document.getElementById(containerId);
    if (!el) return;
    el.innerHTML = entries.map((p) => {
      const scanInfo = state.scan?.providers?.[p.id] || {};
      let statusBadge = "";
      if (scanInfo.connected) {
        statusBadge = `<span class="badge badge-free">Conectado · ${scanInfo.free_count || 0} Gratis / ${scanInfo.paid_count || 0} Pago</span>`;
      } else if (p.id === "local") {
        statusBadge = `<span class="badge badge-neutral">Opcional en tu PC</span>`;
      } else if (p.has_api_key) {
        statusBadge = `<span class="badge badge-paid">Clave guardada</span>`;
      } else {
        statusBadge = `<span class="badge badge-neutral">Sin conectar</span>`;
      }

      const showUrl = p.id === "omnirouter" || p.id === "local";
      const inputId = `${containerId}_key_${p.id}`;
      const helperLink = p.key_url
        ? `<button type="button" class="link-btn" onclick="openExternalUrl('${esc(p.key_url)}')">${esc(p.key_cta || "Obtener clave ↗")}</button>`
        : "";

      return `
        <div class="provider-card" style="padding:${compact ? "12px 14px" : "15px 16px"};">
          <div>
            <div class="provider-head">
              <strong style="font-size:14px;">${esc(p.label)}</strong>
              ${statusBadge}
            </div>
            <div style="display:flex; justify-content:space-between; align-items:baseline; gap:10px; margin-bottom:9px;">
              <p style="font-size:11.5px; color:var(--text-muted); line-height:1.35;">${esc(p.notes)}</p>
              ${helperLink}
            </div>
            ${showUrl ? `
              <label class="field-label">Dirección local o servidor</label>
              <input type="text" id="${containerId}_url_${p.id}" value="${esc(p.base_url)}" style="margin-bottom:8px;" />
            ` : ""}
          </div>
          ${p.id !== "local" ? `
            <div class="key-input-row">
              <input type="password" id="${inputId}" placeholder="${p.masked_key ? `Clave guardada (${p.masked_key})` : "Pega aquí tu clave de API..."}" />
              <button type="button" class="eye-btn" onclick="togglePasswordField('${inputId}', this)">Ver</button>
              <button type="button" class="btn btn-primary btn-sm" onclick="saveProvider('${p.id}', '${containerId}')">Conectar</button>
            </div>
          ` : `
            <div>
              <button type="button" class="btn btn-sm" onclick="saveProvider('${p.id}', '${containerId}')">Detectar modelos locales</button>
            </div>
          `}
        </div>
      `;
    }).join("");
  };
  renderInto("providersGrid", false);
  renderInto("wizProvidersContainer", true);
}

window.saveProvider = async function (providerId, prefix) {
  const keyEl = document.getElementById(`${prefix}_key_${providerId}`);
  const urlEl = document.getElementById(`${prefix}_url_${providerId}`);
  const typedKey = keyEl ? keyEl.value.trim() : "";
  const existingProvider = state.bootstrap?.providers?.[providerId];

  if (providerId !== "local" && providerId !== "omnirouter" && !typedKey && !existingProvider?.has_api_key) {
    toast("Pega primero tu clave de API para poder conectar este proveedor.");
    if (keyEl) keyEl.focus();
    return;
  }

  const apiKey = typedKey ? typedKey : "KEEP_EXISTING";
  const baseUrl = urlEl ? urlEl.value.trim() : null;
  toast("Verificando conexión y detectando modelos disponibles...");

  try {
    const res = await api("/api/ai/providers", "POST", {
      provider_id: providerId,
      api_key: apiKey,
      base_url: baseUrl,
      enabled: true,
    });
    state.scan = res.scan;
    state.recommendations = res.recommendations;
    const provs = await api("/api/ai/providers");
    if (state.bootstrap) state.bootstrap.providers = provs.providers;
    renderProvidersCards(provs.providers);
    renderModelRecommendationsUI();

    const pScan = res.scan?.providers?.[providerId] || {};
    if (pScan.connected) {
      toast(`¡${res.provider.label} conectado! ${pScan.free_count || 0} modelos gratis y ${pScan.paid_count || 0} de pago listos.`);
    } else {
      toast(pScan.error ? `No pudimos conectar con ${res.provider.label}: verifica tu clave.` : `Clave guardada para ${res.provider.label}.`);
    }
  } catch (e) {
    toast(e.message);
  }
};

async function refreshModelScan(force = false) {
  const res = await api(`/api/ai/scan?force=${force}`);
  state.scan = res.scan;
  state.recommendations = res.recommendations;
  state.activeProfile = res.active_profile || state.activeProfile;
  if (state.bootstrap?.providers) {
    renderProvidersCards(state.bootstrap.providers);
  }
  renderModelRecommendationsUI();
}

function modelMatchesQuery(m, rawQuery) {
  const q = (rawQuery || "").trim().toLowerCase();
  if (!q) return true;
  const hay = [
    m.provider_label,
    m.provider,
    m.display_name,
    m.model_id,
    m.free_note,
    m.is_free ? "gratis free $0 0" : "pago paid",
    m.supports_vision ? "vision visión multimodal" : "texto",
  ].join(" ").toLowerCase();
  return q.split(/\s+/).every((tok) => hay.includes(tok));
}

function renderModelRecommendationsUI() {
  const scan = state.scan || { free_models_count: 0, paid_models_count: 0, vision_models_count: 0, models: [] };
  const recs = state.recommendations || { stages: [], profiles: { free: {}, balanced: {}, pro: {} }, estimated_cost_usd_per_video: {}, warnings: [] };
  const allModels = scan.models || [];
  const byKey = {};
  allModels.forEach((m) => { byKey[m.key] = m; });

  const badgeTxt = `${scan.free_models_count} Gratis · ${scan.paid_models_count} de Pago · ${scan.vision_models_count} con Visión`;
  document.getElementById("scanCountersBadge").textContent = badgeTxt;
  document.getElementById("wizModelCountBadge").textContent = badgeTxt;

  const costs = recs.estimated_cost_usd_per_video || {};
  document.getElementById("costFree").textContent = `$${(costs.free || 0).toFixed(3)} / video`;
  document.getElementById("costBalanced").textContent = `~$${(costs.balanced || 0).toFixed(3)} / video`;
  document.getElementById("costPro").textContent = `~$${(costs.pro || 0).toFixed(3)} / video`;

  const profileNames = {
    free: "Solo Modelos Gratis",
    balanced: "Equilibrado Recomendado",
    pro: "Máxima Calidad Pro",
  };

  document.querySelectorAll("#profilesSelector .profile-card").forEach((c) => {
    c.classList.toggle("selected", c.dataset.profile === state.activeProfile);
    c.onclick = async () => {
      state.activeProfile = c.dataset.profile;
      await api("/api/settings", "POST", { model_profile: state.activeProfile });
      renderModelRecommendationsUI();
      toast(`Modo seleccionado: ${profileNames[state.activeProfile] || state.activeProfile}`);
    };
  });

  const wizProfEl = document.getElementById("wizProfileSelect");
  if (wizProfEl && ["balanced", "free", "pro", "custom"].includes(state.activeProfile)) {
    wizProfEl.value = state.activeProfile;
    const wWrap = document.getElementById("wizCustomModelWrap");
    if (wWrap) wWrap.style.display = state.activeProfile === "custom" ? "block" : "none";
  }

  document.getElementById("modelWarningsBox").textContent = (recs.warnings || []).join(" · ");

  const filterMode = document.getElementById("modelFilterSelect").value;
  const activeMap = state.activeProfile === "custom"
    ? { ...(recs.profiles.balanced || {}), ...state.stageOverrides }
    : (recs.profiles[state.activeProfile] || {});

  state._stagePools = {};
  const tbody = document.getElementById("stageModelsTableBody");
  tbody.innerHTML = (recs.stages || []).map((st) => {
    const pool = allModels.filter((m) => {
      if (st.requires_vision && !m.supports_vision) return false;
      if (filterMode === "free" && !m.is_free) return false;
      if (filterMode === "vision" && !m.supports_vision) return false;
      return true;
    });
    state._stagePools[st.id] = { pool, selectedKey: activeMap[st.id] || "", requiresVision: !!st.requires_vision };

    const selectedModel = byKey[activeMap[st.id]] || pool.find((x) => x.key === activeMap[st.id]) || null;
    let triggerInner = "";
    if (selectedModel) {
      const priceBadge = selectedModel.is_free
        ? '<span class="badge badge-free">GRATIS</span>'
        : `<span class="badge badge-paid">${esc(selectedModel.free_note || "Pago")}</span>`;
      const visBadge = selectedModel.supports_vision ? '<span class="badge badge-vision">Visión</span>' : "";
      triggerInner = `
        <span class="model-combo-label">[${esc(selectedModel.provider_label)}] ${esc(selectedModel.display_name)}</span>
        <span class="model-combo-meta">${priceBadge}${visBadge}<span class="model-combo-chevron">▾</span></span>
      `;
    } else {
      triggerInner = `
        <span class="model-combo-label" style="color:var(--text-muted);">Conecta arriba un proveedor${st.requires_vision ? " con visión" : ""}</span>
        <span class="model-combo-chevron">▾</span>
      `;
    }

    return `
      <tr>
        <td><strong>${esc(st.name)}</strong><div style="font-size:11.5px; color:var(--text-dim);">${esc(st.role)}</div></td>
        <td>${st.requires_vision ? '<span class="badge badge-vision">Requiere Visión</span>' : '<span class="badge badge-free">Texto rápido</span>'}</td>
        <td class="stage-model-cell">
          <div class="model-combo" id="combo_${esc(st.id)}" data-stage="${esc(st.id)}">
            <button type="button" class="model-combo-trigger" onclick="toggleStageCombo('${esc(st.id)}', event)">
              ${triggerInner}
            </button>
            <div class="model-combo-dropdown" onclick="event.stopPropagation()">
              <div class="model-combo-search-bar">
                <input
                  type="text"
                  id="comboInput_${esc(st.id)}"
                  placeholder="🔎 Escribe para buscar modelo (ej: free-stack, opus, gemini)..."
                  autocomplete="off"
                  oninput="filterStageCombo('${esc(st.id)}', this.value)"
                  onkeydown="handleComboKeydown('${esc(st.id)}', event)"
                />
                <span class="model-combo-count" id="comboCount_${esc(st.id)}">0</span>
              </div>
              <div class="model-combo-list" id="comboList_${esc(st.id)}"></div>
            </div>
          </div>
        </td>
        <td style="font-size:12px; color:var(--text-muted);">${esc(st.reason_hint)}</td>
      </tr>
    `;
  }).join("");

  renderGlobalQuickMatches();
  renderWizardModelSearchResults();
}

function renderStageComboItems(stageId, queryStr) {
  const info = state._stagePools[stageId];
  const listEl = document.getElementById(`comboList_${stageId}`);
  const countEl = document.getElementById(`comboCount_${stageId}`);
  if (!info || !listEl || !countEl) return;

  const filtered = info.pool.filter((m) => modelMatchesQuery(m, queryStr));
  info.filtered = filtered;
  info.focusIdx = filtered.length ? 0 : -1;
  countEl.textContent = `${filtered.length} de ${info.pool.length}`;

  if (!filtered.length) {
    listEl.innerHTML = `<div class="model-combo-empty">Ningún modelo coincide con "${esc(queryStr)}". Prueba con otro término.</div>`;
    return;
  }

  listEl.innerHTML = filtered.map((m, idx) => {
    const isSel = m.key === info.selectedKey;
    const priceBadge = m.is_free
      ? '<span class="badge badge-free">GRATIS</span>'
      : `<span class="badge badge-paid">${esc(m.free_note || "Pago")}</span>`;
    const visBadge = m.supports_vision ? '<span class="badge badge-vision">Visión</span>' : "";
    const subId = m.model_id && m.model_id !== m.display_name ? `<div class="model-combo-item-sub">${esc(m.model_id)}</div>` : "";
    return `
      <div
        class="model-combo-item ${isSel ? "selected" : ""} ${idx === 0 ? "focused" : ""}"
        data-idx="${idx}"
        onclick="overrideStageModel('${esc(stageId)}', '${esc(m.key)}')"
      >
        <div class="model-combo-item-left">
          <div class="model-combo-item-title">${isSel ? "✓ " : ""}[${esc(m.provider_label)}] ${esc(m.display_name)}</div>
          ${subId}
        </div>
        <div class="model-combo-item-right">
          ${priceBadge}
          ${visBadge}
          <button
            type="button"
            class="model-apply-all-btn"
            title="Aplicar este modelo a todas las etapas compatibles"
            onclick="event.stopPropagation(); applyModelToAllStages('${esc(m.key)}')"
          >En todas</button>
        </div>
      </div>
    `;
  }).join("");
}

window.closeAllStageCombos = function () {
  document.querySelectorAll(".model-combo.open").forEach((el) => {
    el.classList.remove("open", "flip-up");
  });
};

window.toggleStageCombo = function (stageId, ev) {
  if (ev) ev.stopPropagation();
  const combo = document.getElementById(`combo_${stageId}`);
  if (!combo) return;
  const wasOpen = combo.classList.contains("open");
  closeAllStageCombos();
  if (wasOpen) return;

  const rect = combo.getBoundingClientRect();
  if (window.innerHeight - rect.bottom < 330 && rect.top > 320) {
    combo.classList.add("flip-up");
  }
  combo.classList.add("open");

  const inp = document.getElementById(`comboInput_${stageId}`);
  const initialQ = state.globalModelQuery || "";
  if (inp) inp.value = initialQ;
  renderStageComboItems(stageId, initialQ);
  if (inp) {
    setTimeout(() => {
      inp.focus();
      inp.select();
    }, 15);
  }
};

window.filterStageCombo = function (stageId, val) {
  renderStageComboItems(stageId, val);
};

window.handleComboKeydown = function (stageId, ev) {
  const info = state._stagePools[stageId];
  if (!info || !info.filtered) return;
  const listEl = document.getElementById(`comboList_${stageId}`);
  const len = info.filtered.length;

  if (ev.key === "Escape") {
    ev.preventDefault();
    closeAllStageCombos();
    return;
  }
  if (!len) return;

  if (ev.key === "ArrowDown") {
    ev.preventDefault();
    info.focusIdx = (info.focusIdx + 1) % len;
  } else if (ev.key === "ArrowUp") {
    ev.preventDefault();
    info.focusIdx = (info.focusIdx - 1 + len) % len;
  } else if (ev.key === "Enter") {
    ev.preventDefault();
    const chosen = info.filtered[Math.max(0, info.focusIdx)];
    if (chosen) overrideStageModel(stageId, chosen.key);
    return;
  } else {
    return;
  }

  if (listEl) {
    listEl.querySelectorAll(".model-combo-item").forEach((row, idx) => {
      const active = idx === info.focusIdx;
      row.classList.toggle("focused", active);
      if (active) row.scrollIntoView({ block: "nearest" });
    });
  }
};

function renderGlobalQuickMatches() {
  const box = document.getElementById("globalQuickSearchMatches");
  if (!box) return;
  const q = (state.globalModelQuery || "").trim();
  const filterMode = document.getElementById("modelFilterSelect")?.value || "all";
  if (!q) {
    box.style.display = "none";
    box.innerHTML = "";
    return;
  }
  const matches = (state.scan?.models || []).filter((m) => {
    if (filterMode === "free" && !m.is_free) return false;
    if (filterMode === "vision" && !m.supports_vision) return false;
    return modelMatchesQuery(m, q);
  });

  box.style.display = "block";
  if (!matches.length) {
    box.innerHTML = `<div class="model-combo-empty" style="background:#090e1a; border:1px solid var(--border); border-radius:9px;">No encontramos modelos que coincidan con "<strong>${esc(q)}</strong>".</div>`;
    return;
  }

  box.innerHTML = `
    <div style="background:#090e1a; border:1px solid rgba(99,102,241,0.4); border-radius:10px; padding:10px 12px;">
      <div style="font-size:11.5px; color:var(--text-muted); margin-bottom:7px;">
        <strong>${matches.length} coincidencia${matches.length === 1 ? "" : "s"}</strong> para "${esc(q)}" — pulsa en un modelo para aplicarlo a todas las etapas compatibles o abre una etapa abajo:
      </div>
      <div style="display:flex; flex-wrap:wrap; gap:7px;">
        ${matches.slice(0, 8).map((m) => `
          <button
            type="button"
            class="btn btn-sm"
            style="background:#111b31; border-color:rgba(99,102,241,0.38);"
            onclick="applyModelToAllStages('${esc(m.key)}')"
          >
            <span>[${esc(m.provider_label)}] ${esc(m.display_name)}</span>
            <span class="badge ${m.is_free ? "badge-free" : "badge-paid"}">${m.is_free ? "GRATIS" : esc(m.free_note || "Pago")}</span>
            ${m.supports_vision ? '<span class="badge badge-vision">Visión</span>' : ""}
            <span style="color:#a5b4fc; font-size:11px;">→ Usar en todas</span>
          </button>
        `).join("")}
      </div>
    </div>
  `;
}

function renderWizardModelSearchResults() {
  const resBox = document.getElementById("wizModelSearchResults");
  const inp = document.getElementById("wizModelSearchInput");
  if (!resBox || !inp) return;
  const q = inp.value.trim();
  const models = (state.scan?.models || []).filter((m) => modelMatchesQuery(m, q));
  if (!models.length) {
    resBox.innerHTML = `<div class="model-combo-empty">Conecta un proveedor arriba o prueba otro nombre.</div>`;
    return;
  }
  resBox.innerHTML = models.slice(0, 25).map((m) => `
    <div class="model-combo-item" onclick="applyModelToAllStages('${esc(m.key)}')">
      <div class="model-combo-item-left">
        <div class="model-combo-item-title">[${esc(m.provider_label)}] ${esc(m.display_name)}</div>
      </div>
      <div class="model-combo-item-right">
        <span class="badge ${m.is_free ? "badge-free" : "badge-paid"}">${m.is_free ? "GRATIS" : esc(m.free_note || "Pago")}</span>
        ${m.supports_vision ? '<span class="badge badge-vision">Visión</span>' : ""}
        <span class="model-apply-all-btn">Seleccionar</span>
      </div>
    </div>
  `).join("");
}

window.overrideStageModel = async function (stageId, modelKey) {
  if (!modelKey) return;
  closeAllStageCombos();
  const baseMap = state.recommendations?.profiles?.[state.activeProfile]
    || state.recommendations?.profiles?.balanced
    || {};
  state.stageOverrides = { ...baseMap, ...state.stageOverrides, [stageId]: modelKey };
  state.activeProfile = "custom";
  try {
    await api("/api/settings", "POST", { model_profile: "custom", stage_models: state.stageOverrides });
    renderModelRecommendationsUI();
    toast("Modelo guardado para esta etapa.");
  } catch (e) {
    toast(e.message);
  }
};

window.applyModelToAllStages = async function (modelKey) {
  if (!modelKey) return;
  closeAllStageCombos();
  const allModels = state.scan?.models || [];
  const chosen = allModels.find((m) => m.key === modelKey);
  if (!chosen) return;

  const baseMap = state.recommendations?.profiles?.balanced || {};
  const nextMap = { ...baseMap, ...state.stageOverrides };
  (state.recommendations?.stages || []).forEach((st) => {
    if (!st.requires_vision || chosen.supports_vision) {
      nextMap[st.id] = modelKey;
    }
  });
  state.stageOverrides = nextMap;
  state.activeProfile = "custom";
  try {
    await api("/api/settings", "POST", { model_profile: "custom", stage_models: state.stageOverrides });
    renderModelRecommendationsUI();
    toast(
      chosen.supports_vision
        ? `¡${chosen.display_name} aplicado a las 9 etapas!`
        : `¡${chosen.display_name} aplicado a etapas de texto (conservando Visión en etapas 4 y 6)!`
    );
  } catch (e) {
    toast(e.message);
  }
};

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("btnRescanModels").addEventListener("click", async () => {
    toast("Actualizando lista de modelos en vivo...");
    await refreshModelScan(true);
    toast("Lista de modelos actualizada.");
  });
  document.getElementById("modelFilterSelect").addEventListener("change", () => renderModelRecommendationsUI());

  const searchInp = document.getElementById("modelSearchInput");
  const clearBtn = document.getElementById("btnClearModelSearch");
  if (searchInp && clearBtn) {
    searchInp.addEventListener("input", () => {
      state.globalModelQuery = searchInp.value;
      clearBtn.style.display = searchInp.value ? "grid" : "none";
      renderGlobalQuickMatches();
      document.querySelectorAll(".model-combo.open").forEach((el) => {
        const stId = el.dataset.stage;
        const cInp = document.getElementById(`comboInput_${stId}`);
        if (cInp) cInp.value = state.globalModelQuery;
        renderStageComboItems(stId, state.globalModelQuery);
      });
    });
    clearBtn.addEventListener("click", () => {
      searchInp.value = "";
      state.globalModelQuery = "";
      clearBtn.style.display = "none";
      renderGlobalQuickMatches();
      searchInp.focus();
    });
  }

  const wizProfSel = document.getElementById("wizProfileSelect");
  const wizWrap = document.getElementById("wizCustomModelWrap");
  const wizSearch = document.getElementById("wizModelSearchInput");
  if (wizProfSel && wizWrap) {
    wizProfSel.addEventListener("change", () => {
      wizWrap.style.display = wizProfSel.value === "custom" ? "block" : "none";
      if (wizProfSel.value === "custom") {
        renderWizardModelSearchResults();
        if (wizSearch) setTimeout(() => wizSearch.focus(), 20);
      }
    });
  }
  if (wizSearch) {
    wizSearch.addEventListener("input", () => renderWizardModelSearchResults());
  }

  document.addEventListener("mousedown", (ev) => {
    if (!ev.target.closest(".model-combo")) {
      closeAllStageCombos();
    }
  });
});

/* ==================== CHANNELS & WIZARD (REPLACES GRILL-ME) ==================== */
function renderChannelsDropdownAndTab(channelsObj) {
  const items = Object.values(channelsObj?.items || {});
  const activeId = channelsObj?.active_default_channel || "";

  const sel = document.getElementById("topChannelSelect");
  const options = [
    `<option value="" ${!activeId ? "selected" : ""}>⚡ Modo libre (Sin canal / Piloto)</option>`,
    ...items.map((c) => (
      `<option value="${esc(c.id)}" ${c.id === activeId ? "selected" : ""}>📺 ${esc(c.name)} (${c.language.toUpperCase()})</option>`
    ))
  ];
  sel.innerHTML = options.join("");
  sel.onchange = async () => {
    if (sel.value) {
      await api(`/api/channels/active/${sel.value}`, "POST");
      toast(`Canal activo: ${sel.options[sel.selectedIndex].text}`);
    } else {
      await api(`/api/channels/active/_clear_`, "POST").catch(() => {});
      toast(`Modo libre seleccionado (Sin canal asignado).`);
    }
    await refreshBootstrap();
  };

  const grid = document.getElementById("channelsListGrid");
  if (!items.length) {
    grid.innerHTML = `
      <div class="card" style="grid-column:1/-1; text-align:center; padding:28px;">
        <h3 style="font-size:16px; margin-bottom:6px;">Todavía no has creado ningún canal</h3>
        <p style="font-size:13px; color:var(--text-muted); margin-bottom:14px;">Configura el nombre, idioma y voz de tu primer canal en menos de un minuto.</p>
        <button class="btn btn-primary" onclick="openWizard(3)">+ Crear mi primer canal</button>
      </div>
    `;
    return;
  }
  grid.innerHTML = items.map((c) => {
    const s = c.sessions || {};
    return `
      <div class="card" style="margin:0;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
          <div>
            <strong style="font-size:15px;">${esc(c.name)}</strong>
            <span class="badge badge-vision" style="margin-left:6px;">${c.language === "en" ? "Inglés" : "Español"} · 62-72 s</span>
          </div>
          <div style="display:flex; gap:6px; align-items:center;">
            ${c.id === activeId ? '<span class="badge badge-free">Canal activo</span>' : `<button class="btn btn-sm" onclick="setActiveChannel('${c.id}')">Usar este canal</button>`}
            <button class="btn btn-sm" onclick="deleteChannel('${c.id}', '${esc(c.name)}')" style="color:#f87171; border-color:rgba(239,68,68,0.3); background:rgba(239,68,68,0.08);" title="Eliminar este canal">🗑️ Borrar</button>
          </div>
        </div>
        <p style="font-size:12.5px; color:var(--text-muted); margin-bottom:10px;">
          Categoría: <strong>${esc(c.group)}</strong> · Narrador: <strong>${esc(c.voice_preference)}</strong>
        </p>
        <div style="display:flex; gap:8px; flex-wrap:wrap;">
          <button class="btn btn-sm" onclick="connectSocial('${c.id}', 'youtube')">
            ${s.youtube ? "✅ YouTube conectado" : "Conectar YouTube"}
          </button>
          <button class="btn btn-sm" onclick="connectSocial('${c.id}', 'tiktok')">
            ${s.tiktok ? "✅ TikTok conectado" : "Conectar TikTok"}
          </button>
          <button class="btn btn-sm" onclick="connectSocial('${c.id}', 'instagram')">
            ${s.instagram ? "✅ Instagram conectado" : "Conectar Instagram"}
          </button>
        </div>
      </div>
    `;
  }).join("");
}

window.openWizard = openWizard;

window.setActiveChannel = async function (cid) {
  await api(`/api/channels/active/${cid}`, "POST");
  await refreshBootstrap();
  toast("Canal activo actualizado.");
};

window.deleteChannel = async function (cid, name) {
  if (!confirm(`¿Estás seguro de que deseas eliminar el canal "${name}"?\nEsta acción no se puede deshacer.`)) return;
  try {
    const res = await api(`/api/channels/${cid}`, "DELETE");
    if (res.ok) {
      toast(`Canal "${name}" eliminado correctamente.`);
      await refreshBootstrap();
    } else {
      toast("No se pudo eliminar el canal.");
    }
  } catch (err) {
    toast(`Error: ${err.message || err}`);
  }
};

window.connectSocial = async function (channelId, platform) {
  const names = { youtube: "YouTube", tiktok: "TikTok", instagram: "Instagram" };
  toast(`Abriendo navegador para conectar ${names[platform] || platform}...`);
  await api("/api/social/connect", "POST", { channel_id: channelId, platform });
  const poll = setInterval(async () => {
    const st = await api(`/api/social/status/${channelId}`);
    if (!st.pending[platform]) {
      clearInterval(poll);
      if (st.sessions[platform]) {
        toast(`¡Cuenta de ${names[platform] || platform} vinculada correctamente!`);
        const wEl = document.getElementById(`wizStatus_${platform}`);
        if (wEl) wEl.innerHTML = `<span style="color:#6ee7b7; font-weight:700;">✅ Cuenta conectada</span>`;
        refreshBootstrap();
      }
    }
  }, 2000);
};

function openWizard(step = 1) {
  state.wizardStep = step;
  document.getElementById("wizardBackdrop").classList.add("open");
  updateWizardStepUI();
}

function updateWizardStepUI() {
  const s = state.wizardStep;
  document.querySelectorAll(".wiz-pane").forEach((p) => {
    p.style.display = Number(p.dataset.wpane) === s ? "block" : "none";
  });
  document.querySelectorAll(".step-pill").forEach((pill) => {
    const n = Number(pill.dataset.wstep);
    pill.classList.toggle("active", n === s);
    pill.classList.toggle("done", n < s);
  });
  document.getElementById("btnWizardPrev").style.display = s > 1 ? "inline-flex" : "none";
  document.getElementById("btnWizardNext").textContent = s === 4 ? "Finalizar y abrir el Estudio" : "Continuar →";
}

function renderWizardHardware(hw, stock, legacy) {
  const wrap = document.getElementById("wizHardwareSummary");
  const gpuLabel = hw.video_encoder === "h264_nvenc"
    ? `⚡ ${hw.gpu_name} (Aceleración GPU)`
    : `${hw.gpu_name || "Procesador"}`;
  const stockActive = stock.has_pixabay || stock.has_pexels;

  wrap.innerHTML = `
    <div class="card" style="margin:0; padding:13px 15px;">
      <div style="font-size:11.5px; color:var(--text-muted);">Tarjeta gráfica</div>
      <div style="font-weight:700; font-size:13px; margin-top:4px; color:#6ee7b7;">${esc(gpuLabel)}</div>
    </div>
    <div class="card" style="margin:0; padding:13px 15px;">
      <div style="font-size:11.5px; color:var(--text-muted);">Motor de video integrado</div>
      <div style="font-weight:700; font-size:13px; margin-top:4px;">${hw.ffmpeg_ok ? "✅ Incluido y listo sin Internet" : "⚠️ Revisando componentes"}</div>
    </div>
    <div class="card" style="margin:0; padding:13px 15px;">
      <div style="font-size:11.5px; color:var(--text-muted);">Espacio libre y escenas</div>
      <div style="font-weight:700; font-size:13px; margin-top:4px;">${hw.disk_free_gb || 0} GB libres · ${stockActive ? "✅ Escenas activas" : "Pendiente conectar"}</div>
    </div>
  `;

  // Clean, human Legacy Import Banner (never says "0 canal(es)" or raw dev paths!)
  const banner = document.getElementById("legacyImportBanner");
  const hasAnyChannels = Object.keys(state.bootstrap?.channels?.items || {}).length > 0;
  if (legacy?.has_legacy && (!hasAnyChannels || !stockActive)) {
    banner.style.display = "block";
    let msg = "";
    if (legacy.channels_count > 0 && legacy.has_stock_keys) {
      msg = `Detectamos ${legacy.channels_count === 1 ? "1 canal guardado" : `${legacy.channels_count} canales guardados`} y tus claves de escenas listas en este equipo. ¿Deseas cargarlos automáticamente?`;
    } else if (legacy.channels_count > 0) {
      msg = `Detectamos ${legacy.channels_count === 1 ? "1 canal configurado" : `${legacy.channels_count} canales configurados`} previamente en este equipo. Impórtalos con un clic.`;
    } else {
      msg = "Detectamos tus claves gratuitas de Pixabay / Pexels ya guardadas en este equipo. Cárgalas con un clic para no volver a pegarlas.";
    }
    document.getElementById("legacyImportText").textContent = msg;
  } else {
    banner.style.display = "none";
  }
}

function renderWizardVoices() {
  const lang = document.getElementById("wizLangSelect").value;
  const voices = (state.bootstrap?.voices || []).filter((v) => v.lang === lang);
  if (!voices.some((v) => v.id === state.selectedVoice) && voices[0]) {
    state.selectedVoice = voices[0].id;
  }
  const grid = document.getElementById("wizVoicesGrid");
  grid.innerHTML = voices.map((v) => `
    <div class="voice-card ${v.id === state.selectedVoice ? "selected" : ""}" onclick="selectWizardVoice('${v.id}')">
      <div>
        <div style="font-size:13px; font-weight:700;">${esc(v.name)}</div>
        <div style="font-size:11px; color:var(--text-muted);">${esc(v.tone)}</div>
      </div>
      <button type="button" class="btn btn-xs" onclick="event.stopPropagation(); playVoiceSample('${v.id}', this)">▶ Escuchar</button>
    </div>
  `).join("");
}

window.selectWizardVoice = function (vid) {
  state.selectedVoice = vid;
  renderWizardVoices();
};

window.playVoiceSample = function (voiceId, btnEl) {
  const player = document.getElementById("voiceAudioPlayer");
  const oldTxt = btnEl.textContent;
  btnEl.textContent = "🔊 Sonando...";
  player.src = `/api/voices/sample/${encodeURIComponent(voiceId)}`;
  player.onended = () => { btnEl.textContent = oldTxt; };
  player.onerror = () => { btnEl.textContent = oldTxt; toast("No se pudo reproducir la muestra de voz."); };
  player.play().catch(() => { btnEl.textContent = oldTxt; });
};

function updateSubtitleSimulator() {
  const style = document.getElementById("wizSubStyle").value;
  const colorName = document.getElementById("wizSubColor").value;
  const hex = { yellow: "#FFEB3B", cyan: "#00E5FF", green: "#00E676" }[colorName] || "#FFEB3B";
  const box = document.getElementById("phoneSubPreview");
  if (style === "hybrid") {
    box.innerHTML = `NADIE <span style="background:${hex}; color:#000; padding:1px 6px; border-radius:5px; text-shadow:none;">IMAGINÓ</span> ESTO`;
  } else {
    box.innerHTML = `EL <span style="color:${hex};">SECRETO</span> OCULTO`;
  }
}

function bindWizardControls() {
  document.getElementById("btnOpenWizard").addEventListener("click", () => openWizard(1));
  document.getElementById("btnNewChannelWizard").addEventListener("click", () => openWizard(3));
  document.getElementById("wizLangSelect").addEventListener("change", renderWizardVoices);
  document.getElementById("wizSubStyle").addEventListener("change", updateSubtitleSimulator);
  document.getElementById("wizSubColor").addEventListener("change", updateSubtitleSimulator);

  document.getElementById("btnWizOpenPixabay").addEventListener("click", () => openExternalUrl("https://pixabay.com/api/docs/"));
  document.getElementById("btnWizOpenPexels").addEventListener("click", () => openExternalUrl("https://www.pexels.com/api/"));

  document.getElementById("btnImportLegacyNow").addEventListener("click", async () => {
    const legacyInfo = state.bootstrap?.legacy_cli || {};
    const res = await api("/api/import-legacy", "POST");
    if (res.imported) {
      await refreshBootstrap();
      document.getElementById("legacyImportBanner").style.display = "none";
      if ((legacyInfo.channels_count || 0) > 0) {
        toast("Canales y claves importados. Ahora conecta o revisa tu proveedor de IA.");
        state.wizardStep = 2;
        updateWizardStepUI();
      } else {
        document.getElementById("wizStockMsg").textContent = "✅ Claves de escenas importadas y listas.";
        toast("Claves de escenas importadas correctamente.");
      }
    }
  });

  document.getElementById("btnWizTestStock").addEventListener("click", async () => {
    const pix = document.getElementById("wizPixabayInput").value.trim();
    const pex = document.getElementById("wizPexelsInput").value.trim();
    const msgEl = document.getElementById("wizStockMsg");
    if (!pix && !pex) {
      msgEl.textContent = "Pega al menos una clave de Pixabay o Pexels primero.";
      return;
    }
    msgEl.textContent = "Comprobando clave...";
    const res = await api("/api/stock/save", "POST", { pixabay_key: pix, pexels_key: pex });
    msgEl.textContent = res.validation.pixabay.message || res.validation.pexels.message || "Claves guardadas.";
    await refreshBootstrap();
  });

  document.getElementById("btnSuggestNichesAI").addEventListener("click", async () => {
    const btn = document.getElementById("btnSuggestNichesAI");
    btn.disabled = true;
    btn.textContent = "Analizando temáticas...";
    try {
      const res = await api("/api/ai/suggest-niches", "POST", {
        language: document.getElementById("wizLangSelect").value,
        purpose: document.getElementById("wizPurposeSelect").value,
      });
      const box = document.getElementById("wizNicheSuggestions");
      box.style.display = "grid";
      box.innerHTML = (res.suggestions || []).map((s) => `
        <div class="profile-card" style="padding:11px 13px;" onclick='applyNicheSuggestion(${JSON.stringify(s).replace(/'/g, "&#39;")})'>
          <div class="profile-top">
            <strong style="font-size:13.5px;">${esc(s.name)}</strong>
            <span class="badge badge-free">${esc(s.rpm_tier)}</span>
          </div>
          <p style="font-size:11.5px; color:#c7d2fe; margin:4px 0;">${esc(s.niche)}</p>
          <p style="font-size:11px; color:var(--text-muted); line-height:1.35;">${esc(s.reason)}</p>
        </div>
      `).join("");
    } finally {
      btn.disabled = false;
      btn.textContent = "✨ Recomendar 3 temáticas rentables";
    }
  });

  document.querySelectorAll(".wiz-social-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!state.savedWizardChannelId) {
        await saveChannelFromWizard();
      }
      connectSocial(state.savedWizardChannelId, btn.dataset.platform);
    });
  });

  document.getElementById("btnWizardSkip").addEventListener("click", async () => {
    await api("/api/settings", "POST", { wizard_completed: true });
    document.getElementById("wizardBackdrop").classList.remove("open");
  });

  document.getElementById("btnWizardPrev").addEventListener("click", () => {
    if (state.wizardStep > 1) {
      state.wizardStep -= 1;
      updateWizardStepUI();
    }
  });

  document.getElementById("btnWizardNext").addEventListener("click", async () => {
    if (state.wizardStep === 2) {
      const prof = document.getElementById("wizProfileSelect").value;
      state.activeProfile = prof;
      await api("/api/settings", "POST", { model_profile: prof });
    } else if (state.wizardStep === 3) {
      await saveChannelFromWizard();
    } else if (state.wizardStep === 4) {
      await saveChannelFromWizard();
      await api("/api/settings", "POST", { wizard_completed: true });
      document.getElementById("wizardBackdrop").classList.remove("open");
      await refreshBootstrap();
      toast("¡Configuración completada! Ya puedes crear tu primer video.");
      return;
    }
    state.wizardStep += 1;
    updateWizardStepUI();
  });
}

window.applyNicheSuggestion = function (s) {
  document.getElementById("wizChannelName").value = s.name || "";
  document.getElementById("wizChannelGroup").value = s.group_slug || "";
  document.getElementById("wizChannelNiche").value = s.niche || "";
  if (s.voice_id) {
    state.selectedVoice = s.voice_id;
    renderWizardVoices();
  }
  toast(`Temática "${s.name}" aplicada.`);
};

async function saveChannelFromWizard() {
  const platforms = [];
  ["youtube", "tiktok", "instagram"].forEach((p) => {
    const txt = document.getElementById(`wizStatus_${p}`)?.textContent || "";
    if (txt.includes("✅")) platforms.push(p === "youtube" ? "youtube_shorts" : (p === "instagram" ? "instagram_reels" : "tiktok"));
  });
  const res = await api("/api/channels", "POST", {
    channel_id: state.savedWizardChannelId,
    name: document.getElementById("wizChannelName").value.trim() || "Mi Canal",
    group: document.getElementById("wizChannelGroup").value.trim(),
    language: document.getElementById("wizLangSelect").value,
    niche: document.getElementById("wizChannelNiche").value.trim() || "Curiosidades",
    purpose: document.getElementById("wizPurposeSelect").value,
    voice_preference: state.selectedVoice,
    subtitle_style: document.getElementById("wizSubStyle").value,
    subtitle_color: document.getElementById("wizSubColor").value,
    platforms,
    schedule_mode: document.getElementById("wizScheduleMode").value,
    schedule_time: document.getElementById("wizScheduleTime").value || "19:00",
    set_default: true,
  });
  state.savedWizardChannelId = res.channel_id;
}

/* ==================== LIVE PRODUCTION STUDIO ==================== */
function syncProdModeUI(mode) {
  state.productionMode = mode || "auto";
  document.querySelectorAll("#prodModeSwitch .mode-pill").forEach((b) => {
    b.classList.toggle("active", b.dataset.mode === state.productionMode);
  });
}

function renderPipelineStagesIdle() {
  const grid = document.getElementById("stagesGrid");
  grid.innerHTML = state.defaultStages.map((s) => `
    <div class="stage-card">
      <div class="stage-top">
        <span class="stage-name">${esc(s.name)}</span>
        <span class="stage-timer">—</span>
      </div>
      <div class="stage-model">${esc(s.role)}</div>
      <div class="stage-summary">Listo para iniciar</div>
    </div>
  `).join("");
}

function bindStudioControls() {
  document.querySelectorAll("#prodModeSwitch .mode-pill").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const m = btn.dataset.mode;
      syncProdModeUI(m);
      await api("/api/settings", "POST", { production_mode: m });
      toast(m === "copilot"
        ? "Modo Copiloto: podrás revisar el guión y elegir la foto antes del montaje."
        : "Modo Automático: el video se creará de principio a fin sin pausas.");
    });
  });

  document.getElementById("btnStartProduction").addEventListener("click", async () => {
    const chId = document.getElementById("topChannelSelect").value || null;
    const topic = document.getElementById("customTopicInput").value.trim() || null;
    const demo = document.getElementById("demoModeCheck").checked || !chId;

    try {
      const res = await api("/api/pipeline/start", "POST", {
        channel_id: chId,
        custom_topic: topic,
        mode: state.productionMode,
        demo_mode: demo,
      });
      if (!res.ok) {
        toast(res.error || "No se pudo iniciar la creación del video.");
        return;
      }
      toast("¡Creación en marcha! Puedes seguir cada etapa en vivo aquí abajo.");
      pollPipeline();
    } catch (e) {
      toast(e.message);
    }
  });
}

function ensureLiveStopwatchTicker() {
  if (state._liveStopwatchTimer) return;
  state._liveStopwatchTimer = setInterval(updateLiveStopwatch, 100);
}

function updateLiveStopwatch() {
  const st = state._livePipeline;
  if (!st || !st.active) return;
  const isRunning = (st.status === "running" || st.status === "awaiting_copilot");
  const deltaSec = isRunning ? Math.max(0, (performance.now() - (state._livePipelineReceived || performance.now())) / 1000) : 0;
  const totalElapsed = (st.total_elapsed_sec || 0) + deltaSec;

  const statusLabels = {
    running: "En progreso",
    awaiting_copilot: "Esperando tu confirmación",
    completed: "Completado",
    error: "Detenido por aviso",
  };

  const timerEl = document.getElementById("pipelineTotalTimer");
  if (timerEl) {
    timerEl.textContent = `Tiempo total: ${totalElapsed.toFixed(1)} s · ${statusLabels[st.status] || st.status}`;
  }

  if (st.stages && Array.isArray(st.stages)) {
    for (const s of st.stages) {
      const stageTimerEl = document.getElementById(`stageTimer_${s.id}`);
      if (!stageTimerEl) continue;
      if (s.status === "running") {
        const sElapsed = (s.elapsed_sec || 0) + deltaSec;
        stageTimerEl.textContent = `${sElapsed.toFixed(1)} s`;
      } else if (s.status === "done") {
        stageTimerEl.textContent = `${s.elapsed_sec || 0} s`;
      } else if (s.status === "waiting_user") {
        stageTimerEl.textContent = "Pausado";
      } else {
        stageTimerEl.textContent = "—";
      }
    }
  }
}

function pollPipeline() {
  clearInterval(state.pipelineTimer);
  ensureLiveStopwatchTicker();
  state.pipelineTimer = setInterval(async () => {
    try {
      const st = await api("/api/pipeline/state");
      if (!st.active) {
        clearInterval(state.pipelineTimer);
        clearInterval(state._liveStopwatchTimer);
        state._liveStopwatchTimer = null;
        return;
      }
      state._livePipeline = st;
      state._livePipelineReceived = performance.now();
      renderLivePipeline(st);
      updateLiveStopwatch();
      if (st.status === "completed" || st.status === "error") {
        clearInterval(state.pipelineTimer);
        clearInterval(state._liveStopwatchTimer);
        state._liveStopwatchTimer = null;
        updateLiveStopwatch();
        refreshGallery();
        refreshBootstrap();
      }
    } catch (_) {}
  }, 1000);
}

function updatePreviewImageOnce(wrapId, filePath, versionTag, altText) {
  const wrap = document.getElementById(wrapId);
  if (!wrap || !filePath) return;
  const cacheKey = `${filePath}::${versionTag || ""}`;
  if (wrap.dataset.renderedKey === cacheKey) return;
  wrap.dataset.renderedKey = cacheKey;

  const url = `/api/media?path=${encodeURIComponent(filePath)}&v=${encodeURIComponent(versionTag || "1")}`;
  const existingImg = wrap.querySelector("img");
  if (existingImg) {
    const pre = new Image();
    pre.onload = () => { existingImg.src = url; };
    pre.src = url;
  } else {
    wrap.innerHTML = `<img src="${url}" alt="${esc(altText)}" />`;
  }
}

function renderLivePipeline(st) {
  state._livePipeline = st;
  state._livePipelineReceived = performance.now();
  ensureLiveStopwatchTicker();

  // Reset preview keys when a brand-new run starts
  if (st.run_id && state._lastPreviewRunId !== st.run_id) {
    state._lastPreviewRunId = st.run_id;
    ["prevTrendWrap", "prevScriptWrap", "prevSeoWrap", "prevThumbWrap", "prevFinalWrap"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) {
        delete el.dataset.renderedKey;
        el.innerHTML = (id === "prevFinalWrap" || id === "prevThumbWrap") ? "Se mostrará al finalizar" : "Se mostrará al iniciar";
        el.className = "preview-empty";
      }
    });
  }

  const statusLabels = {
    running: "En progreso",
    awaiting_copilot: "Esperando tu confirmación",
    completed: "Completado",
    error: "Detenido por aviso",
  };
  document.getElementById("pipelineTotalTimer").textContent =
    `Tiempo total: ${(st.total_elapsed_sec || 0).toFixed(1)} s · ${statusLabels[st.status] || st.status}`;

  const stageStatusMap = {
    pending: "En cola",
    running: "Trabajando...",
    waiting_user: "Esperando tu revisión",
    done: "Completado",
    skipped: "Omitido",
    error: "Revisar aviso",
  };

  const grid = document.getElementById("stagesGrid");
  const stageKey = (st.stages || []).map(s => `${s.id}:${s.name}:${s.status}:${s.summary || ""}:${s.model_key || ""}`).join("|");
  if (grid.dataset.renderedKey !== stageKey) {
    grid.dataset.renderedKey = stageKey;
    grid.innerHTML = (st.stages || []).map((s) => `
      <div class="stage-card ${esc(s.status)}" id="stageCard_${esc(s.id)}">
        <div class="stage-top">
          <span class="stage-name">${esc(s.name)}</span>
          <span class="stage-timer" id="stageTimer_${esc(s.id)}">${s.elapsed_sec ? `${s.elapsed_sec} s` : (s.status === "running" ? "En curso..." : "—")}</span>
        </div>
        <div class="stage-model" title="${esc(s.model_key)}">${esc(s.model_key ? s.model_key.replace("::", " · ") : s.role)}</div>
        <div class="stage-summary">${esc(s.summary || stageStatusMap[s.status] || s.status)}</div>
      </div>
    `).join("");
  }

  const p = st.previews || {};
  const s5Ver = st.stages?.[4]?.elapsed_sec || "1";
  const s7Ver = st.stages?.[6]?.elapsed_sec || "1";

  // Box 1: Tendencia seleccionada
  const trendWrap = document.getElementById("prevTrendWrap");
  if (trendWrap) {
    const tb = p.trend_brief || {};
    const topic = tb.selected_topic || st.topic || "";
    if (topic) {
      const angle = tb.viral_angle || "Verificado";
      const entity = tb.real_subject_entity || "";
      const why = tb.why_viral || "";
      const tKey = `${topic}::${angle}::${entity}`;
      if (trendWrap.dataset.renderedKey !== tKey) {
        trendWrap.dataset.renderedKey = tKey;
        trendWrap.className = "";
        trendWrap.innerHTML = `
          <div class="preview-scroll-content">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
              <span class="badge badge-paid">🔥 Tendencia</span>
              <span style="font-size:10.5px; color:#6ee7b7;">Aprobada</span>
            </div>
            <div style="font-weight:700; color:#fff; font-size:12.5px; margin-bottom:6px;">${esc(topic)}</div>
            <div style="font-size:11px; color:#94a3b8; margin-bottom:4px;"><strong>Ángulo:</strong> ${esc(angle)}</div>
            ${entity ? `<div style="font-size:11px; color:#94a3b8; margin-bottom:4px;"><strong>Entidad real:</strong> ${esc(entity)}</div>` : ""}
            ${why ? `<div style="font-size:10.5px; color:#a5b4fc; margin-top:6px; font-style:italic; border-top:1px dashed rgba(255,255,255,0.1); padding-top:4px;">💡 ${esc(why)}</div>` : ""}
          </div>
        `;
      }
    }
  }

  // Box 2: Guión Viral
  const scriptWrap = document.getElementById("prevScriptWrap");
  if (scriptWrap) {
    const scData = p.script_data || {};
    const fullScript = scData.full_script || (st.copilot_data?.script?.full_script) || "";
    if (fullScript) {
      const words = fullScript.trim().split(/\s+/).length;
      const sKey = `${fullScript.length}::${words}`;
      if (scriptWrap.dataset.renderedKey !== sKey) {
        scriptWrap.dataset.renderedKey = sKey;
        scriptWrap.className = "";
        scriptWrap.innerHTML = `
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
            <span class="badge badge-free">${words} palabras · 62-72s</span>
            <button class="btn btn-sm" style="padding:2px 8px; font-size:10.5px;" onclick="copyDirectText(${JSON.stringify(fullScript)}, 'Guión viral copiado al portapapeles')">📋 Copiar</button>
          </div>
          <div class="preview-scroll-content" style="white-space:pre-wrap;">${esc(fullScript)}</div>
        `;
      }
    }
  }

  // Box 3: Título, Descripción y Tags
  const seoWrap = document.getElementById("prevSeoWrap");
  if (seoWrap) {
    const meta = p.viral_metadata || {};
    const title = meta.primary_title || "";
    if (title) {
      const desc = meta.description || "";
      const pinned = meta.pinned_comment || "";
      const tags = (meta.tags || []).join(" #");
      const packText = `${title}\n\n${desc}\n\nComentario fijado:\n${pinned}\n\nEtiquetas:\n#${tags}`;
      const mKey = `${title}::${tags}`;
      if (seoWrap.dataset.renderedKey !== mKey) {
        seoWrap.dataset.renderedKey = mKey;
        seoWrap.className = "";
        seoWrap.innerHTML = `
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
            <span class="badge badge-vision">Pack SEO</span>
            <button class="btn btn-primary btn-sm" style="padding:2px 8px; font-size:10.5px;" onclick="copyDirectText(${JSON.stringify(packText)}, 'Pack SEO copiado al portapapeles')">📋 Copiar</button>
          </div>
          <div class="preview-scroll-content">
            <div style="font-weight:700; color:#38bdf8; margin-bottom:4px; font-size:12px;">${esc(title)}</div>
            <div style="color:#e2e8f0; margin-bottom:6px; font-size:11px;">${esc(desc)}</div>
            ${pinned ? `<div style="color:#fcd34d; margin-bottom:6px; font-size:11px; background:rgba(245,158,11,0.08); padding:4px 6px; border-radius:4px;"><strong>📌 Comentario:</strong> ${esc(pinned)}</div>` : ""}
            ${tags ? `<div style="color:#a78bfa; font-size:10.5px;">#${esc(tags)}</div>` : ""}
          </div>
        `;
      }
    }
  }

  // Box 4: Portada viral (Miniatura con clic para ver en grande)
  const thumbWrap = document.getElementById("prevThumbWrap");
  if (thumbWrap && p.thumbnail) {
    const thumbUrl = `/api/media?path=${encodeURIComponent(p.thumbnail)}&v=${encodeURIComponent(s7Ver)}`;
    const tKey = `${p.thumbnail}::${s7Ver}`;
    if (thumbWrap.dataset.renderedKey !== tKey) {
      thumbWrap.dataset.renderedKey = tKey;
      thumbWrap.className = "";
      thumbWrap.innerHTML = `
        <div class="preview-thumb-container" onclick="openImageLightbox('${esc(thumbUrl)}', 'Portada viral (Alta resolución)')" title="Haz clic para ver la miniatura en grande">
          <img src="${thumbUrl}" alt="Portada viral (Miniatura)" />
          <div class="preview-thumb-badge">🔍 Clic para ver en grande</div>
        </div>
      `;
    }
  }

  // Box 5: Video terminado (Se muestra ÚNICAMENTE tras la portada para preservar el orden 1->2->3->4->5)
  const finalWrap = document.getElementById("prevFinalWrap");
  const stage7Done = (st.stages || []).find((s) => s.name?.includes("Portada") || s.id === "thumbnail-designer")?.status === "done";
  const canShowVideo = p.final_video && (Boolean(p.thumbnail) || stage7Done || st.status === "completed");
  if (finalWrap && canShowVideo) {
    const finalKey = `${p.final_video}::${s5Ver}::${p.thumbnail || ""}::${s7Ver}::${p.publication_folder || ""}`;
    if (finalWrap.dataset.renderedKey !== finalKey) {
      finalWrap.dataset.renderedKey = finalKey;
      finalWrap.className = "";
      const vidUrl = `/api/media?path=${encodeURIComponent(p.final_video)}&v=${encodeURIComponent(s5Ver)}`;
      const thumbUrl = p.thumbnail ? `/api/media?path=${encodeURIComponent(p.thumbnail)}&v=${encodeURIComponent(s7Ver)}` : "";
      finalWrap.innerHTML = `
        <video src="${vidUrl}" controls poster="${thumbUrl}"></video>
        ${p.publication_folder ? `<button class="btn btn-sm" style="margin-top:8px; width:100%;" onclick="openFolder('${esc(p.publication_folder.replace(/\\/g, "\\\\"))}')">📂 Ver en carpeta</button>` : ""}
      `;
    }
  }

  // Copilot Interactive Approval Gate
  const copCard = document.getElementById("copilotCard");
  if (st.status === "awaiting_copilot" && st.copilot_gate === "script") {
    copCard.style.display = "block";
    const sc = st.copilot_data?.script?.full_script || "";
    if (copCard.dataset.renderedKey !== "script") {
      copCard.dataset.renderedKey = "script";
      document.getElementById("copilotTitle").textContent = "🎛️ Revisa o edita el guión antes de grabar la narración";
      document.getElementById("copilotBody").innerHTML = `
        <textarea id="copilotScriptBox" rows="5" style="margin-bottom:10px;">${esc(sc)}</textarea>
        <button class="btn btn-emerald" onclick="approveCopilotScript()">Aprobar guión y continuar</button>
      `;
    }
  } else if (st.status === "awaiting_copilot" && st.copilot_gate === "visuals") {
    copCard.style.display = "block";
    const cands = st.copilot_data?.candidates || [];
    const rec = st.copilot_data?.recommended_candidate || 1;
    const currentKey = `visuals::${rec}::${cands.join("|")}`;
    if (copCard.dataset.renderedKey !== currentKey) {
      copCard.dataset.renderedKey = currentKey;
      document.getElementById("copilotTitle").textContent = `🎛️ Elige la foto real para los primeros 4 segundos (Recomendada: Opción #${rec})`;
      document.getElementById("copilotBody").innerHTML = `
        <div class="grid-4" style="margin-bottom:10px;">
          ${cands.map((cp, idx) => `
            <div class="preview-box" style="cursor:pointer; border-color:${idx + 1 === rec ? "var(--emerald)" : "var(--border)"};" onclick="approveCopilotPhoto(${idx + 1})">
              <strong>Opción #${idx + 1} ${idx + 1 === rec ? "⭐ Recomendada" : ""}</strong>
              <img src="${mediaUrl(cp)}" alt="Candidata ${idx + 1}" />
            </div>
          `).join("")}
        </div>
      `;
    }
  } else {
    copCard.style.display = "none";
    copCard.dataset.renderedKey = "";
    document.getElementById("copilotBody").innerHTML = "";
  }
}

window.approveCopilotScript = async function () {
  const txt = document.getElementById("copilotScriptBox").value;
  await api("/api/pipeline/copilot", "POST", { full_script: txt });
  toast("Guión confirmado. Buscando fotografías reales y preparando títulos...");
};

window.approveCopilotPhoto = async function (idx) {
  await api("/api/pipeline/copilot", "POST", { selected_candidate: idx });
  toast(`Fotografía #${idx} elegida. Montando el video en tu tarjeta gráfica...`);
};

/* ==================== GALLERY & 30-DAY PROTECTION ==================== */
function populateGalleryChannelFilter(vids, cools) {
  const filterSel = document.getElementById("galleryChannelFilter");
  if (!filterSel) return;
  const currentVal = filterSel.value;
  const counts = {};
  vids.forEach((v) => {
    const ch = v.channel || "⚡ Modo libre / Piloto";
    counts[ch] = (counts[ch] || 0) + 1;
  });

  // Also include channels that exist in cooldown or channels config even if 0 videos
  (cools || []).forEach((c) => {
    const ch = c.channel || c.group || "⚡ Modo libre / Piloto";
    if (counts[ch] === undefined) {
      counts[ch] = 0;
    }
  });
  (state.bootstrap?.channels || []).forEach((c) => {
    const ch = c.name || c.id;
    if (counts[ch] === undefined) {
      counts[ch] = 0;
    }
  });

  let html = `<option value="">📺 Todos los canales (${vids.length})</option>`;
  Object.keys(counts).sort().forEach((ch) => {
    html += `<option value="${esc(ch)}">${esc(ch)} (${counts[ch]})</option>`;
  });
  filterSel.innerHTML = html;
  if (currentVal && counts[currentVal] !== undefined) {
    filterSel.value = currentVal;
  }
}

function renderFilteredGallery() {
  const vGrid = document.getElementById("galleryVideosGrid");
  const filterSel = document.getElementById("galleryChannelFilter");
  const selectedChannel = filterSel ? filterSel.value : "";
  const allVids = window._galleryVideos || [];
  const allCools = window._galleryCooldown || [];

  // 1. Filter videos grid
  const filteredVids = selectedChannel
    ? allVids.filter((v) => (v.channel || "⚡ Modo libre / Piloto") === selectedChannel)
    : allVids;

  if (!filteredVids.length) {
    vGrid.innerHTML = `
      <div class="card" style="grid-column:1/-1; color:var(--text-muted); text-align:center; padding:26px;">
        ${allVids.length ? `No hay videos terminados para el canal "<strong>${esc(selectedChannel)}</strong>".` : `Todavía no tienes videos terminados en tu biblioteca. Ve a <strong>Crear Videos</strong> para producir el primero.`}
      </div>
    `;
  } else {
    vGrid.innerHTML = filteredVids.map((v) => {
      const origIdx = allVids.indexOf(v);
      return `
      <div class="card" style="margin:0;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
          <span class="badge badge-vision">${esc(v.channel)}</span>
          <span style="font-size:11.5px; color:#6ee7b7;">${v.duration_sec ? `${v.duration_sec} s` : "62-72 s"}</span>
        </div>
        ${v.video_path ? `<video src="${mediaUrl(v.video_path)}" controls poster="${v.thumbnail_path ? mediaUrl(v.thumbnail_path) : ""}" style="width:100%; max-height:280px; border-radius:8px; background:#000;"></video>` : ""}
        <div style="font-size:13px; font-weight:700; margin:8px 0;">${esc(v.slug)}</div>
        <div style="display:flex; gap:8px; flex-wrap:wrap;">
          <button class="btn btn-primary btn-sm" onclick="copyPack(${origIdx >= 0 ? origIdx : 0})">Copiar título y texto</button>
          ${v.thumbnail_path ? `<button class="btn btn-sm" onclick="openImageLightbox('${mediaUrl(v.thumbnail_path)}', 'Portada: ${esc(v.slug)}')">🔍 Miniatura</button>` : ""}
          <button class="btn btn-sm" onclick="openFolder('${esc(v.folder.replace(/\\/g, "\\\\"))}')">Abrir carpeta</button>
          <button class="btn btn-sm" onclick="deleteVideo('${esc(v.folder.replace(/\\/g, "\\\\"))}', '${esc(v.slug)}')" style="color:#f87171; border-color:rgba(239,68,68,0.3); background:rgba(239,68,68,0.08);" title="Eliminar este video de la biblioteca">🗑️ Borrar</button>
        </div>
      </div>
    `;
    }).join("");
  }

  // 2. Filter 30-day cooldown table with the exact same channel filter!
  const cBody = document.getElementById("cooldownTableBody");
  if (cBody) {
    const filteredCools = selectedChannel
      ? allCools.filter((c) => {
          const ch = c.channel || c.group || "";
          return ch === selectedChannel || (selectedChannel === "⚡ Modo libre / Piloto" && (!ch || ch === "piloto_demo"));
        })
      : allCools;

    cBody.innerHTML = filteredCools.length
      ? filteredCools.map((c) => `
          <tr>
            <td><strong>${esc(c.group || c.channel || "—")}</strong></td>
            <td>${esc(c.channel || c.group || "—")}</td>
            <td>${esc(c.topic)}</td>
            <td><span class="badge badge-paid">Protegido por ${c.days_remaining} días más</span></td>
            <td style="text-align:right;">
              <button class="btn btn-sm" style="padding:2px 8px; font-size:11px; color:#f87171; border-color:rgba(239,68,68,0.3); background:rgba(239,68,68,0.06);" onclick="unblockTopic('${esc(c.topic.replace(/'/g, "\\'"))}')" title="Desbloquear este tema para volver a usarlo">✕ Liberar</button>
            </td>
          </tr>
        `).join("")
      : `<tr><td colspan="5" style="color:var(--text-dim); text-align:center; padding:18px;">${selectedChannel ? `No hay temas protegidos para el canal "<strong>${esc(selectedChannel)}</strong>".` : "Aún no hay temas registrados en el historial de los últimos 30 días."}</td></tr>`;
  }
}

async function refreshGallery() {
  const res = await api("/api/gallery");
  renderCacheBar(res.cache);

  window._galleryVideos = res.videos || [];
  window._galleryCooldown = res.cooldown_active || [];
  populateGalleryChannelFilter(window._galleryVideos, window._galleryCooldown);
  renderFilteredGallery();
}

window.unblockTopic = async function (topic) {
  if (!confirm(`¿Deseas desbloquear el tema "${topic}" de la protección de 30 días?`)) return;
  try {
    const res = await api(`/api/gallery/cooldown?topic=${encodeURIComponent(topic)}`, "DELETE");
    if (res.ok) {
      toast(`Tema "${topic}" desbloqueado correctamente.`);
      await refreshGallery();
    } else {
      toast("No se pudo desbloquear el tema.");
    }
  } catch (err) {
    toast(`Error al desbloquear: ${err.message || err}`);
  }
};

window.purgeOrphanCooldowns = async function () {
  try {
    const res = await api("/api/gallery/cooldown?all_orphans=true", "DELETE");
    if (res.ok) {
      toast(`Se liberaron ${res.removed} temas huérfanos.`);
      await refreshGallery();
    } else {
      toast("No se pudieron purgar los temas huérfanos.");
    }
  } catch (err) {
    toast(`Error: ${err.message || err}`);
  }
};

window.copyPack = function (idx) {
  const v = (window._galleryVideos || [])[idx];
  if (v && v.copy_text) {
    navigator.clipboard.writeText(v.copy_text);
    toast("Título, descripción, primer comentario y etiquetas copiados al portapapeles.");
  }
};

window.deleteVideo = async function (folder, slug) {
  if (!confirm(`¿Estás seguro de que deseas eliminar el video "${slug}"?\nSe borrarán sus archivos y se liberará el tema de la lista de 30 días.`)) return;
  try {
    const res = await api(`/api/gallery?folder=${encodeURIComponent(folder)}`, "DELETE");
    if (res.ok) {
      toast(`Video "${slug}" eliminado correctamente.`);
      await refreshGallery();
      await refreshBootstrap();
    } else {
      toast("No se pudo eliminar el video.");
    }
  } catch (err) {
    toast(`Error: ${err.message || err}`);
  }
};

window.openFolder = function (folderPath) {
  api("/api/system/open-folder", "POST", { target: folderPath });
};

window.openImageLightbox = function (src, title) {
  const bd = document.getElementById("imageLightboxBackdrop");
  const img = document.getElementById("lightboxImg");
  const t = document.getElementById("lightboxTitle");
  if (!bd || !img) return;
  img.src = src;
  if (t && title) t.textContent = title;
  bd.classList.add("open");
};

window.closeImageLightbox = function (e) {
  if (e && e.target && e.target.id === "lightboxImg") return;
  const bd = document.getElementById("imageLightboxBackdrop");
  if (bd) bd.classList.remove("open");
};

window.copyDirectText = function (text, msg) {
  if (text) {
    navigator.clipboard.writeText(text);
    toast(msg || "Copiado al portapapeles.");
  }
};

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("btnRefreshGallery").addEventListener("click", refreshGallery);
  const chFilter = document.getElementById("galleryChannelFilter");
  if (chFilter) {
    chFilter.addEventListener("change", renderFilteredGallery);
  }
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeImageLightbox();
    }
  });
  initApp();
});
