/* VideoStudio Pro — Modern Reactive Desktop Controller */
const state = {
  bootstrap: null,
  scan: null,
  recommendations: null,
  activeProfile: "balanced",
  stageOverrides: {},
  wizardStep: 1,
  selectedVoice: "es-MX-JorgeNeural",
  savedWizardChannelId: null,
  pipelineTimer: null,
  updaterTimer: null,
  defaultStages: [
    { id: "trend-researcher", name: "1. Trend Researcher", role: "Tendencias + Cooldown 30d" },
    { id: "viral-scriptwriter", name: "2. Viral Scriptwriter", role: "Guión 5 Compases (62-72s)" },
    { id: "viral-copywriter", name: "3. Viral Copywriter", role: "Rama Paralela SEO & CTR" },
    { id: "visual-asset-reviewer", name: "4. Visual Asset Reviewer", role: "Rama Paralela Grid 2x2 + Visión" },
    { id: "video-renderer", name: "5. Video Renderer (GPU)", role: "FFmpeg Directo NVENC ~20s" },
    { id: "video-qa-validator", name: "6. Video QA Validator", role: "Tira QA 5 Fotogramas + Visión" },
    { id: "thumbnail-designer", name: "7. Thumbnail Designer", role: "Foto Real + Badge 74px" },
    { id: "packaging-archiver", name: "8. Packaging Archiver", role: "Historial 30d + LRU 1.5 GB" },
    { id: "social-media-publisher", name: "9. Social Publisher", role: "Sesiones Multi-Red Aisladas" },
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
    throw new Error(data.detail || data.error || `HTTP ${res.status}`);
  }
  return data;
}

function toast(msg) {
  const el = document.getElementById("toastBox");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(window._toastTimeout);
  window._toastTimeout = setTimeout(() => el.classList.remove("show"), 3600);
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
  state.stageOverrides = data.settings.stage_models || {};

  // Top bar version & GPU
  document.getElementById("topVersionBadge").textContent = `v${data.version.version}`;
  const hw = data.hardware || {};
  const gpuBadge = document.getElementById("gpuTopBadge");
  if (hw.video_encoder === "h264_nvenc") {
    gpuBadge.textContent = `⚡ ${hw.gpu_name.replace("NVIDIA GeForce ", "")} · NVENC`;
  } else {
    gpuBadge.textContent = `⚙️ ${hw.video_encoder || "CPU"} · ${hw.cpu_cores || 4} Cores`;
  }

  document.getElementById("prodModeSelect").value = data.settings.production_mode || "auto";
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
    toast(`Caché limpiada: ${res.freed_mb} MB liberados.`);
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
    txt.textContent = `Nueva v${u.latest_version} (${u.asset_size_mb} MB)`;
    cta.style.display = "inline-flex";
    cta.textContent = `🚀 Actualizar a v${u.latest_version} en 1 Clic`;
    cta.disabled = false;
  } else if (u.status === "downloading") {
    dot.classList.add("update");
    txt.textContent = `Descargando actualización: ${u.progress_percent}% (${u.speed_mbps} MB/s)`;
    cta.style.display = "inline-flex";
    cta.textContent = `⏳ ${u.progress_percent}%`;
    cta.disabled = true;
  } else if (u.status === "ready_to_install") {
    dot.classList.add("update");
    txt.textContent = `Actualización verificada lista`;
    cta.style.display = "inline-flex";
    cta.textContent = `⚡ Instalar y Reiniciar Ahora`;
    cta.disabled = false;
  } else if (u.status === "repo_pending") {
    dot.classList.add("pending");
    txt.textContent = u.message || `v${u.current_version} · Repo Git pendiente`;
  } else {
    txt.textContent = u.message || `v${u.current_version} · Actualizado`;
  }
}

