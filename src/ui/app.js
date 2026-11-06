/* VideoStudio Pro — End-User Native Desktop Controller */
const state = {
  bootstrap: null,
  scan: null,
  recommendations: null,
  activeProfile: "balanced",
  productionMode: "auto",
  stageOverrides: {},
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
  document.getElementById("sidebarCacheText").textContent = `${cache.used_mb} / ${cache.cap_mb} MB`;
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
    cta.textContent = `Actualizar a v${u.latest_version} en 1 clic`;
    cta.disabled = false;
  } else if (u.status === "downloading") {
    dot.classList.add("update");
    txt.textContent = `Descargando: ${u.progress_percent}% (${u.speed_mbps} MB/s)`;
    cta.style.display = "inline-flex";
    cta.textContent = `${u.progress_percent}%`;
    cta.disabled = true;
  } else if (u.status === "ready_to_install") {
    dot.classList.add("update");
    txt.textContent = `Actualización lista`;
    cta.style.display = "inline-flex";
    cta.textContent = `Instalar y reiniciar ahora`;
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

function renderModelRecommendationsUI() {
  const scan = state.scan || { free_models_count: 0, paid_models_count: 0, vision_models_count: 0, models: [] };
  const recs = state.recommendations || { stages: [], profiles: { free: {}, balanced: {}, pro: {} }, estimated_cost_usd_per_video: {}, warnings: [] };

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

  document.getElementById("modelWarningsBox").textContent = (recs.warnings || []).join(" · ");

  const filterMode = document.getElementById("modelFilterSelect").value;
  const activeMap = state.activeProfile === "custom"
    ? { ...(recs.profiles.balanced || {}), ...state.stageOverrides }
    : (recs.profiles[state.activeProfile] || {});

  const tbody = document.getElementById("stageModelsTableBody");
  tbody.innerHTML = (recs.stages || []).map((st) => {
    const pool = (scan.models || []).filter((m) => {
      if (st.requires_vision && !m.supports_vision) return false;
      if (filterMode === "free" && !m.is_free) return false;
      if (filterMode === "vision" && !m.supports_vision) return false;
      return true;
    });
    const selectedKey = activeMap[st.id] || "";
    const opts = pool.length
      ? pool.map((m) => {
          const priceTag = m.is_free ? "GRATIS" : m.free_note;
          const visTag = m.supports_vision ? " · Con Visión" : "";
          return `<option value="${esc(m.key)}" ${m.key === selectedKey ? "selected" : ""}>[${esc(m.provider_label)}] ${esc(m.display_name)} — ${priceTag}${visTag}</option>`;
        }).join("")
      : `<option value="">Conecta arriba un proveedor${st.requires_vision ? " con visión" : ""}</option>`;

    return `
      <tr>
        <td><strong>${esc(st.name)}</strong><div style="font-size:11.5px; color:var(--text-dim);">${esc(st.role)}</div></td>
        <td>${st.requires_vision ? '<span class="badge badge-vision">Requiere Visión</span>' : '<span class="badge badge-free">Texto rápido</span>'}</td>
        <td>
          <select onchange="overrideStageModel('${st.id}', this.value)">${opts}</select>
        </td>
        <td style="font-size:12px; color:var(--text-muted);">${esc(st.reason_hint)}</td>
      </tr>
    `;
  }).join("");
}

window.overrideStageModel = async function (stageId, modelKey) {
  if (!modelKey) return;
  const baseMap = state.recommendations?.profiles?.[state.activeProfile] || {};
  state.stageOverrides = { ...baseMap, ...state.stageOverrides, [stageId]: modelKey };
  state.activeProfile = "custom";
  try {
    await api("/api/settings", "POST", { model_profile: "custom", stage_models: state.stageOverrides });
    renderModelRecommendationsUI();
    toast("Modelo personalizado guardado.");
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
});

/* ==================== CHANNELS & WIZARD (REPLACES GRILL-ME) ==================== */
function renderChannelsDropdownAndTab(channelsObj) {
  const items = Object.values(channelsObj?.items || {});
  const activeId = channelsObj?.active_default_channel || "";

  const sel = document.getElementById("topChannelSelect");
  if (!items.length) {
    sel.innerHTML = `<option value="">Canal de prueba (Local)</option>`;
  } else {
    sel.innerHTML = items.map((c) => (
      `<option value="${esc(c.id)}" ${c.id === activeId ? "selected" : ""}>${esc(c.name)} (${c.language.toUpperCase()})</option>`
    )).join("");
  }
  sel.onchange = async () => {
    if (sel.value) {
      await api(`/api/channels/active/${sel.value}`, "POST");
      toast(`Canal seleccionado: ${sel.options[sel.selectedIndex].text}`);
    }
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
          ${c.id === activeId ? '<span class="badge badge-free">Canal activo</span>' : `<button class="btn btn-sm" onclick="setActiveChannel('${c.id}')">Usar este canal</button>`}
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

function pollPipeline() {
  clearInterval(state.pipelineTimer);
  state.pipelineTimer = setInterval(async () => {
    try {
      const st = await api("/api/pipeline/state");
      if (!st.active) return;
      renderLivePipeline(st);
      if (st.status === "completed" || st.status === "error") {
        clearInterval(state.pipelineTimer);
        refreshGallery();
        refreshBootstrap();
      }
    } catch (_) {}
  }, 1100);
}

function renderLivePipeline(st) {
  const statusLabels = {
    running: "En progreso",
    awaiting_copilot: "Esperando tu confirmación",
    completed: "Completado",
    error: "Detenido por aviso",
  };
  document.getElementById("pipelineTotalTimer").textContent =
    `Tiempo total: ${st.total_elapsed_sec || 0} s · ${statusLabels[st.status] || st.status}`;

  const stageStatusMap = {
    pending: "En cola",
    running: "Trabajando...",
    waiting_user: "Esperando tu revisión",
    done: "Completado",
    skipped: "Omitido",
    error: "Revisar aviso",
  };

  const grid = document.getElementById("stagesGrid");
  grid.innerHTML = (st.stages || []).map((s) => `
    <div class="stage-card ${esc(s.status)}">
      <div class="stage-top">
        <span class="stage-name">${esc(s.name)}</span>
        <span class="stage-timer">${s.elapsed_sec ? `${s.elapsed_sec} s` : (s.status === "running" ? "En curso..." : "—")}</span>
      </div>
      <div class="stage-model" title="${esc(s.model_key)}">${esc(s.model_key ? s.model_key.replace("::", " · ") : s.role)}</div>
      <div class="stage-summary">${esc(s.summary || stageStatusMap[s.status] || s.status)}</div>
    </div>
  `).join("");

  const p = st.previews || {};
  if (p.candidates_grid) {
    document.getElementById("prevGridWrap").innerHTML = `<img src="${mediaUrl(p.candidates_grid)}" alt="Fotos reales candidatas" />`;
  }
  if (p.mosaico_clips) {
    document.getElementById("prevMosaicWrap").innerHTML = `<img src="${mediaUrl(p.mosaico_clips)}" alt="Escenas de apoyo" />`;
  }
  if (p.qa_strip) {
    document.getElementById("prevQaWrap").innerHTML = `<img src="${mediaUrl(p.qa_strip)}" alt="Revisión de calidad" />`;
  }
  if (p.final_video) {
    document.getElementById("prevFinalWrap").innerHTML = `
      <video src="${mediaUrl(p.final_video)}" controls poster="${p.thumbnail ? mediaUrl(p.thumbnail) : ""}"></video>
      ${p.publication_folder ? `<button class="btn btn-sm" style="margin-top:8px;" onclick="openFolder('${esc(p.publication_folder.replace(/\\/g, "\\\\"))}')">📂 Ver en carpeta</button>` : ""}
    `;
  }

  // Copilot Interactive Approval Gate
  const copCard = document.getElementById("copilotCard");
  if (st.status === "awaiting_copilot" && st.copilot_gate === "script") {
    copCard.style.display = "block";
    const sc = st.copilot_data?.script?.full_script || "";
    if (!document.getElementById("copilotScriptBox")) {
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
  } else {
    copCard.style.display = "none";
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
async function refreshGallery() {
  const res = await api("/api/gallery");
  renderCacheBar(res.cache);

  const vGrid = document.getElementById("galleryVideosGrid");
  const vids = res.videos || [];
  if (!vids.length) {
    vGrid.innerHTML = `
      <div class="card" style="grid-column:1/-1; color:var(--text-muted); text-align:center; padding:26px;">
        Todavía no tienes videos terminados en tu biblioteca. Ve a <strong>Crear Videos</strong> para producir el primero.
      </div>
    `;
  } else {
    vGrid.innerHTML = vids.map((v, idx) => `
      <div class="card" style="margin:0;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
          <span class="badge badge-vision">${esc(v.channel)}</span>
          <span style="font-size:11.5px; color:#6ee7b7;">${v.duration_sec ? `${v.duration_sec} s` : "62-72 s"}</span>
        </div>
        ${v.video_path ? `<video src="${mediaUrl(v.video_path)}" controls poster="${v.thumbnail_path ? mediaUrl(v.thumbnail_path) : ""}" style="width:100%; max-height:280px; border-radius:8px; background:#000;"></video>` : ""}
        <div style="font-size:13px; font-weight:700; margin:8px 0;">${esc(v.slug)}</div>
        <div style="display:flex; gap:8px;">
          <button class="btn btn-primary btn-sm" onclick="copyPack(${idx})">Copiar título y descripción</button>
          <button class="btn btn-sm" onclick="openFolder('${esc(v.folder.replace(/\\/g, "\\\\"))}')">Abrir carpeta</button>
        </div>
      </div>
    `).join("");
    window._galleryVideos = vids;
  }

  const cBody = document.getElementById("cooldownTableBody");
  const cools = res.cooldown_active || [];
  cBody.innerHTML = cools.length
    ? cools.map((c) => `
        <tr>
          <td><strong>${esc(c.group)}</strong></td>
          <td>${esc(c.channel)}</td>
          <td>${esc(c.topic)}</td>
          <td><span class="badge badge-paid">Protegido por ${c.days_remaining} días más</span></td>
        </tr>
      `).join("")
    : `<tr><td colspan="4" style="color:var(--text-dim);">Aún no hay temas registrados en el historial de los últimos 30 días.</td></tr>`;
}

window.copyPack = function (idx) {
  const v = (window._galleryVideos || [])[idx];
  if (v && v.copy_text) {
    navigator.clipboard.writeText(v.copy_text);
    toast("Título, descripción, primer comentario y etiquetas copiados al portapapeles.");
  }
};

window.openFolder = function (folderPath) {
  api("/api/system/open-folder", "POST", { target: folderPath });
};

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("btnRefreshGallery").addEventListener("click", refreshGallery);
  initApp();
});
