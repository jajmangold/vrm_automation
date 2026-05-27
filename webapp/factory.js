const form = document.querySelector("#job-form");
const statusLine = document.querySelector("#form-status");
const jobsEl = document.querySelector("#jobs");
const jobStatsEl = document.querySelector("#job-stats");
const storageStatsEl = document.querySelector("#storage-stats");
const recentGalleriesEl = document.querySelector("#recent-galleries");
const jobFiltersEl = document.querySelector("#job-filters");
const refreshButton = document.querySelector("#refresh-jobs");
const refreshGalleriesButton = document.querySelector("#refresh-galleries");
const batchButton = document.querySelector("#queue-batch");
const matrixButton = document.querySelector("#queue-matrix");
const previewMatrixButton = document.querySelector("#preview-matrix");
const warmMatrixCacheButton = document.querySelector("#warm-matrix-cache");
const warmRenderMatrixButton = document.querySelector("#warm-render-matrix");
const cachedLipSyncButton = document.querySelector("#queue-cached-lipsync");
const phrasebankThumbnailButton = document.querySelector("#queue-phrasebank-thumbnails");
const cachedLipSyncCacheSelect = document.querySelector("#cached-lipsync-cache-select");
const cachedLipSyncBatchIdInput = document.querySelector("#cached-lipsync-batch-id");
const cachedLipSyncCountInput = document.querySelector("#cached-lipsync-count");
const cachedLipSyncAutoCacheLinesInput = document.querySelector("#cached-lipsync-auto-cache-lines");
const cachedLipSyncCacheLineCountInput = document.querySelector("#cached-lipsync-cache-line-count");
const cachedLipSyncAudioKeyInput = document.querySelector("#cached-lipsync-audio-key");
const cachedLipSyncTimelineInput = document.querySelector("#cached-lipsync-timeline");
const cachedLipSyncRenderProfileInput = document.querySelector("#cached-lipsync-render-profile");
const cachedLipSyncPromoteInput = document.querySelector("#cached-lipsync-promote");
const cachedLipSyncChunkedInput = document.querySelector("#cached-lipsync-chunked");
const cachedLipSyncFastPublishInput = document.querySelector("#cached-lipsync-fast-publish");
const cachedLipSyncEstimateEl = document.querySelector("#cached-lipsync-estimate");
const promoteBatchButton = document.querySelector("#promote-batch");
const promoteBatchResultInput = document.querySelector("#promote-batch-result");
const promoteTextureSizeInput = document.querySelector("#promote-texture-size");
const matrixCount = document.querySelector("#matrix-count");
const matrixPlanEl = document.querySelector("#matrix-plan");
const syncGodotButton = document.querySelector("#sync-godot");
const refreshCombinedGalleryButton = document.querySelector("#refresh-combined-gallery");
const godotStageStatusEl = document.querySelector("#godot-stage-status");
const godotAnimationControlsEl = document.querySelector("#godot-animation-controls");
const placementAssetSelect = document.querySelector("#placement-asset");
const placementProfileSelect = document.querySelector("#placement-profile");
const placementSummaryEl = document.querySelector("#placement-summary");
const placementOutputEl = document.querySelector("#placement-output");
const refreshPlacementButton = document.querySelector("#refresh-placement");
const placementPlanButton = document.querySelector("#placement-plan");
const placementSuggestButton = document.querySelector("#placement-suggest");
const placementCurrentBox = document.querySelector("#placement-current-box");
const placementTargetBox = document.querySelector("#placement-target-box");
const placementCharacterBox = document.querySelector("#placement-character-box");
const characterSummaryEl = document.querySelector("#character-summary");
const characterSearchInput = document.querySelector("#character-search");
const characterPrioritySelect = document.querySelector("#character-priority");
const characterLipSelect = document.querySelector("#character-lip");
const characterSortSelect = document.querySelector("#character-sort");
const refreshCharactersButton = document.querySelector("#refresh-characters");
const characterTagsEl = document.querySelector("#character-tags");
const characterResultsEl = document.querySelector("#character-results");
const characterPrevButton = document.querySelector("#character-prev");
const characterNextButton = document.querySelector("#character-next");
const characterPageStatusEl = document.querySelector("#character-page-status");
let matrixPlanTimer;
let cachedLipSyncEstimateTimer;
let latestJobsPayload = {jobs: [], stats: {}};
let activeJobFilter = "all";
let latestGalleriesPayload = {galleries: []};
let activeGalleryFilter = "all";
let matrixJobLimit = 24;
let matrixChunkedJobLimit = 96;
let latestPlacementAssets = [];
let latestLipSyncCacheEntries = [];
let characterPage = 1;
let activeCharacterTag = "";
let latestCharacterPayload = null;

function formPayload() {
  const data = new FormData(form);
  return {
    id: data.get("id"),
    name: data.get("name"),
    text: data.get("text"),
    base: data.get("base"),
    accessory: data.get("accessory"),
    animation: data.get("animation"),
    render_profile: data.get("render_profile"),
    render: data.has("render"),
    dry_run: data.has("dry_run"),
    reuse_audio: data.has("reuse_audio"),
    reuse_lipsync: data.has("reuse_lipsync")
  };
}

function batchPayload() {
  const payload = formPayload();
  const data = new FormData(form);
  delete payload.id;
  delete payload.text;
  payload.id_prefix = data.get("id_prefix");
  payload.lines = data.get("batch_lines");
  payload.cache_line_audio = data.has("cache_line_audio");
  return payload;
}

function selectedValues(name) {
  const select = form.elements[name];
  if (!select) {
    return [];
  }
  return Array.from(select.selectedOptions || [])
    .map((option) => option.value)
    .filter(Boolean);
}

function matrixPayload() {
  const payload = batchPayload();
  const data = new FormData(form);
  payload.bases = selectedValues("matrix_bases");
  payload.accessories = selectedValues("matrix_accessories");
  payload.animations = selectedValues("matrix_animations");
  payload.chunked = data.has("matrix_chunked");
  return payload;
}

function productionMatrixPayload() {
  const payload = matrixPayload();
  payload.render = true;
  payload.dry_run = false;
  payload.cache_line_audio = true;
  return payload;
}

function cachedLipSyncPayload() {
  const payload = matrixPayload();
  const data = new FormData(form);
  const selectedCacheLines = selectedLipSyncCacheEntries();
  payload.batch_id = cachedLipSyncBatchIdInput?.value || data.get("id_prefix") || "web-control";
  payload.count = Number(cachedLipSyncCountInput?.value || 4);
  payload.text = data.get("text") || "";
  payload.audio_cache_key = cachedLipSyncAudioKeyInput?.value || "";
  payload.lipsync_timeline = cachedLipSyncTimelineInput?.value || "";
  payload.auto_cache_lines = Boolean(cachedLipSyncAutoCacheLinesInput?.checked);
  payload.cache_line_count = Number(cachedLipSyncCacheLineCountInput?.value || 4);
  payload.cache_lines = payload.auto_cache_lines ? [] : selectedCacheLines;
  payload.render_profile = cachedLipSyncRenderProfileInput?.value || "control_lipsync";
  payload.texture_size = Number(promoteTextureSizeInput?.value || 768);
  payload.promote_after = Boolean(cachedLipSyncPromoteInput?.checked);
  payload.chunked_cached_lipsync = Boolean(cachedLipSyncChunkedInput?.checked);
  payload.skip_combined_refresh = Boolean(cachedLipSyncFastPublishInput?.checked);
  return payload;
}

function lipSyncCacheLabel(entry) {
  const text = entry.text || entry.audio_cache_key;
  const clipped = text.length > 84 ? `${text.slice(0, 81)}...` : text;
  const details = `${entry.cue_count || 0} cues · ${Number(entry.duration || 0).toFixed(2)}s`;
  const active = Array.isArray(entry.active_visemes) && entry.active_visemes.length
    ? ` · ${entry.active_visemes.join("/")}`
    : "";
  const missing = Array.isArray(entry.missing_active_visemes) && entry.missing_active_visemes.length
    ? ` · missing ${entry.missing_active_visemes.join("/")}`
    : " · full";
  const source = entry.source_mode ? ` · ${entry.source_mode}` : "";
  return `${clipped} (${details}${source}${active}${missing})`;
}

function applyLipSyncCacheSelection() {
  const entry = selectedLipSyncCacheEntries()[0];
  if (!entry) {
    return;
  }
  if (cachedLipSyncAudioKeyInput) cachedLipSyncAudioKeyInput.value = entry.audio_cache_key || "";
  if (cachedLipSyncTimelineInput) cachedLipSyncTimelineInput.value = entry.timeline || "";
  if (entry.text && form.elements.text) form.elements.text.value = entry.text;
}

function selectedLipSyncCacheEntries() {
  const selectedKeys = Array.from(cachedLipSyncCacheSelect?.selectedOptions || []).map((option) => option.value);
  const keys = selectedKeys.length ? selectedKeys : [cachedLipSyncCacheSelect?.value].filter(Boolean);
  return keys
    .map((key) => latestLipSyncCacheEntries.find((item) => item.audio_cache_key === key))
    .filter(Boolean)
    .map((entry) => ({
      text: entry.text || "",
      audio_cache_key: entry.audio_cache_key || "",
      lipsync_timeline: entry.timeline || ""
    }));
}