function bindSettingsAndUpdater() {
  document.getElementById("btnCheckUpdates").addEventListener("click", async () => {
    document.getElementById("updaterText").textContent = "Buscando en GitHub...";
    const u = await api("/api/updater/check", "POST");
    renderUpdaterBar(u);
    toast(u.message || "Comprobación completada.");
  });

  document.getElementById("btnOneClickUpdate").addEventListener("click", async () => {
    const cur = await api("/api/updater/status");
    if (cur.status === "ready_to_install") {
      toast("Lanzando instalador de actualización...");
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
        toast("¡Descarga verificada! Iniciando instalación automática...");
        await api("/api/updater/install", "POST");
      } else if (st.status === "error") {
        clearInterval(state.updaterTimer);
        toast(st.error || "Error en descarga.");
      }
    }, 650);
  });

  document.getElementById("btnSaveGitRepo").addEventListener("click", async () => {
    const repo = document.getElementById("settingsGithubRepo").value.trim();
    await api("/api/settings", "POST", { github_repo: repo });
    const u = await api("/api/updater/check", "POST");
    renderUpdaterBar(u);
    toast("Repositorio Git guardado y verificado.");
  });

  document.getElementById("btnSaveStockSettings").addEventListener("click", async () => {
    const pix = document.getElementById("settingsPixabayKey").value.trim();
    const pex = document.getElementById("settingsPexelsKey").value.trim();
    const res = await api("/api/stock/save", "POST", { pixabay_key: pix, pexels_key: pex });
    toast(res.validation.pixabay.message || res.validation.pexels.message || "Configuración de Stock guardada.");
  });

  document.getElementById("btnGetPixabayKey").addEventListener("click", () => {
    api("/api/system/open-url", "POST", { target: "https://pixabay.com/api/docs/" });
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
      const connectedBadge = scanInfo.connected
        ? `<span class="badge badge-free">✅ Activo (${scanInfo.free_count || 0} Gratis / ${scanInfo.paid_count || 0} Pagos)</span>`
        : `<span class="badge" style="background:rgba(255,255,255,0.06); color:var(--text-muted);">${p.has_api_key ? "Listo" : "Sin clave"}</span>`;
      const showUrl = p.id === "omnirouter" || p.id === "local";
      return `
        <div class="card" style="margin-bottom:0; padding:${compact ? "12px" : "15px"};">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
            <strong>${esc(p.label)}</strong>
            ${connectedBadge}
          </div>
          <p style="font-size:11.5px; color:var(--text-muted); margin-bottom:9px;">${esc(p.notes)}</p>
          ${showUrl ? `
            <label class="field-label">Endpoint Base URL</label>
            <input type="text" id="${containerId}_url_${p.id}" value="${esc(p.base_url)}" style="margin-bottom:8px;" />
          ` : ""}
          ${p.id !== "local" ? `
            <div style="display:flex; gap:8px;">
              <input type="password" id="${containerId}_key_${p.id}" placeholder="${p.masked_key ? `Guardada (${p.masked_key})` : "Pega tu API Key..."}" />
              <button class="btn btn-primary btn-sm" onclick="saveProvider('${p.id}', '${containerId}')">Conectar</button>
            </div>
          ` : `
            <button class="btn btn-sm" onclick="saveProvider('${p.id}', '${containerId}')">Probar Conexión Local</button>
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
  const apiKey = keyEl && keyEl.value.trim() ? keyEl.value.trim() : "KEEP_EXISTING";
  const baseUrl = urlEl ? urlEl.value.trim() : null;
  toast(`Conectando y escaneando ${providerId}...`);
  const res = await api("/api/ai/providers", "POST", {
    provider_id: providerId,
    api_key: apiKey,
    base_url: baseUrl,
    enabled: true,
  });
  state.scan = res.scan;
  state.recommendations = res.recommendations;
  const provs = await api("/api/ai/providers");
  renderProvidersCards(provs.providers);
  renderModelRecommendationsUI();
  toast(`${res.provider.label}: ${res.scan.free_models_count} modelos GRATIS y ${res.scan.paid_models_count} PAGOS detectados.`);
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

  const badgeTxt = `🟢 ${scan.free_models_count} GRATIS · 💎 ${scan.paid_models_count} PAGOS · 👁️ ${scan.vision_models_count} VISIÓN`;
  document.getElementById("scanCountersBadge").textContent = badgeTxt;
  document.getElementById("wizModelCountBadge").textContent = badgeTxt;

  const costs = recs.estimated_cost_usd_per_video || {};
  document.getElementById("costFree").textContent = `$${(costs.free || 0).toFixed(3)} / video`;
  document.getElementById("costBalanced").textContent = `~$${(costs.balanced || 0).toFixed(3)} / video`;
  document.getElementById("costPro").textContent = `~$${(costs.pro || 0).toFixed(3)} / video`;

  document.querySelectorAll("#profilesSelector .profile-card").forEach((c) => {
    c.classList.toggle("selected", c.dataset.profile === state.activeProfile);
    c.onclick = async () => {
      state.activeProfile = c.dataset.profile;
      await api("/api/settings", "POST", { model_profile: state.activeProfile });
      renderModelRecommendationsUI();
      toast(`Perfil IA cambiado a: ${state.activeProfile.toUpperCase()}`);
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
          const priceTag = m.is_free ? "🟢 GRATIS" : `💎 ${m.free_note}`;
          const visTag = m.supports_vision ? " · 👁️ VISIÓN" : "";
          return `<option value="${esc(m.key)}" ${m.key === selectedKey ? "selected" : ""}>[${esc(m.provider_label)}] ${esc(m.display_name)} — ${priceTag}${visTag}</option>`;
        }).join("")
      : `<option value="">Conecta una IA ${st.requires_vision ? "con VISIÓN " : ""}arriba</option>`;

    return `
      <tr>
        <td><strong>${esc(st.name)}</strong><div style="font-size:11px; color:var(--text-dim);">${esc(st.role)}</div></td>
        <td>${st.requires_vision ? '<span class="badge badge-vision">👁️ Exige Visión</span>' : '<span class="badge badge-free">⚡ Texto / JSON</span>'}</td>
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
    toast(`Modelo actualizado para ${stageId}`);
  } catch (e) {
    toast(e.message);
  }
};

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("btnRescanModels").addEventListener("click", () => refreshModelScan(true));
  document.getElementById("modelFilterSelect").addEventListener("change", () => renderModelRecommendationsUI());
});

/* ==================== CHANNELS & WIZARD (REPLACES GRILL-ME) ==================== */
function renderChannelsDropdownAndTab(channelsObj) {
  const items = Object.values(channelsObj?.items || {});
  const activeId = channelsObj?.active_default_channel || "";

  const sel = document.getElementById("topChannelSelect");
  if (!items.length) {
    sel.innerHTML = `<option value="">Modo Piloto Demo</option>`;
  } else {
    sel.innerHTML = items.map((c) => (
      `<option value="${esc(c.id)}" ${c.id === activeId ? "selected" : ""}>📺 ${esc(c.name)} (${c.language.toUpperCase()})</option>`
    )).join("");
  }
  sel.onchange = async () => {
    if (sel.value) {
      await api(`/api/channels/active/${sel.value}`, "POST");
      toast(`Canal activo: ${sel.options[sel.selectedIndex].text}`);
    }
  };

  const grid = document.getElementById("channelsListGrid");
  if (!items.length) {
    grid.innerHTML = `<div class="card">No tienes canales guardados aún. Usa el botón <strong>+ Crear Canal en el Wizard</strong>.</div>`;
    return;
  }
  grid.innerHTML = items.map((c) => {
    const s = c.sessions || {};
    return `
      <div class="card">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
          <div>
            <strong style="font-size:15px;">${esc(c.name)}</strong>
            <span class="badge badge-vision" style="margin-left:6px;">${c.language.toUpperCase()} · 62-72s</span>
          </div>
          ${c.id === activeId ? '<span class="badge badge-free">Activo</span>' : `<button class="btn btn-sm" onclick="setActiveChannel('${c.id}')">Activar</button>`}
        </div>
        <p style="font-size:12.5px; color:var(--text-muted); margin-bottom:8px;">
          Grupo Cooldown 30d: <code>${esc(c.group)}</code> · Voz: <code>${esc(c.voice_preference)}</code>
        </p>
        <div style="display:flex; gap:8px; flex-wrap:wrap; margin-top:10px;">
          <button class="btn btn-sm" onclick="connectSocial('${c.id}', 'youtube')">
            ${s.youtube ? "✅ YouTube Conectado" : "🔗 Conectar YouTube"}
          </button>
          <button class="btn btn-sm" onclick="connectSocial('${c.id}', 'tiktok')">
            ${s.tiktok ? "✅ TikTok Conectado" : "🔗 Conectar TikTok"}
          </button>
          <button class="btn btn-sm" onclick="connectSocial('${c.id}', 'instagram')">
            ${s.instagram ? "✅ Instagram Conectado" : "🔗 Conectar Instagram"}
          </button>
        </div>
      </div>
    `;
  }).join("");
}

window.setActiveChannel = async function (cid) {
  await api(`/api/channels/active/${cid}`, "POST");
  await refreshBootstrap();
  toast("Canal predeterminado cambiado.");
};

window.connectSocial = async function (channelId, platform) {
  toast(`Abriendo Chrome limpio para iniciar sesión en ${platform}...`);
  await api("/api/social/connect", "POST", { channel_id: channelId, platform });
  const poll = setInterval(async () => {
    const st = await api(`/api/social/status/${channelId}`);
    if (!st.pending[platform]) {
      clearInterval(poll);
      if (st.sessions[platform]) {
        toast(`✅ ¡Sesión de ${platform} guardada y aislada para ${channelId}!`);
        const wEl = document.getElementById(`wizStatus_${platform}`);
        if (wEl) wEl.innerHTML = `<span style="color:#6ee7b7; font-weight:700;">✅ Sesión guardada</span>`;
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
  document.getElementById("btnWizardNext").textContent = s === 4 ? "🚀 Finalizar y Entrar al Estudio" : "Siguiente Paso →";
}

function renderWizardHardware(hw, stock, legacy) {
  const wrap = document.getElementById("wizHardwareSummary");
  wrap.innerHTML = `
    <div class="card" style="margin:0;">
      <div style="font-size:12px; color:var(--text-muted);">Aceleración de Video</div>
      <div style="font-weight:700; margin-top:4px; color:#6ee7b7;">⚡ ${esc(hw.gpu_name || "CPU")} (${esc(hw.video_encoder)})</div>
    </div>
    <div class="card" style="margin:0;">
      <div style="font-size:12px; color:var(--text-muted);">Motor Multimedia Offline</div>
      <div style="font-weight:700; margin-top:4px;">${hw.ffmpeg_ok ? "✅ FFmpeg + libass Listo" : "⚠️ FFmpeg pendiente"}</div>
    </div>
    <div class="card" style="margin:0;">
      <div style="font-size:12px; color:var(--text-muted);">Espacio Libre & Stock</div>
      <div style="font-weight:700; margin-top:4px;">💾 ${hw.disk_free_gb || 0} GB · ${stock.has_pixabay || stock.has_pexels ? "✅ Stock Activo" : "Falta API Stock"}</div>
    </div>
  `;

  const banner = document.getElementById("legacyImportBanner");
  const hasAnyChannels = Object.keys(state.bootstrap?.channels?.items || {}).length > 0;
  if (legacy?.has_legacy && !hasAnyChannels) {
    banner.style.display = "block";
    document.getElementById("legacyImportText").textContent =
      `Encontramos ${legacy.channels_count} canal(es) y claves de Stock en ${legacy.source}. ¿Quieres importarlos sin volver a escribirlos?`;
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
      <button type="button" class="btn btn-sm" onclick="event.stopPropagation(); playVoiceSample('${v.id}', this)">▶ Oír</button>
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
  btnEl.textContent = "🔊...";
  player.src = `/api/voices/sample/${encodeURIComponent(voiceId)}`;
  player.onended = () => { btnEl.textContent = oldTxt; };
  player.onerror = () => { btnEl.textContent = oldTxt; toast("Error sintetizando muestra de voz."); };
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

  document.getElementById("btnWizOpenPixabay").addEventListener("click", () => {
    api("/api/system/open-url", "POST", { target: "https://pixabay.com/api/docs/" });
  });

  document.getElementById("btnImportLegacyNow").addEventListener("click", async () => {
    const res = await api("/api/import-legacy", "POST");
    if (res.imported) {
      await api("/api/settings", "POST", { wizard_completed: true });
      await refreshBootstrap();
      toast("¡Canales, sesiones y claves importadas con éxito!");
      document.getElementById("wizardBackdrop").classList.remove("open");
    }
  });

  document.getElementById("btnWizTestStock").addEventListener("click", async () => {
    const pix = document.getElementById("wizPixabayInput").value.trim();
    const pex = document.getElementById("wizPexelsInput").value.trim();
    const msgEl = document.getElementById("wizStockMsg");
    msgEl.textContent = "Verificando conexión...";
    const res = await api("/api/stock/save", "POST", { pixabay_key: pix, pexels_key: pex });
    msgEl.textContent = res.validation.pixabay.message || res.validation.pexels.message || "Guardado.";
  });

  document.getElementById("btnSuggestNichesAI").addEventListener("click", async () => {
    const btn = document.getElementById("btnSuggestNichesAI");
    btn.disabled = true;
    btn.textContent = "⏳ Analizando mercado...";
    try {
      const res = await api("/api/ai/suggest-niches", "POST", {
        language: document.getElementById("wizLangSelect").value,
        purpose: document.getElementById("wizPurposeSelect").value,
      });
      const box = document.getElementById("wizNicheSuggestions");
      box.style.display = "grid";
      box.innerHTML = (res.suggestions || []).map((s) => `
        <div class="profile-card" onclick='applyNicheSuggestion(${JSON.stringify(s).replace(/'/g, "&#39;")})'>
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <strong>${esc(s.name)}</strong>
            <span class="badge badge-free">${esc(s.rpm_tier)}</span>
          </div>
          <p style="font-size:11.5px; color:#c7d2fe; margin:5px 0;">${esc(s.niche)}</p>
          <p style="font-size:11px; color:var(--text-muted);">${esc(s.reason)}</p>
        </div>
      `).join("");
    } finally {
      btn.disabled = false;
      btn.textContent = "✨ Sugerir 3 Nichos Rentables con IA";
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
      toast("🎉 ¡Todo listo! Ya puedes producir tu primer video viral.");
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
  toast(`Plantilla '${s.name}' cargada.`);
};

async function saveChannelFromWizard() {
  const platforms = [];
  ["youtube", "tiktok", "instagram"].forEach((p) => {
    const txt = document.getElementById(`wizStatus_${p}`)?.textContent || "";
    if (txt.includes("✅")) platforms.push(p === "youtube" ? "youtube_shorts" : (p === "instagram" ? "instagram_reels" : "tiktok"));
  });
  const res = await api("/api/channels", "POST", {
    channel_id: state.savedWizardChannelId,
    name: document.getElementById("wizChannelName").value.trim() || "Mi Canal Viral",
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

/* ==================== LIVE 9-SUBAGENT PRODUCTION STUDIO ==================== */
function renderPipelineStagesIdle() {
  const grid = document.getElementById("stagesGrid");
  grid.innerHTML = state.defaultStages.map((s) => `
    <div class="stage-card">
      <div class="stage-top">
        <span class="stage-name">${esc(s.name)}</span>
        <span class="stage-timer">0.0s</span>
      </div>
      <div class="stage-model">${esc(s.role)}</div>
      <div class="stage-summary">En espera</div>
    </div>
  `).join("");
}

function bindStudioControls() {
  document.getElementById("prodModeSelect").addEventListener("change", async (e) => {
    await api("/api/settings", "POST", { production_mode: e.target.value });
  });

  document.getElementById("btnStartProduction").addEventListener("click", async () => {
    const chId = document.getElementById("topChannelSelect").value || null;
    const topic = document.getElementById("customTopicInput").value.trim() || null;
    const mode = document.getElementById("prodModeSelect").value;
    const demo = document.getElementById("demoModeCheck").checked || !chId;

    try {
      const res = await api("/api/pipeline/start", "POST", {
        channel_id: chId,
        custom_topic: topic,
        mode,
        demo_mode: demo,
      });
      if (!res.ok) {
        toast(res.error || "No se pudo iniciar la producción.");
        return;
      }
      toast("🎬 ¡Producción iniciada! Observa los 9 subagentes en tiempo real.");
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
  document.getElementById("pipelineTotalTimer").textContent = `Δt Total: ${st.total_elapsed_sec || 0}s · Estado: ${st.status.toUpperCase()}`;

  const grid = document.getElementById("stagesGrid");
  grid.innerHTML = (st.stages || []).map((s) => `
    <div class="stage-card ${esc(s.status)}">
      <div class="stage-top">
        <span class="stage-name">${esc(s.name)}</span>
        <span class="stage-timer">${s.elapsed_sec ? `${s.elapsed_sec}s` : (s.status === "running" ? "⏳..." : "")}</span>
      </div>
      <div class="stage-model" title="${esc(s.model_key)}">🤖 ${esc(s.model_key || s.role)}</div>
      <div class="stage-summary">${esc(s.summary || s.status)}</div>
    </div>
  `).join("");

  // Previews
  const p = st.previews || {};
  if (p.candidates_grid) {
    document.getElementById("prevGridWrap").innerHTML = `<img src="${mediaUrl(p.candidates_grid)}" alt="Grid 2x2" />`;
  }
  if (p.mosaico_clips) {
    document.getElementById("prevMosaicWrap").innerHTML = `<img src="${mediaUrl(p.mosaico_clips)}" alt="Mosaico" />`;
  }
  if (p.qa_strip) {
    document.getElementById("prevQaWrap").innerHTML = `<img src="${mediaUrl(p.qa_strip)}" alt="Tira QA" />`;
  }
  if (p.final_video) {
    document.getElementById("prevFinalWrap").innerHTML = `
      <video src="${mediaUrl(p.final_video)}" controls poster="${p.thumbnail ? mediaUrl(p.thumbnail) : ""}"></video>
      ${p.publication_folder ? `<button class="btn btn-sm" style="margin-top:6px;" onclick="openFolder('${esc(p.publication_folder.replace(/\\/g, "\\\\"))}')">📂 Abrir Carpeta</button>` : ""}
    `;
  }

  // Copilot Interactive Approval Gate
  const copCard = document.getElementById("copilotCard");
  if (st.status === "awaiting_copilot" && st.copilot_gate === "script") {
    copCard.style.display = "block";
    const sc = st.copilot_data?.script?.full_script || "";
    if (!document.getElementById("copilotScriptBox")) {
      document.getElementById("copilotTitle").textContent = "🎛️ Copiloto: Revisa o retoca el guión antes de generar audio y video";
      document.getElementById("copilotBody").innerHTML = `
        <textarea id="copilotScriptBox" rows="5" style="margin-bottom:10px;">${esc(sc)}</textarea>
        <button class="btn btn-emerald" onclick="approveCopilotScript()">✅ Aprobar Guión y Continuar</button>
      `;
    }
  } else if (st.status === "awaiting_copilot" && st.copilot_gate === "visuals") {
    copCard.style.display = "block";
    const cands = st.copilot_data?.candidates || [];
    const rec = st.copilot_data?.recommended_candidate || 1;
    document.getElementById("copilotTitle").textContent = `🎛️ Copiloto: Elige la foto real para el Hook 0-4s (IA recomienda #${rec})`;
    document.getElementById("copilotBody").innerHTML = `
      <div class="grid-4" style="margin-bottom:10px;">
        ${cands.map((cp, idx) => `
          <div class="preview-box" style="cursor:pointer; border-color:${idx + 1 === rec ? "var(--emerald)" : "var(--border)"};" onclick="approveCopilotPhoto(${idx + 1})">
            <strong>Opción #${idx + 1} ${idx + 1 === rec ? "⭐ IA" : ""}</strong>
            <img src="${mediaUrl(cp)}" />
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
  toast("Guión aprobado. Lanzando ramas paralelas SEO + Visuales...");
};