async function refreshLipSyncCache() {
  if (!cachedLipSyncCacheSelect) {
    return;
  }
  try {
    const payload = await requestJson("/api/lipsync-cache");
    latestLipSyncCacheEntries = payload.entries || [];
    cachedLipSyncCacheSelect.replaceChildren(
      ...latestLipSyncCacheEntries.map((entry, index) => {
        const option = document.createElement("option");
        option.value = entry.audio_cache_key;
        option.textContent = lipSyncCacheLabel(entry);
        option.selected = index < 2;
        return option;
      })
    );
    applyLipSyncCacheSelection();
    await refreshCachedLipSyncEstimate();
  } catch (error) {
    statusLine.textContent = error.message;
  }
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: {"Content-Type": "application/json"},
    ...options
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || response.statusText);
  }
  return payload;
}

function renderStats(stats = {}) {
  if (!jobStatsEl) {
    return;
  }
  jobStatsEl.innerHTML = `
    <span>Total ${stats.total ?? 0}</span>
    <span>Queued ${stats.queued ?? 0}</span>
    <span>Running ${stats.running ?? 0}/${stats.max_concurrent ?? 1}</span>
    <span>OK ${stats.ok ?? 0}</span>
    <span>Errors ${stats.error ?? 0}</span>
  `;
}

function renderStorageStats(storage = {}) {
  if (!storageStatsEl) {
    return;
  }
  if (!storage || storage.status !== "ok") {
    storageStatsEl.textContent = "Storage unavailable";
    return;
  }
  const totals = storage.totals || {};
  const dirs = storage.directories || {};
  const batch = dirs["outputs/batch"] || {};
  const optimized = dirs["outputs/batch_optimized"] || {};
  const godot = dirs["godot_viewer/game_assets/glb"] || {};
  storageStatsEl.innerHTML = `
    <span>GLBs ${escapeHtml(totals.glb_file_count ?? 0)}</span>
    <span>Actual ${escapeHtml(totals.actual || "0B")}</span>
    <span>Apparent ${escapeHtml(totals.apparent || "0B")}</span>
    <span>Hardlink saved ${escapeHtml(totals.hardlink_saved || "0B")}</span>
    <span>Raw ${escapeHtml(batch.actual || "0B")}</span>
    <span>Optimized ${escapeHtml(optimized.actual || "0B")}</span>
    <span>Godot ${escapeHtml(godot.actual || "0B")}</span>
  `;
}

function formatGalleryTime(value) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return date.toLocaleString([], {month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"});
}

function renderRecentGalleries(payload = {}) {
  if (!recentGalleriesEl) {
    return;
  }
  latestGalleriesPayload = payload;
  const galleries = Array.isArray(payload.galleries) ? payload.galleries : [];
  if (!galleries.length) {
    recentGalleriesEl.innerHTML = "<p>No galleries yet.</p>";
    return;
  }
  const galleryFilters = [
    {key: "all", label: "All", count: galleries.length},
    {key: "ship", label: "Ship", count: galleries.filter(isShipGallery).length},
    {key: "review", label: "Review", count: galleries.filter(isReviewGallery).length},
    {key: "nonship", label: "Non-ship", count: galleries.filter(isNonShipGallery).length}
  ];
  const visibleGalleries = galleries.filter((gallery) => galleryMatchesFilter(gallery, activeGalleryFilter));
  const benchmark = payload.benchmark || {};
  const best = benchmark.best_throughput || {};
  const recommendation = benchmark.recommendation || {};
  const reviewBatches = Array.isArray(benchmark.review_batches) ? benchmark.review_batches : [];
  const recommendationCache = recommendation.source_job_count
    ? `${recommendation.cache_ready ? "Cache ready" : "Cache warming"}: ${recommendation.cache_hit_count || 0}/${recommendation.source_job_count} sources`
    : "";
  const queuePlan = recommendation.count
    ? `Queue plan: ${recommendation.queue_publish_combined ? "published catalog" : "fast preview"} · ${recommendation.queue_chunked ? `${recommendation.queue_chunk_count || 0} chunks` : "single job"}${Number(recommendation.queue_estimated_wall_seconds || 0) ? ` · ${Number(recommendation.queue_estimated_wall_seconds || 0).toFixed(1)}s est` : ""}`
    : "";
  const queueReference = Number(recommendation.queue_reference_elapsed_seconds || 0)
    ? `Published sample: ${escapeHtml(recommendation.queue_reference_batch_id || "recent")} · ${Number(recommendation.queue_reference_elapsed_seconds || 0).toFixed(1)}s · ${Number(recommendation.queue_reference_characters_per_second || 0).toFixed(1)} chars/s`
    : "";
  const queueOverhead = Number(recommendation.queue_reference_orchestration_overhead_seconds || 0)
    ? `Queue overhead: ${Number(recommendation.queue_reference_orchestration_overhead_seconds || 0).toFixed(1)}s latest${Number(recommendation.queue_estimate_orchestration_overhead_seconds || 0) ? ` · ${Number(recommendation.queue_estimate_orchestration_overhead_seconds || 0).toFixed(1)}s median` : ""}${Number(recommendation.queue_estimate_sample_count || 0) ? ` · ${Number(recommendation.queue_estimate_sample_count || 0)} samples` : ""}`
    : "";
  const bestMode = best.mode === "fast-preview" ? "fast preview" : "published";
  const benchmarkHtml = best.batch_id ? `
    <div class="recent-gallery-benchmark">
      <span>Best ${escapeHtml(bestMode)} throughput: <b>${escapeHtml(best.batch_id)}</b> · ${escapeHtml(Number(best.characters_per_second || 0).toFixed(1))} chars/s · ${escapeHtml(best.character_count || 0)} chars</span>
      ${recommendationCache ? `<span>${escapeHtml(recommendationCache)}</span>` : ""}
      ${queuePlan ? `<span>${escapeHtml(queuePlan)}</span>` : ""}
      ${queueReference ? `<span>${queueReference}</span>` : ""}
      ${queueOverhead ? `<span>${escapeHtml(queueOverhead)}</span>` : ""}
      ${recommendation.count ? `<button type="button" data-gallery-action="use-benchmark" data-batch-id="${escapeHtml(recommendation.batch_id || "")}" data-count="${escapeHtml(recommendation.count)}" data-chunked="${escapeHtml(Boolean(recommendation.chunked))}" data-fast-publish="${escapeHtml(Boolean(recommendation.fast_publish))}">Use benchmark</button>` : ""}
      ${recommendation.count ? `<button type="button" data-gallery-action="queue-benchmark" data-batch-id="${escapeHtml(recommendation.batch_id || "")}" data-count="${escapeHtml(recommendation.count)}" data-chunked="${escapeHtml(Boolean(recommendation.queue_chunked))}" data-fast-publish="${escapeHtml(Boolean(recommendation.queue_fast_publish))}" data-cache-ready="${escapeHtml(Boolean(recommendation.cache_ready))}" data-estimated-wall="${escapeHtml(recommendation.queue_estimated_wall_seconds || "")}">Queue benchmark</button>` : ""}
      ${reviewBatches.length ? `<span>${escapeHtml(reviewBatches.length)} review batch${reviewBatches.length === 1 ? "" : "es"}</span>` : "<span>All recent batches ship-ready</span>"}
    </div>
  ` : "";
  const filterHtml = `
    <div class="recent-gallery-filters" role="group" aria-label="Gallery filters">
      ${galleryFilters.map((filter) => `
        <button type="button" data-gallery-filter="${escapeHtml(filter.key)}" aria-pressed="${filter.key === activeGalleryFilter ? "true" : "false"}">
          ${escapeHtml(filter.label)} ${escapeHtml(filter.count)}
        </button>
      `).join("")}
    </div>
  `;
  const emptyHtml = visibleGalleries.length ? "" : `<p>No ${escapeHtml(activeGalleryFilter)} galleries in the recent set.</p>`;
  recentGalleriesEl.innerHTML = benchmarkHtml + filterHtml + emptyHtml + visibleGalleries.map((gallery) => {
    const label = gallery.batch_id || gallery.name || gallery.href;
    const updated = formatGalleryTime(gallery.updated_at);
    const summary = gallery.summary || {};
    const qaGrade = Object.entries(summary.qa_grades || {})
      .sort((a, b) => String(a[0]).localeCompare(String(b[0])))
      .map(([grade, count]) => `${grade}${count}`)
      .join(" ");
    const lipGrade = Object.entries(summary.lipsync_grades || {})
      .sort((a, b) => String(a[0]).localeCompare(String(b[0])))
      .map(([grade, count]) => `${grade}${count}`)
      .join(" ");
    const renderCache = summary.render_cache || {};
    const validationCache = summary.validation_cache || {};
    const renderDedupe = summary.render_dedupe || {};
    const variation = summary.variation || {};
    const lipQuality = summary.lipsync_quality || {};
    const activeVisemes = Array.isArray(lipQuality.active_visemes) ? lipQuality.active_visemes : [];
    const missingVisemeCount = Object.values(lipQuality.missing_active_viseme_counts || {})
      .reduce((total, count) => total + Number(count || 0), 0);
    const elapsed = Number(summary.elapsed_seconds || 0);
    const throughput = Number(summary.characters_per_second || 0);
    const renderCacheRate = Number(summary.render_cache_hit_rate || 0);
    const validationCacheRate = Number(summary.validation_cache_hit_rate || 0);
    const slowestStage = summary.slowest_stage || "";
    const slowestSeconds = Number(summary.slowest_stage_seconds || 0);
    return `
      <article class="recent-gallery-link">
        <a href="/${escapeHtml(gallery.href)}" target="gallery">
        <strong>${escapeHtml(label)}</strong>
        ${updated ? `<span>${escapeHtml(updated)}</span>` : ""}
        <span class="recent-gallery-badges">
          ${summary.character_count ? `<b>${escapeHtml(summary.character_count)} chars</b>` : ""}
          ${qaGrade ? `<b>QA ${escapeHtml(qaGrade)}</b>` : ""}
          ${Number(summary.review_count || 0) ? `<b>${escapeHtml(summary.review_count)} review</b>` : ""}
          ${lipGrade ? `<b>Lip ${escapeHtml(lipGrade)}</b>` : ""}
          ${activeVisemes.length ? `<b>Visemes ${escapeHtml(activeVisemes.join("/"))}</b>` : ""}
          ${missingVisemeCount ? `<b>Missing visemes ${escapeHtml(missingVisemeCount)}</b>` : ""}
          ${Number(lipQuality.cue_count_min || 0) ? `<b>Cues ${escapeHtml(lipQuality.cue_count_min)}-${escapeHtml(lipQuality.cue_count_max || lipQuality.cue_count_min)}</b>` : ""}
          ${Number(lipQuality.expression_count_min || 0) ? `<b>Expr ${escapeHtml(lipQuality.expression_count_min)}-${escapeHtml(lipQuality.expression_count_max || lipQuality.expression_count_min)}</b>` : ""}
          ${summary.lipsync_status && summary.lipsync_status !== "unknown" ? `<b>${escapeHtml(summary.lipsync_status)}</b>` : ""}
          ${elapsed ? `<b>${escapeHtml(elapsed.toFixed(1))}s</b>` : ""}
          ${throughput ? `<b>${escapeHtml(throughput.toFixed(1))} chars/s</b>` : ""}
          ${slowestStage ? `<b>${escapeHtml(slowestStage)} ${escapeHtml(slowestSeconds.toFixed(1))}s</b>` : ""}
          ${Number(renderCache.hit_count || 0) || Number(renderCache.miss_count || 0) ? `<b>Render ${escapeHtml(renderCache.hit_count || 0)}/${escapeHtml(renderCache.miss_count || 0)}</b>` : ""}
          ${Number(renderDedupe.materialized_duplicate_count || 0) ? `<b>Sources ${escapeHtml(renderDedupe.source_job_count || 0)}/${escapeHtml(renderDedupe.requested_job_count || summary.character_count || 0)}</b>` : ""}
          ${Number(renderDedupe.materialized_duplicate_count || 0) ? `<b>Dedupe ${escapeHtml(renderDedupe.materialized_duplicate_count || 0)}</b>` : ""}
          ${Number(variation.accessory_count || 0) ? `<b>Var ${escapeHtml(variation.base_count || 0)}B/${escapeHtml(variation.accessory_count || 0)}A/${escapeHtml(variation.animation_count || 0)}M</b>` : ""}
          ${Number(variation.category_count || 0) ? `<b>${escapeHtml((variation.categories || []).join(", "))}</b>` : ""}
          ${Number(validationCache.hit_count || 0) || Number(validationCache.miss_count || 0) ? `<b>Val ${escapeHtml(validationCache.hit_count || 0)}/${escapeHtml(validationCache.miss_count || 0)}</b>` : ""}
          ${renderCacheRate ? `<b>Render cache ${escapeHtml(Math.round(renderCacheRate * 100))}%</b>` : ""}
          ${validationCacheRate ? `<b>Val cache ${escapeHtml(Math.round(validationCacheRate * 100))}%</b>` : ""}
        </span>
        </a>
        <span class="recent-gallery-actions">
          <button type="button" data-gallery-action="use" data-batch-id="${escapeHtml(gallery.batch_id || "")}" data-batch-result="${escapeHtml(gallery.batch_result || "")}">Use</button>
          <button type="button" data-gallery-action="sync" data-batch-result="${escapeHtml(gallery.batch_result || "")}">Sync Godot</button>
        </span>
      </article>
    `;
  }).join("");
}

function isReviewGallery(gallery) {
  const summary = gallery.summary || {};
  return Number(summary.review_count || 0) > 0;
}

function isNonShipGallery(gallery) {
  const summary = gallery.summary || {};
  return summary.ship_compatible === false || Number(summary.non_ship_outfit_count || 0) > 0;
}

function isShipGallery(gallery) {
  return !isReviewGallery(gallery) && !isNonShipGallery(gallery);
}

function galleryMatchesFilter(gallery, filter) {
  if (filter === "ship") return isShipGallery(gallery);
  if (filter === "review") return isReviewGallery(gallery);
  if (filter === "nonship") return isNonShipGallery(gallery);
  return true;
}

async function handleRecentGalleryAction(button) {
  const action = button.dataset.galleryAction;
  const batchResult = button.dataset.batchResult || "";
  const batchId = button.dataset.batchId || "";
  const applyBenchmarkSettings = () => {
    if (batchId && cachedLipSyncBatchIdInput) cachedLipSyncBatchIdInput.value = batchId;
    if (button.dataset.count && cachedLipSyncCountInput) cachedLipSyncCountInput.value = button.dataset.count;
    if (cachedLipSyncChunkedInput) cachedLipSyncChunkedInput.checked = button.dataset.chunked === "true";
    if (cachedLipSyncFastPublishInput) cachedLipSyncFastPublishInput.checked = button.dataset.fastPublish !== "false";
    updateCachedLipSyncCountLimit();
  };
  if (action === "use") {
    if (batchId && cachedLipSyncBatchIdInput) cachedLipSyncBatchIdInput.value = batchId;
    if (batchResult && promoteBatchResultInput) promoteBatchResultInput.value = batchResult;
    statusLine.textContent = `Selected ${batchId || batchResult || "gallery batch"}`;
    return;
  }
  if (action === "use-benchmark") {
    applyBenchmarkSettings();
    await refreshCachedLipSyncEstimate();
    statusLine.textContent = `Using benchmark settings for ${batchId || "next batch"}`;
    return;
  }
  if (action === "queue-benchmark") {
    applyBenchmarkSettings();
    if (cachedLipSyncFastPublishInput) cachedLipSyncFastPublishInput.checked = false;
    if (cachedLipSyncChunkedInput && Number(cachedLipSyncCountInput?.value || 0) > matrixJobLimit) {
      cachedLipSyncChunkedInput.checked = true;
    }
    updateCachedLipSyncCountLimit();
    await queuePhrasebankThumbnailBatch({
      renderCacheReady: button.dataset.cacheReady === "true",
      estimatedWallSeconds: Number(button.dataset.estimatedWall || 0)
    });
    return;
  }
  if (action === "sync") {
    statusLine.textContent = `Syncing ${batchId || batchResult || "gallery"} to Godot...`;
    const payload = await requestJson("/api/godot/sync", {
      method: "POST",
      body: JSON.stringify({batch_result: batchResult})
    });
    const assetCount = payload.reload?.asset_count ?? payload.export?.exported?.length ?? 0;
    const skipped = payload.export?.skipped?.length ?? 0;
    statusLine.textContent = `Godot sync ${payload.status}: ${assetCount} assets, ${skipped} skipped`;
    await refreshGodotStageStatus();
  }
}

async function refreshGalleries() {
  const payload = await requestJson("/api/galleries?limit=12");
  renderRecentGalleries(payload);
}

function characterQueryParams() {
  const params = new URLSearchParams();
  params.set("page", String(characterPage));
  params.set("per_page", "48");
  const query = characterSearchInput?.value?.trim();
  const priority = characterPrioritySelect?.value;
  const lip = characterLipSelect?.value;
  const sort = characterSortSelect?.value || "ready";
  if (query) params.set("q", query);
  if (activeCharacterTag) params.set("tag", activeCharacterTag);
  if (priority) params.set("priority", priority);
  if (lip) params.set("lip", lip);
  params.set("sort", sort);
  return params;
}

function renderCharacterTags(summary = {}) {
  if (!characterTagsEl) {
    return;
  }
  const tags = Array.isArray(summary.top_tags) ? summary.top_tags.slice(0, 24) : [];
  characterTagsEl.innerHTML = [
    `<button type="button" data-character-tag="" class="${activeCharacterTag ? "" : "active"}">All tags</button>`,
    ...tags.map((item) => `
      <button type="button" data-character-tag="${escapeHtml(item.tag)}" class="${item.tag === activeCharacterTag ? "active" : ""}">
        ${escapeHtml(item.tag)} ${escapeHtml(item.count)}
      </button>
    `)
  ].join("");
}

function renderCharacterBrowser(payload = {}) {
  latestCharacterPayload = payload;
  const summary = payload.summary || {};
  const page = payload.pagination || {};
  const lipSummary = summary.lipsync || {};
  if (characterSummaryEl) {
    characterSummaryEl.textContent = `${summary.character_count || 0} characters · ${page.total ?? 0} match · ${lipSummary.checked_count || 0} lip-checked · A ${lipSummary.grade_counts?.A || 0}`;
  }
  renderCharacterTags(summary);
  if (characterPageStatusEl) {
    characterPageStatusEl.textContent = `Page ${page.page || 1} / ${page.page_count || 1} · ${page.start || 0}-${page.end || 0} of ${page.total || 0}`;
  }
  if (characterPrevButton) characterPrevButton.disabled = (page.page || 1) <= 1;
  if (characterNextButton) characterNextButton.disabled = (page.page || 1) >= (page.page_count || 1);
  if (!characterResultsEl) {
    return;
  }
  const characters = payload.characters || [];
  if (!characters.length) {
    characterResultsEl.innerHTML = "<p>No characters match these filters.</p>";
    return;
  }
  characterResultsEl.innerHTML = characters.map(renderCharacterCard).join("");
}

function renderCharacterCard(character) {
  const lipsync = character.lipsync || {};
  const qa = character.qa || {};
  const assetSize = character.asset_size || {};
  const links = Array.isArray(character.links) ? character.links : [];
  const updated = formatCharacterUpdated(character.updated_at);
  const linkMarkup = links.map((link) => `<a href="${escapeHtml(link.href)}" target="_blank" rel="noreferrer">${escapeHtml(link.label)}</a>`).join("");
  const tagMarkup = (character.tags || []).slice(0, 8).map((tag) => `<span>${escapeHtml(tag)}</span>`).join("");
  const image = character.review_image
    ? `<a class="character-thumb" href="${escapeHtml(character.review_image)}" target="_blank" rel="noreferrer"><img src="${escapeHtml(character.review_image)}" alt="${escapeHtml(character.display_name)} QA render" loading="lazy"></a>`
    : `<div class="character-thumb empty">No PNG</div>`;
  return `
    <article class="character-card">
      ${image}
      <div class="character-card-body">
        <div class="character-title">
          <strong>${escapeHtml(character.display_name || character.id)}</strong>
          <span>QA ${escapeHtml(qa.grade || "n/a")} · ${escapeHtml(qa.priority || "n/a")}</span>
        </div>
        <div class="character-meta">
          <span>${escapeHtml(character.animation || "unknown")}</span>
          <span>${escapeHtml(character.category || "none")}</span>
          <span>Lip ${escapeHtml(lipsync.status || "unchecked")} ${lipsync.grade ? `/${escapeHtml(lipsync.grade)}` : ""}</span>
          <span>${escapeHtml(lipsync.cue_count || 0)} cues</span>
          <span>${character.has_game_asset ? "Game asset" : "No game asset"}</span>
          ${assetSize.optimized_bytes ? `<span>GLB ${escapeHtml(formatBytes(assetSize.optimized_bytes))}</span>` : ""}
          ${Number(assetSize.saved_pct || 0) ? `<span>${escapeHtml(assetSize.saved_pct)}% saved</span>` : ""}
          ${updated ? `<span>Updated ${escapeHtml(updated)}</span>` : ""}
        </div>
        <p>${escapeHtml(character.persona || character.notes || character.id)}</p>
        <div class="character-links">
          <button type="button" data-character-load="${escapeHtml(character.id)}">Load</button>
          ${lipsync.timeline ? `<button type="button" data-character-talk="${escapeHtml(character.id)}" data-timeline="${escapeHtml(lipsync.timeline)}">Talk</button>` : ""}
          ${linkMarkup}
        </div>
        <div class="character-tag-list">${tagMarkup}</div>
      </div>
    </article>
  `;
}

function formatBytes(value) {
  let size = Number(value || 0);
  if (!size) {
    return "n/a";
  }
  const units = ["B", "KB", "MB", "GB"];
  for (const unit of units) {
    if (size < 1024 || unit === "GB") {
      return unit === "B" ? `${Math.round(size)} ${unit}` : `${size.toFixed(1)} ${unit}`;
    }
    size /= 1024;
  }
  return `${size.toFixed(1)} GB`;
}

function formatCharacterUpdated(value) {
  const timestamp = Number(value || 0);
  if (!timestamp) {
    return "";
  }
  const date = new Date(timestamp * 1000);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}

async function refreshCharacters() {
  if (!characterResultsEl) {
    return;
  }
  const payload = await requestJson(`/api/characters?${characterQueryParams().toString()}`);
  renderCharacterBrowser(payload);
}

async function refreshStorageStats() {
  if (!storageStatsEl) {
    return;
  }
  try {
    renderStorageStats(await requestJson("/api/storage"));
  } catch (error) {
    storageStatsEl.textContent = error.message;
  }
}

function isPipelineJob(job) {
  return Boolean(job.request?.pipeline) ||
    Boolean(job.publish_result) ||
    (Array.isArray(job.child_job_ids) && job.child_job_ids.length > 0) ||
    (Array.isArray(job.render_job_ids) && job.render_job_ids.length > 0) ||
    (Array.isArray(job.warm_job_ids) && job.warm_job_ids.length > 0);
}

function jobMatchesFilter(job, filter) {
  const summary = job.output_summary || {};
  if (filter === "game-ready") {
    return Boolean(summary.has_game_asset);
  }
  if (filter === "cache-only") {
    return Boolean(summary.has_timeline) && !summary.has_game_asset;
  }
  if (filter === "lip-ready") {
    return Boolean(summary.has_game_asset) && summary.lip_sync_readiness?.status === "ready";
  }
  if (filter === "needs-lip-fix") {
    return Boolean(summary.has_game_asset) && summary.lip_sync_readiness?.status === "review";
  }
  if (filter === "pipelines") {
    return isPipelineJob(job);
  }
  if (filter === "errors") {
    return job.status === "error";
  }
  return true;
}

function jobFilterCounts(jobs) {
  return {
    all: jobs.length,
    "game-ready": jobs.filter((job) => jobMatchesFilter(job, "game-ready")).length,
    "cache-only": jobs.filter((job) => jobMatchesFilter(job, "cache-only")).length,
    "lip-ready": jobs.filter((job) => jobMatchesFilter(job, "lip-ready")).length,
    "needs-lip-fix": jobs.filter((job) => jobMatchesFilter(job, "needs-lip-fix")).length,
    pipelines: jobs.filter((job) => jobMatchesFilter(job, "pipelines")).length,
    errors: jobs.filter((job) => jobMatchesFilter(job, "errors")).length
  };
}

function renderJobFilters(jobs) {
  if (!jobFiltersEl) {
    return;
  }
  const counts = jobFilterCounts(jobs);
  jobFiltersEl.querySelectorAll("[data-job-filter]").forEach((button) => {
    const filter = button.dataset.jobFilter || "all";
    const label = button.dataset.label || filter;
    const active = filter === activeJobFilter;
    button.textContent = `${label} ${counts[filter] ?? 0}`;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });
}

function renderJobs(payload) {
  latestJobsPayload = payload || {jobs: [], stats: {}};
  const jobs = payload.jobs || [];
  renderStats(payload.stats);
  renderJobFilters(jobs);
  if (!jobs.length) {
    jobsEl.innerHTML = "<p>No jobs yet.</p>";
    return;
  }
  const visibleJobs = jobs.filter((job) => jobMatchesFilter(job, activeJobFilter));
  if (!visibleJobs.length) {
    jobsEl.innerHTML = `<p>No ${escapeHtml(activeJobFilter)} jobs.</p>`;
    return;
  }
  jobsEl.innerHTML = visibleJobs.slice().reverse().map((job) => {
    const status = job.status || "unknown";
    const logLines = job.log_tail || [];
    const log = logLines.join("\n");
    const pipelineLinks = [
      renderJobLinks("children", job.child_job_ids),
      renderJobLinks("warm", job.warm_job_ids),
      renderJobLinks("render", job.render_job_ids)
    ].join("");
    const publishStatus = renderPublishStatus(job.publish_result);
    const outputSummary = renderOutputSummary(job.output_summary);
    const godotActions = renderGodotActions(job);
    return `
      <article class="job">
        <div><strong>${job.id}</strong><span class="pill ${status}">${status}</span></div>
        <div>${job.request?.name || ""}</div>
        <div>${job.request?.text || ""}</div>
        <div>return: ${job.returncode ?? ""}</div>
        ${outputSummary}
        ${godotActions}
        ${publishStatus}
        ${pipelineLinks}
        <details class="job-log">
          <summary>Log tail (${logLines.length})</summary>
          <pre>${escapeHtml(log)}</pre>
        </details>
      </article>
    `;
  }).join("");
}

function renderOutputSummary(summary) {
  if (!summary || !Array.isArray(summary.links) || !summary.links.length) {
    return "";
  }
  const qa = summary.qa || {};
  const lipsync = summary.lipsync || {};
  const reviewImage = summary.review_image || "";
  const readiness = renderLipSyncReadiness(summary.lip_sync_readiness);
  const lipQuality = renderLipSyncQuality(lipsync.quality);
  const visemeDiagnostics = renderVisemeDiagnostics(lipsync);
  const batchTiming = renderBatchTiming(summary.batch_run);
  const pipelineTiming = renderPipelineTiming(summary.pipeline_timing);
  const estimateAccuracy = renderEstimateAccuracy(summary.estimate_accuracy);
  const links = summary.links.map((link) => `
    <a href="${escapeHtml(link.href)}" target="_blank" rel="noreferrer">${escapeHtml(link.label)}</a>
  `).join("");
  return `
    <div class="job-outputs">
      ${reviewImage ? `<a class="job-review-image" href="${escapeHtml(reviewImage)}" target="_blank" rel="noreferrer"><img src="${escapeHtml(reviewImage)}" alt="QA render for generated job"></a>` : ""}
      <strong>Outputs</strong>
      ${qa.grade ? `<span>QA ${escapeHtml(qa.grade)} · ${escapeHtml(qa.score ?? "")} · ${escapeHtml(qa.priority || "")}</span>` : ""}
      ${lipsync.cue_count ? `<span>Lip sync ${escapeHtml(lipsync.cue_count)} cues / ${escapeHtml(lipsync.duration)}s</span>` : ""}
      ${readiness}
      ${lipQuality}
      ${visemeDiagnostics}
      ${batchTiming}
      ${pipelineTiming}
      ${estimateAccuracy}
      <div class="job-output-links">${links}</div>
    </div>
  `;
}

function renderBatchTiming(batchRun) {
  const stageSummary = batchRun?.stage_summary || {};
  if (!stageSummary.slowest_stage) {
    return "";
  }
  const elapsed = batchRun.elapsed_seconds ? ` · total ${Number(batchRun.elapsed_seconds).toFixed(1)}s` : "";
  const slowestSeconds = Number(stageSummary.slowest_stage_seconds || 0).toFixed(1);
  return `<span class="job-timing">Slowest ${escapeHtml(stageSummary.slowest_stage)} ${escapeHtml(slowestSeconds)}s${escapeHtml(elapsed)}</span>`;
}

function renderPipelineTiming(timing) {
  if (!timing || !timing.wall_elapsed_seconds) {
    return "";
  }
  const wall = Number(timing.wall_elapsed_seconds || 0).toFixed(1);
  const child = Number(timing.child_elapsed_seconds || 0).toFixed(1);
  const workers = Number(timing.chunk_workers || 1);
  const efficiency = Number(timing.parallel_efficiency || 0).toFixed(2);
  const reports = Array.isArray(timing.child_reports) ? timing.child_reports : [];
  const slowest = reports
    .slice()
    .sort((a, b) => Number(b.elapsed_seconds || 0) - Number(a.elapsed_seconds || 0))[0];
  const slowestLabel = slowest
    ? ` · slowest ${slowest.batch_id || "chunk"} ${Number(slowest.elapsed_seconds || 0).toFixed(1)}s`
    : "";
  return `
    <div class="job-pipeline-timing">
      <span>Pipeline ${escapeHtml(wall)}s wall · ${escapeHtml(child)}s child · ${escapeHtml(workers)} worker${workers === 1 ? "" : "s"}</span>
      <span>Parallel efficiency ${escapeHtml(efficiency)}x${escapeHtml(slowestLabel)}</span>
    </div>
  `;
}

function renderEstimateAccuracy(accuracy) {
  if (!accuracy || !accuracy.estimated_wall_seconds) {
    return "";
  }
  const estimated = Number(accuracy.estimated_wall_seconds || 0).toFixed(1);
  const actual = Number(accuracy.actual_wall_seconds || 0).toFixed(1);
  const error = Number(accuracy.error_seconds || 0).toFixed(1);
  const ratio = Number(accuracy.actual_to_estimate_ratio || 0).toFixed(2);
  const status = accuracy.estimate_status || "close";
  const sign = Number(error) > 0 ? "+" : "";
  return `
    <div class="job-estimate-accuracy ${escapeHtml(status)}">
      <span>Estimate ${escapeHtml(estimated)}s · actual ${escapeHtml(actual)}s · error ${escapeHtml(sign)}${escapeHtml(error)}s</span>
      <span>Accuracy ratio ${escapeHtml(ratio)}x · ${escapeHtml(status)}</span>
    </div>
  `;
}

function renderLipSyncQuality(quality) {
  if (!quality?.status) {
    return "";
  }
  const cssClass = quality.status === "ok" ? "job-lip-ready" : "job-lip-review";
  const source = quality.source_mode || "unknown";
  const density = quality.cue_density_per_second ? ` · ${quality.cue_density_per_second}/s` : "";
  const warnings = Array.isArray(quality.warnings) ? quality.warnings : [];
  const issues = Array.isArray(quality.issues) ? quality.issues : [];
  const detail = issues.length ? issues.join(", ") : warnings.slice(0, 2).join(", ");
  return `
    <div class="job-lip-quality ${cssClass}">
      <span>Lip quality ${escapeHtml(quality.status)} / ${escapeHtml(quality.grade || "n/a")}</span>
      <span>${escapeHtml(source)}${escapeHtml(density)}${detail ? ` · ${escapeHtml(detail)}` : ""}</span>
    </div>
  `;
}

function renderLipSyncReadiness(readiness) {
  if (!readiness?.status) {
    return "";
  }
  const missing = Array.isArray(readiness.missing_visemes) ? readiness.missing_visemes : [];
  const reasons = Array.isArray(readiness.reasons) ? readiness.reasons : [];
  const reasonLabels = reasons.map(readinessReasonLabel);
  const detail = reasonLabels.length ? reasonLabels.join(", ") : missing.length ? `missing ${missing.join(", ")}` : "";
  const cssClass = readiness.status === "ready" ? "job-lip-ready" : "job-lip-review";
  return `
    <div class="job-lip-readiness ${cssClass}">
      <span>${escapeHtml(readiness.label || (readiness.status === "ready" ? "Lip-ready" : "Needs lip fix"))}</span>
      ${detail ? `<span>${escapeHtml(detail)}</span>` : ""}
    </div>
  `;
}

function readinessReasonLabel(reason) {
  return {
    "missing-game-asset": "missing game asset",
    "missing-timeline": "missing timeline",
    "empty-timeline": "empty timeline",
    "missing-face-profile": "missing face profile",
    "missing-visemes": "missing visemes"
  }[reason] || String(reason || "").replaceAll("-", " ");
}

function renderVisemeDiagnostics(lipsync) {
  const counts = lipsync?.viseme_counts || {};
  const names = Object.keys(counts);
  if (!names.length && !lipsync?.missing_visemes?.length) {
    return "";
  }
  const chips = names.map((name) => `
    <span class="job-viseme">${escapeHtml(name)} ${escapeHtml(counts[name])}</span>
  `).join("");
  const expressionCount = Number(lipsync.expression_count || 0);
  const missing = Array.isArray(lipsync.missing_visemes) ? lipsync.missing_visemes : [];
  return `
    <div class="job-visemes">
      ${chips}
      ${expressionCount ? `<span class="job-viseme">expr ${escapeHtml(expressionCount)}</span>` : ""}
      ${missing.length ? `<span class="job-viseme-missing">Missing visemes ${escapeHtml(missing.join(", "))}</span>` : ""}
    </div>
  `;
}

function renderGodotActions(job) {
  const summary = job.output_summary || {};
  const timeline = summary.lipsync?.path || "";
  if (!summary.has_game_asset && !timeline) {
    return "";
  }
  if (!summary.has_game_asset) {
    return `
      <div class="godot-job-actions timeline-only">
        <button type="button" data-godot-action="timeline" data-job-id="${escapeHtml(job.id)}" data-timeline="${escapeHtml(timeline)}">Send timeline to Godot</button>
      </div>
    `;
  }
  return `
    <div class="godot-job-actions">
      <button type="button" data-godot-action="load" data-job-id="${escapeHtml(job.id)}">Load in Godot</button>
      ${timeline ? `<button type="button" data-godot-action="talk" data-job-id="${escapeHtml(job.id)}" data-timeline="${escapeHtml(timeline)}">Talk in Godot</button>` : ""}
    </div>
  `;
}

function renderJobLinks(label, ids) {
  if (!Array.isArray(ids) || !ids.length) {
    return "";
  }
  return `
    <div class="job-links">
      <span>${label}</span>
      ${ids.map((id) => `<code>${escapeHtml(id)}</code>`).join("")}
    </div>
  `;
}

function listCount(value) {
  return Array.isArray(value) ? value.length : 0;
}

function renderPublishStatus(publish) {
  if (!publish) {
    return "";
  }
  const status = publish.status || "review";
  const galleryReturn = publish.gallery?.returncode ?? "";
  const reload = publish.godot?.reload || {};
  const exportResult = publish.godot?.export || {};
  const assetCount = reload.asset_count ?? "";
  const exported = listCount(exportResult.exported);
  const skipped = listCount(exportResult.skipped);
  const failed = listCount(exportResult.failed);
  const error = publish.godot?.error || exportResult.error || "";
  return `
    <div class="publish-status publish-${escapeHtml(status)}">
      <strong>Publish</strong>
      <span>${escapeHtml(status)}</span>
      <span>gallery return ${escapeHtml(galleryReturn)}</span>
      <span>Godot assets ${escapeHtml(assetCount)}</span>
      <span>${exported} exported</span>
      <span>${skipped} skipped</span>
      <span>${failed} failed</span>
      ${error ? `<span class="publish-error">${escapeHtml(error)}</span>` : ""}
    </div>
  `;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function compactJson(value) {
  return JSON.stringify(value, null, 2);
}

function parseBoxInput(value) {
  return String(value || "")
    .split(",")
    .map((part) => Number(part.trim()))
    .filter((value) => Number.isFinite(value));
}

function renderPlacementSummary(payload) {
  if (!placementSummaryEl) {
    return;
  }
  const counts = payload?.counts || {};
  const priorities = payload?.placement_priorities || {};
  placementSummaryEl.innerHTML = [
    `Ship ${counts.ship || 0}`,
    `Review ${counts.review || 0}`,
    `Reject ${counts.reject || 0}`,
    `Saved ${priorities["use-saved-overrides"] || 0}`,
    `Rough ${priorities["rough-calibration"] || 0}`
  ].map((item) => `<span>${escapeHtml(item)}</span>`).join("");
}

function renderPlacementOutput(payload) {
  if (!placementOutputEl) {
    return;
  }
  placementOutputEl.textContent = compactJson(payload);
}

async function refreshPlacementAssets() {
  if (!placementAssetSelect) {
    return;
  }
  const payload = await requestJson("/api/placement/assets");
  latestPlacementAssets = payload.assets || [];
  const current = placementAssetSelect.value;
  placementAssetSelect.replaceChildren(
    ...latestPlacementAssets.map((asset) => {
      const option = document.createElement("option");
      option.value = asset.key;
      option.textContent = `${asset.title || asset.key} · ${asset.quality} · ${asset.placement_priority}`;
      return option;
    })
  );
  if (latestPlacementAssets.some((asset) => asset.key === current)) {
    placementAssetSelect.value = current;
  }
  renderPlacementSummary(payload);
  if (!placementOutputEl.textContent) {
    renderPlacementOutput({status: payload.status, counts: payload.counts, placement_priorities: payload.placement_priorities});
  }
}

async function buildPlacementPlan() {
  if (!placementAssetSelect || !placementProfileSelect) {
    return;
  }
  const payload = await requestJson("/api/placement/plan", {
    method: "POST",
    body: JSON.stringify({
      asset_key: placementAssetSelect.value,
      profile: placementProfileSelect.value
    })
  });
  renderPlacementOutput({
    status: payload.status,
    asset: payload.asset,
    profile: payload.profile,
    render: payload.render,
    sam: payload.sam,
    qwen: payload.qwen,
    command_template: payload.command_template
  });
}

async function suggestPlacementOverrides() {
  if (!placementAssetSelect) {
    return;
  }
  const payload = await requestJson("/api/placement/suggest", {
    method: "POST",
    body: JSON.stringify({
      asset_key: placementAssetSelect.value,
      current_box: parseBoxInput(placementCurrentBox.value),
      target_box: parseBoxInput(placementTargetBox.value),
      character_box: parseBoxInput(placementCharacterBox.value),
      center_correction_gain: 0.5
    })
  });
  renderPlacementOutput({
    status: payload.status,
    asset: payload.asset,
    fit_overrides: payload.suggestion?.fit_overrides,
    pixel_delta: payload.suggestion?.pixel_delta,
    anchor_calibration: payload.suggestion?.anchor_calibration
  });
}

function stagePayload(button) {
  const godotStageAction = button.dataset.godotStageAction;
  const value = Number(button.dataset.value ?? "1");
  if (godotStageAction === "camera") {
    return {
      url: "/api/godot/camera",
      body: {preset: button.dataset.preset || "portrait"},
      label: `camera ${button.dataset.preset || "portrait"}`
    };
  }
  if (godotStageAction === "expression-preset") {
    return {
      url: "/api/godot/expression-preset",
      body: {name: button.dataset.name || "neutral", value},
      label: `face ${button.dataset.name || "neutral"}`
    };
  }
  if (godotStageAction === "viseme") {
    return {
      url: "/api/godot/viseme",
      body: {name: button.dataset.name || "rest", value},
      label: `viseme ${button.dataset.name || "rest"}`
    };
  }
  if (godotStageAction === "animation") {
    return {
      url: "/api/godot/animation",
      body: {name: button.dataset.name || "", time: Number(button.dataset.time || "0")},
      label: `animation ${button.dataset.name || ""}`
    };
  }
  return null;
}

function renderGodotStageStatus(health = {}, profile = {}) {
  if (!godotStageStatusEl) {
    return;
  }
  const loaded = health.loaded || "";
  const profileQuality = profile.quality || {};
  const lipsyncStatus = health.lipsync || {};
  const visemeCount = profileQuality.viseme_count ?? Object.keys(profile.visemes || {}).length;
  const expressionCount = profileQuality.expression_count ?? Object.keys(profile.expressions || {}).length;
  const chips = [
    `Godot ${health.status || "unknown"}`,
    `${health.asset_count ?? 0} assets`,
    loaded ? `Loaded ${loaded}` : "No asset loaded"
  ];
  if (profile.status === "ok") {
    chips.push(`${visemeCount} visemes`);
    chips.push(`${expressionCount} expressions`);
  }
  if (lipsyncStatus.status) {
    chips.push(`Lip ${lipsyncStatus.status}`);
  }
  if (lipsyncStatus.active_viseme) {
    chips.push(`Viseme ${lipsyncStatus.active_viseme}`);
  }
  if (Number(lipsyncStatus.cue_count || 0) > 0) {
    chips.push(`${lipsyncStatus.cue_index ?? 0}/${lipsyncStatus.cue_count} cues`);
  }
  godotStageStatusEl.innerHTML = chips.map((chip) => `<span>${escapeHtml(chip)}</span>`).join("");
  renderGodotAnimationControls(health.animations);
}

function animationButtonLabel(name) {
  const label = String(name || "")
    .replace(/_?Armature$/i, "")
    .replaceAll("_", " ")
    .trim();
  if (!label) {
    return "Animation";
  }
  return label.split(/\s+/).map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(" ");
}

function renderGodotAnimationControls(animations = []) {
  if (!godotAnimationControlsEl) {
    return;
  }
  const label = document.createElement("span");
  label.textContent = "Animation";
  const names = (Array.isArray(animations) ? animations : [])
    .map((name) => String(name || ""))
    .filter((name) => name && !name.toLowerCase().startsWith("face"));
  const buttons = (names.length ? names : ["talk_idle_Armature"]).map((name) => {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.godotStageAction = "animation";
    button.dataset.name = name;
    button.textContent = animationButtonLabel(name);
    return button;
  });
  godotAnimationControlsEl.replaceChildren(label, ...buttons);
}

async function refreshGodotStageStatus() {
  if (!godotStageStatusEl) {
    return;
  }
  try {
    const health = await requestJson("/api/godot/health");
    let profile = {};
    let lipsync = health.lipsync || {};
    if (health.loaded) {
      profile = await requestJson("/api/godot/face-profile");
    }
    try {
      lipsync = await requestJson("/api/godot/lipsync-status");
    } catch (error) {
      lipsync = health.lipsync || {};
    }
    health.lipsync = lipsync;
    renderGodotStageStatus(health, profile);
  } catch (error) {
    godotStageStatusEl.innerHTML = `<span>Godot error</span><span>${escapeHtml(error.message)}</span>`;
  }
}

async function refreshJobs() {
  const payload = await requestJson("/api/jobs?compact=1&limit=40&summary=0&logs=0");
  renderJobs(payload);
}

function populateSelect(name, options, selectedValue) {
  const select = form.elements[name];
  if (!select || !Array.isArray(options) || !options.length) {
    return;
  }
  const currentValues = selectedValues(name);
  const selectedValuesSet = new Set(Array.isArray(selectedValue) ? selectedValue : [selectedValue]);
  select.replaceChildren(
    ...options.map((option) => {
      const element = document.createElement("option");
      element.value = option.value;
      element.textContent = option.label;
      if (select.multiple) {
        element.selected = currentValues.includes(option.value) || selectedValuesSet.has(option.value);
      }
      return element;
    })
  );
  if (!select.multiple) {
    const currentValue = currentValues[0];
    if (options.some((option) => option.value === currentValue)) {
      select.value = currentValue;
    } else {
      select.value = selectedValue;
    }
  }
  updateMatrixCount();
}

async function loadOptions() {
  try {
    const payload = await requestJson("/api/options");
    populateSelect("base", payload.base_models, payload.defaults?.base);
    populateSelect("accessory", payload.accessories, payload.defaults?.accessory);
    populateSelect("animation", payload.animations, payload.defaults?.animation);
    populateSelect("matrix_bases", payload.base_models, [payload.defaults?.base]);
    populateSelect("matrix_accessories", payload.accessories, [payload.defaults?.accessory]);
    populateSelect("matrix_animations", payload.animations, [payload.defaults?.animation]);
    matrixJobLimit = Number(payload.limits?.matrix_jobs || matrixJobLimit);
    matrixChunkedJobLimit = Number(payload.limits?.chunked_matrix_jobs || matrixChunkedJobLimit);
    updateMatrixCount();
    updateCachedLipSyncCountLimit();
  } catch (error) {
    console.warn(error);
  }
}

function batchLineCount() {
  const data = new FormData(form);
  return String(data.get("batch_lines") || "")
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean).length;
}

function updateMatrixCount() {
  if (!matrixCount) {
    return;
  }
  const count = Math.max(1, batchLineCount()) *
    Math.max(1, selectedValues("matrix_bases").length) *
    Math.max(1, selectedValues("matrix_accessories").length) *
    Math.max(1, selectedValues("matrix_animations").length);
  const chunked = new FormData(form).has("matrix_chunked");
  const limit = chunked ? matrixChunkedJobLimit : matrixJobLimit;
  const label = chunked ? "chunked max" : "max";
  matrixCount.textContent = `${count} ${count === 1 ? "job" : "jobs"} / ${limit} ${label}`;
  matrixCount.classList.toggle("over-limit", count > limit);
}

function updateCachedLipSyncCountLimit() {
  if (!cachedLipSyncCountInput) {
    return;
  }
  const chunked = Boolean(cachedLipSyncChunkedInput?.checked);
  const fastPublish = Boolean(cachedLipSyncFastPublishInput?.checked);
  const limit = chunked || fastPublish ? matrixChunkedJobLimit : matrixJobLimit;
  const label = chunked ? "chunked max" : fastPublish ? "fast max" : "max";
  cachedLipSyncCountInput.max = String(limit);
  cachedLipSyncCountInput.title = `Cached lip-sync count: ${limit} ${label}`;
  if (Number(cachedLipSyncCountInput.value || 1) > limit) {
    cachedLipSyncCountInput.value = String(limit);
  }
}

function renderMatrixPlan(plan) {
  if (!matrixPlanEl) {
    return;
  }
  if (!plan || plan.status !== "ok") {
    matrixPlanEl.textContent = "Matrix cache plan unavailable.";
    return;
  }
  const groups = (plan.cache_groups || []).map((group) => `
    <span class="${group.audio_cache}">${group.audio_cache_key}: audio ${group.audio_cache}</span>
    <span class="${group.lipsync_cache}">lip-sync ${group.lipsync_cache}</span>
  `).join("");
  matrixPlanEl.innerHTML = `
    <div class="plan-stats">
      <span>${plan.job_count} jobs</span>
      <span>${plan.cache_group_count} line groups</span>
      <span>${plan.cache_reuse_jobs} reused prep slots</span>
      <span>${plan.estimated_tts_jobs} TTS jobs</span>
      <span>${plan.estimated_lipsync_jobs} lip-sync jobs</span>
      ${plan.chunked ? `<span>${plan.chunk_count} render chunks of ${plan.chunk_size}</span>` : ""}
    </div>
    <div class="plan-groups">${groups || "<span>cache disabled</span>"}</div>
  `;
}

async function refreshMatrixPlan() {
  if (!matrixPlanEl) {
    return;
  }
  try {
    const plan = await requestJson("/api/matrix-plan", {
      method: "POST",
      body: JSON.stringify(matrixPayload())
    });
    renderMatrixPlan(plan);
  } catch (error) {
    matrixPlanEl.textContent = error.message;
  }
}

function renderCachedLipSyncEstimate(estimate) {
  if (!cachedLipSyncEstimateEl) {
    return;
  }
  if (!estimate || estimate.status !== "ok") {
    cachedLipSyncEstimateEl.textContent = "Cached lip-sync estimate unavailable.";
    return;
  }
  const chunks = (estimate.chunks || []).map((chunk) => `
    <span>${escapeHtml(chunk.batch_id || "chunk")} · ${escapeHtml(chunk.count)} assets · ${escapeHtml(chunk.estimated_seconds)}s · ${escapeHtml(chunk.confidence || "sampled")}</span>
  `).join("");
  const workerOptions = (estimate.worker_options || []).map((option) => `
    <span>${escapeHtml(option.workers)} worker${option.workers === 1 ? "" : "s"} · ${escapeHtml(option.estimated_wall_seconds)}s wall</span>
  `).join("");
  const notices = renderEstimateNotices(estimate);
  cachedLipSyncEstimateEl.innerHTML = `
    <div class="plan-stats">
      <span>${escapeHtml(estimate.count)} assets</span>
      <span>${escapeHtml(estimate.chunk_count)} chunk${estimate.chunk_count === 1 ? "" : "s"}</span>
      <span>${escapeHtml(estimate.chunk_workers)} worker${estimate.chunk_workers === 1 ? "" : "s"}</span>
      <span>${escapeHtml(estimate.estimated_wall_seconds)}s wall est</span>
      <span>${escapeHtml(estimate.estimated_parallel_efficiency)}x efficiency</span>
      <span>${escapeHtml(estimate.sample_count)} timing samples</span>
      <span>${escapeHtml(estimate.confidence || "sampled")}</span>
    </div>
    ${notices}
    <div class="plan-groups">${workerOptions}</div>
    <div class="plan-groups">${chunks}</div>
  `;
}

function renderEstimateNotices(estimate) {
  const warnings = Array.isArray(estimate.warnings) ? estimate.warnings : [];
  const recommendations = Array.isArray(estimate.recommendations) ? estimate.recommendations : [];
  const warningItems = warnings.map((warning) => {
    const label = warning === "chunk-count-extrapolated"
      ? "Some chunk timings are extrapolated from smaller batches."
      : String(warning || "").replaceAll("-", " ");
    return `<span class="plan-warning">${escapeHtml(label)}</span>`;
  }).join("");
  const recommendationItems = recommendations.map((item) => {
    const label = item.type === "enable-parallel-chunks"
      ? item.label || "Enable parallel cached lip-sync chunks."
      : item.label || item.type || "Recommendation";
    const timing = item.estimated_wall_seconds
      ? ` ${Number(item.estimated_wall_seconds).toFixed(1)}s wall, ${Number(item.estimated_saved_seconds || 0).toFixed(1)}s faster est.`
      : "";
    const command = item.command ? ` <code>${escapeHtml(item.command)}</code>` : "";
    return `<span class="plan-recommendation">${escapeHtml(label)}${escapeHtml(timing)}${command}</span>`;
  }).join("");
  if (!warningItems && !recommendationItems) {
    return "";
  }
  return `<div class="plan-notices">${warningItems}${recommendationItems}</div>`;
}

async function refreshCachedLipSyncEstimate() {
  if (!cachedLipSyncEstimateEl) {
    return;
  }
  try {
    const estimate = await requestJson("/api/cached-lipsync-estimate", {
      method: "POST",
      body: JSON.stringify(cachedLipSyncPayload())
    });
    renderCachedLipSyncEstimate(estimate);
  } catch (error) {
    cachedLipSyncEstimateEl.textContent = error.message;
  }
}

async function warmMatrixCache() {
  statusLine.textContent = "Planning cache warm...";
  try {
    const warm = await requestJson("/api/matrix-cache-warm", {
      method: "POST",
      body: JSON.stringify(matrixPayload())
    });
    if (warm.dry_run) {
      statusLine.textContent = `Cache warm dry run: ${warm.warm_job_count} to run, ${warm.skipped_group_count} already warm`;
    } else {
      statusLine.textContent = `Queued ${warm.jobs?.length || 0} cache warm jobs, skipped ${warm.skipped_group_count}`;
      await refreshJobs();
    }
    renderMatrixPlan(warm.plan);
  } catch (error) {
    statusLine.textContent = error.message;
  }
}

async function warmRenderMatrix() {
  statusLine.textContent = "Planning warm + render pipeline...";
  try {
    const pipeline = await requestJson("/api/matrix-warm-render", {
      method: "POST",
      body: JSON.stringify(productionMatrixPayload())
    });
    if (pipeline.dry_run) {
      statusLine.textContent = `Warm + render dry run: ${pipeline.warm_job_count} warm jobs, ${pipeline.render_job_count} render jobs`;
    } else {
      statusLine.textContent = `Queued ${pipeline.pipeline_job?.id}: ${pipeline.warm_job_count} warm jobs, ${pipeline.render_job_count} render jobs`;
      await refreshJobs();
    }
    renderMatrixPlan(pipeline.plan);
  } catch (error) {
    statusLine.textContent = error.message;
  }
}

async function promoteBatch() {
  statusLine.textContent = "Queueing batch promotion...";
  try {
    const payload = await requestJson("/api/promote-batch", {
      method: "POST",
      body: JSON.stringify({
        batch_result: promoteBatchResultInput?.value || "",
        texture_size: Number(promoteTextureSizeInput?.value || 768)
      })
    });
    statusLine.textContent = `Queued ${payload.job?.id || "promotion"}`;
    await refreshJobs();
  } catch (error) {
    statusLine.textContent = error.message;
  }
}

async function queueCachedLipSyncBatch() {
  statusLine.textContent = "Queueing promoted lip-sync batch...";
  try {
    const payload = await requestJson("/api/cached-lipsync-batch", {
      method: "POST",
      body: JSON.stringify(cachedLipSyncPayload())
    });
    const queuedId = payload.pipeline_job?.id || payload.job?.id || "cached lip-sync batch";
    const chunkDetail = payload.chunked ? ` · ${payload.chunk_count} chunks` : "";
    statusLine.textContent = `Queued ${queuedId}${chunkDetail}`;
    await refreshJobs();
    await refreshCachedLipSyncEstimate();
  } catch (error) {
    statusLine.textContent = error.message;
  }
}

async function queuePhrasebankThumbnailBatch(options = {}) {
  statusLine.textContent = "Queueing phrase-bank thumbnail batch...";
  try {
    const payload = await requestJson("/api/phrasebank-thumbnail-batch", {
      method: "POST",
      body: JSON.stringify({
        batch_id: cachedLipSyncBatchIdInput?.value || "web-thumb",
        count: Number(cachedLipSyncCountInput?.value || 16),
        chunked: Boolean(cachedLipSyncChunkedInput?.checked),
        publish_combined: !Boolean(cachedLipSyncFastPublishInput?.checked),
        render_cache_ready: Boolean(options.renderCacheReady),
        estimated_wall_seconds: Number(options.estimatedWallSeconds || 0)
      })
    });
    statusLine.textContent = `Queued ${payload.job?.id || "phrase-bank thumbnail batch"}`;
    await refreshJobs();
  } catch (error) {
    statusLine.textContent = error.message;
  }
}

async function refreshCombinedGallery() {
  statusLine.textContent = "Queueing catalog refresh...";
  try {
    const payload = await requestJson("/api/refresh-combined-gallery", {
      method: "POST",
      body: JSON.stringify({})
    });
    statusLine.textContent = `Queued ${payload.job?.id || "catalog refresh"}`;
    await refreshJobs();
  } catch (error) {
    statusLine.textContent = error.message;
  }
}

function scheduleMatrixPlan() {
  clearTimeout(matrixPlanTimer);
  matrixPlanTimer = setTimeout(refreshMatrixPlan, 250);
}

function scheduleCachedLipSyncEstimate() {
  clearTimeout(cachedLipSyncEstimateTimer);
  cachedLipSyncEstimateTimer = setTimeout(refreshCachedLipSyncEstimate, 250);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  statusLine.textContent = "Queueing...";
  try {
    const payload = await requestJson("/api/jobs", {
      method: "POST",
      body: JSON.stringify(formPayload())
    });
    statusLine.textContent = `Queued ${payload.job.id}`;
    await refreshJobs();
  } catch (error) {
    statusLine.textContent = error.message;
  }
});