window.approveCopilotPhoto = async function (idx) {
  await api("/api/pipeline/copilot", "POST", { selected_candidate: idx });
  toast(`Foto real #${idx} seleccionada. Iniciando render GPU...`);
};

/* ==================== GALLERY & 30-DAY COOLDOWN ==================== */
async function refreshGallery() {
  const res = await api("/api/gallery");
  renderCacheBar(res.cache);

  const vGrid = document.getElementById("galleryVideosGrid");
  const vids = res.videos || [];
  if (!vids.length) {
    vGrid.innerHTML = `<div class="card" style="grid-column:1/-1; color:var(--text-muted);">Aún no hay videos empaquetados en esta biblioteca. ¡Produce el primero en la pestaña Estudio!</div>`;
  } else {
    vGrid.innerHTML = vids.map((v, idx) => `
      <div class="card" style="margin:0;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
          <span class="badge badge-vision">${esc(v.channel)}</span>
          <span style="font-size:11.5px; color:#6ee7b7;">${v.duration_sec ? `${v.duration_sec}s` : "62-72s"}</span>
        </div>
        ${v.video_path ? `<video src="${mediaUrl(v.video_path)}" controls poster="${v.thumbnail_path ? mediaUrl(v.thumbnail_path) : ""}" style="width:100%; max-height:280px; border-radius:8px; background:#000;"></video>` : ""}
        <div style="font-size:12.5px; font-weight:700; margin:8px 0;">${esc(v.slug)}</div>
        <div style="display:flex; gap:8px;">
          <button class="btn btn-primary btn-sm" onclick="copyPack(${idx})">📋 Copiar Pack Viral</button>
          <button class="btn btn-sm" onclick="openFolder('${esc(v.folder.replace(/\\/g, "\\\\"))}')">📂 Carpeta</button>
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
          <td><code>${esc(c.group)}</code></td>
          <td>${esc(c.channel)}</td>
          <td>${esc(c.topic)}</td>
          <td><code>${esc(c.image_dhash || "N/A")}</code></td>
          <td><span class="badge badge-paid">${c.days_remaining} días restantes</span></td>
        </tr>
      `).join("")
    : `<tr><td colspan="5" style="color:var(--text-dim);">Sin temas bloqueados en este momento.</td></tr>`;
}

window.copyPack = function (idx) {
  const v = (window._galleryVideos || [])[idx];
  if (v && v.copy_text) {
    navigator.clipboard.writeText(v.copy_text);
    toast("📋 ¡Título, descripción, comentario fijado y hashtags copiados!");
  }
};

window.openFolder = function (folderPath) {
  api("/api/system/open-folder", "POST", { target: folderPath });
};

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("btnRefreshGallery").addEventListener("click", refreshGallery);
  initApp();
});