refreshButton.addEventListener("click", refreshJobs);
refreshGalleriesButton?.addEventListener("click", async () => {
  try {
    await refreshGalleries();
    statusLine.textContent = "Recent galleries refreshed";
  } catch (error) {
    statusLine.textContent = error.message;
  }
});
recentGalleriesEl?.addEventListener("click", async (event) => {
  const filterButton = event.target.closest("[data-gallery-filter]");
  if (filterButton) {
    activeGalleryFilter = filterButton.dataset.galleryFilter || "all";
    renderRecentGalleries(latestGalleriesPayload);
    return;
  }
  const button = event.target.closest("[data-gallery-action]");
  if (!button) {
    return;
  }
  try {
    await handleRecentGalleryAction(button);
  } catch (error) {
    statusLine.textContent = error.message;
  }
});
jobFiltersEl?.addEventListener("click", (event) => {
  const button = event.target.closest("[data-job-filter]");
  if (!button) {
    return;
  }
  activeJobFilter = button.dataset.jobFilter || "all";
  renderJobs(latestJobsPayload);
});
form.addEventListener("input", () => {
  updateMatrixCount();
  updateCachedLipSyncCountLimit();
  scheduleMatrixPlan();
  scheduleCachedLipSyncEstimate();
});
form.addEventListener("change", () => {
  updateMatrixCount();
  updateCachedLipSyncCountLimit();
  scheduleMatrixPlan();
  scheduleCachedLipSyncEstimate();
});
previewMatrixButton.addEventListener("click", refreshMatrixPlan);
warmMatrixCacheButton.addEventListener("click", warmMatrixCache);
warmRenderMatrixButton.addEventListener("click", warmRenderMatrix);
promoteBatchButton?.addEventListener("click", promoteBatch);
cachedLipSyncButton?.addEventListener("click", queueCachedLipSyncBatch);
phrasebankThumbnailButton?.addEventListener("click", queuePhrasebankThumbnailBatch);
refreshCombinedGalleryButton?.addEventListener("click", refreshCombinedGallery);
cachedLipSyncCacheSelect?.addEventListener("change", () => {
  applyLipSyncCacheSelection();
  scheduleCachedLipSyncEstimate();
});
refreshPlacementButton?.addEventListener("click", async () => {
  try {
    await refreshPlacementAssets();
    statusLine.textContent = "Placement assets refreshed";
  } catch (error) {
    statusLine.textContent = error.message;
  }
});
placementPlanButton?.addEventListener("click", async () => {
  try {
    await buildPlacementPlan();
    statusLine.textContent = "Placement plan ready";
  } catch (error) {
    statusLine.textContent = error.message;
  }
});
placementSuggestButton?.addEventListener("click", async () => {
  try {
    await suggestPlacementOverrides();
    statusLine.textContent = "Placement suggestion ready";
  } catch (error) {
    statusLine.textContent = error.message;
  }
});
refreshCharactersButton?.addEventListener("click", async () => {
  try {
    await refreshCharacters();
    statusLine.textContent = "Character browser refreshed";
  } catch (error) {
    statusLine.textContent = error.message;
  }
});
characterSearchInput?.addEventListener("input", () => {
  characterPage = 1;
  clearTimeout(characterSearchInput._timer);
  characterSearchInput._timer = setTimeout(() => refreshCharacters().catch((error) => {
    statusLine.textContent = error.message;
  }), 250);
});
characterPrioritySelect?.addEventListener("change", () => {
  characterPage = 1;
  refreshCharacters().catch((error) => {
    statusLine.textContent = error.message;
  });
});
characterLipSelect?.addEventListener("change", () => {
  characterPage = 1;
  refreshCharacters().catch((error) => {
    statusLine.textContent = error.message;
  });
});
characterSortSelect?.addEventListener("change", () => {
  characterPage = 1;
  refreshCharacters().catch((error) => {
    statusLine.textContent = error.message;
  });
});
characterPrevButton?.addEventListener("click", () => {
  characterPage = Math.max(1, characterPage - 1);
  refreshCharacters().catch((error) => {
    statusLine.textContent = error.message;
  });
});
characterNextButton?.addEventListener("click", () => {
  const pageCount = latestCharacterPayload?.pagination?.page_count || characterPage + 1;
  characterPage = Math.min(pageCount, characterPage + 1);
  refreshCharacters().catch((error) => {
    statusLine.textContent = error.message;
  });
});
characterTagsEl?.addEventListener("click", (event) => {
  const button = event.target.closest("[data-character-tag]");
  if (!button) {
    return;
  }
  activeCharacterTag = button.dataset.characterTag || "";
  characterPage = 1;
  refreshCharacters().catch((error) => {
    statusLine.textContent = error.message;
  });
});
batchButton.addEventListener("click", async () => {
  statusLine.textContent = "Queueing batch...";
  try {
    const payload = await requestJson("/api/batch-jobs", {
      method: "POST",
      body: JSON.stringify(batchPayload())
    });
    statusLine.textContent = `Queued ${payload.jobs.length} jobs`;
    await refreshJobs();
  } catch (error) {
    statusLine.textContent = error.message;
  }
});
matrixButton.addEventListener("click", async () => {
  statusLine.textContent = "Queueing matrix...";
  try {
    const payload = await requestJson("/api/matrix-jobs", {
      method: "POST",
      body: JSON.stringify(matrixPayload())
    });
    statusLine.textContent = `Queued ${payload.jobs.length} matrix jobs`;
    await refreshJobs();
  } catch (error) {
    statusLine.textContent = error.message;
  }
});
syncGodotButton.addEventListener("click", async () => {
  statusLine.textContent = "Syncing Godot...";
  try {
    const payload = await requestJson("/api/godot/sync", {method: "POST", body: "{}"});
    const assetCount = payload.reload?.asset_count ?? payload.export?.exported?.length ?? 0;
    const skipped = payload.export?.skipped?.length ?? 0;
    statusLine.textContent = `Godot sync ${payload.status}: ${assetCount} assets, ${skipped} skipped`;
    await refreshGodotStageStatus();
  } catch (error) {
    statusLine.textContent = error.message;
  }
});
document.addEventListener("click", async (event) => {
  const loadCharacter = event.target.closest("[data-character-load]");
  const talkCharacter = event.target.closest("[data-character-talk]");
  if (loadCharacter || talkCharacter) {
    const id = (loadCharacter || talkCharacter).dataset.characterLoad || (loadCharacter || talkCharacter).dataset.characterTalk;
    try {
      await requestJson("/api/godot/load", {
        method: "POST",
        body: JSON.stringify({id})
      });
      if (talkCharacter?.dataset.timeline) {
        const payload = await requestJson("/api/godot/lipsync", {
          method: "POST",
          body: JSON.stringify({path: talkCharacter.dataset.timeline})
        });
        statusLine.textContent = `Godot talking ${id}: ${payload.cue_count || 0} cues`;
      } else {
        statusLine.textContent = `Godot loaded ${id}`;
      }
      await refreshGodotStageStatus();
    } catch (error) {
      statusLine.textContent = error.message;
    }
    return;
  }
  const button = event.target.closest("[data-godot-stage-action]");
  if (!button) {
    return;
  }
  const payload = stagePayload(button);
  if (!payload) {
    return;
  }
  try {
    const response = await requestJson(payload.url, {
      method: "POST",
      body: JSON.stringify(payload.body)
    });
    statusLine.textContent = `Godot ${payload.label}: ${response.status || "ok"}`;
    await refreshGodotStageStatus();
  } catch (error) {
    statusLine.textContent = error.message;
  }
});
document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-godot-action]");
  if (!button) {
    return;
  }
  const id = button.dataset.jobId;
  const action = button.dataset.godotAction;
  try {
    if (action === "timeline" && button.dataset.timeline) {
      const payload = await requestJson("/api/godot/lipsync", {
        method: "POST",
        body: JSON.stringify({path: button.dataset.timeline})
      });
      statusLine.textContent = `Godot timeline ${id}: ${payload.cue_count || 0} cues`;
    } else {
      await requestJson("/api/godot/load", {
        method: "POST",
        body: JSON.stringify({id})
      });
      if (action === "talk" && button.dataset.timeline) {
        const payload = await requestJson("/api/godot/lipsync", {
          method: "POST",
          body: JSON.stringify({path: button.dataset.timeline})
        });
        statusLine.textContent = `Godot talking ${id}: ${payload.cue_count || 0} cues`;
      } else {
        statusLine.textContent = `Godot loaded ${id}`;
      }
    }
    await refreshGodotStageStatus();
  } catch (error) {
    statusLine.textContent = error.message;
  }
});
refreshJobs();
refreshGalleries().catch((error) => {
  console.warn(error);
});
refreshStorageStats();
loadOptions();
refreshPlacementAssets().catch((error) => {
  console.warn(error);
});
refreshLipSyncCache().catch((error) => {
  console.warn(error);
});
refreshCharacters().catch((error) => {
  console.warn(error);
});
updateMatrixCount();
refreshMatrixPlan();
refreshCachedLipSyncEstimate();
refreshGodotStageStatus();
setInterval(refreshJobs, 5000);
setInterval(refreshGalleries, 15000);
setInterval(refreshStorageStats, 30000);
setInterval(refreshGodotStageStatus, 8000);
