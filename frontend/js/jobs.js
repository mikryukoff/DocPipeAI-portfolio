import {
    cancelJob,
    createUpdatesSocket,
    getUndefinedSpecNames,
    saveSpecSections,
} from "./api.js";
import { confirmDialog } from "./dialogs.js";
import { renderEmbedmentGroup } from "./embedments.js";
import { renderPipelinesList } from "./pipelines.js";
import { buildProblemFilesWithReasons } from "./error-reasons.js";
import { t } from "./messages.js";

const ACTIVE_JOB_KEY = "active_job_id";
const FINISHED_JOB_KEY = "finished_job_snapshot";
const GLOBAL_ACTIVE_JOB_KEY = "active_job_id_global";
const GLOBAL_FINISHED_JOB_KEY = "finished_job_snapshot_global";
/** После «Закрыть» не восстанавливать этот итог после F5 (scoped по пользователю). */
const DISMISSED_FINISHED_JOB_ID_KEY = "dismissed_finished_job_id";
let activeSocket = null;
let reconnectTimer = null;
let watchedJobId = null;
let socketJobId = null;
let lastPipelinesKey = "";
let allowedSections = [];
let allowedTables = [];
/** @type {Record<string, string[]>} */
let tableToSections = {};
let userUndefinedSectionLabel = "Не определен пользователем";
let saveSpecSectionsBound = false;
let lastUndefinedRenderKey = "";
let lastJobEmbedmentRenderKey = "";
const undefinedSelectedTable = new Map();
const undefinedSelectedSection = new Map();
const undefinedCustomKeys = new Map();
const undefinedFullNames = new Map();
const undefinedUnknownClicked = new Set();
let viewerRole = null;
let viewerUserId = null;
let onProcessingStateChange = null;
let lastLoggedJobStatus = null;
let invalidFilesExpanded = false;
let lastInvalidFilesKey = "";
let cancelInFlight = false;
let currentRenderedJobId = null;
let lastRenderedJobSnapshot = null;
let lastLoggedProgressStep = -1;
let lastLoggedFileKey = "";
let lastLoggedInvalidFilesCount = 0;
/** После успеха/ошибки показываем итог (прогресс, статистика, текст), пока не начнётся новая задача или не уйдут с раздела. */
let showFinishedJobSummary = false;

function isTerminalJobStatus(job) {
    const status = String(job?.status || "").toLowerCase();
    return status === "done" || status === "error";
}

function setJobCloseVisible(isVisible) {
    const closeBtn = document.getElementById("jobCloseBtn");
    if (!closeBtn) return;
    closeBtn.classList.toggle("hidden", !isVisible);
}

function getScopedStorageKey(baseKey) {
    const uid = Number(viewerUserId);
    if (Number.isFinite(uid) && uid > 0) {
        return `${baseKey}_${uid}`;
    }
    return baseKey;
}

function getActiveJobKey() {
    return getScopedStorageKey(ACTIVE_JOB_KEY);
}

function getFinishedJobKey() {
    return getScopedStorageKey(FINISHED_JOB_KEY);
}

function getGlobalActiveJobKey() {
    return GLOBAL_ACTIVE_JOB_KEY;
}

function getGlobalFinishedJobKey() {
    return GLOBAL_FINISHED_JOB_KEY;
}

function getDismissedFinishedJobKey() {
    return getScopedStorageKey(DISMISSED_FINISHED_JOB_ID_KEY);
}

function clearDismissedFinishedJobId() {
    try {
        localStorage.removeItem(getDismissedFinishedJobKey());
    } catch {
        // ignore
    }
}

function readDismissedFinishedJobId() {
    try {
        const raw = localStorage.getItem(getDismissedFinishedJobKey());
        return raw != null && String(raw).trim() !== "" ? String(raw).trim() : null;
    } catch {
        return null;
    }
}

function setDismissedFinishedJobId(jobId) {
    if (jobId === null || jobId === undefined || jobId === "") {
        return;
    }
    try {
        localStorage.setItem(getDismissedFinishedJobKey(), String(jobId));
    } catch {
        // ignore
    }
}

function dropStaleWatchedJob() {
    localStorage.removeItem(getActiveJobKey());
    localStorage.removeItem(getFinishedJobKey());
    localStorage.removeItem(getGlobalActiveJobKey());
    watchedJobId = null;
    currentRenderedJobId = null;
    lastRenderedJobSnapshot = null;
    showFinishedJobSummary = false;
    clearReconnect();
    stopSocket();
    resetJobUi({ hideSection: true, clearActivity: true });
    setJobLiveIndicator(false);
    setProcessingState(false);
    connectSocket(null);
}

function saveFinishedJobSnapshot(job) {
    if (!job || (job.status !== "done" && job.status !== "error")) {
        return;
    }
    try {
        const snapshot = {
            ...job,
            __saved_at: Date.now(),
            __owner_user_id: viewerUserId ?? null,
        };
        localStorage.setItem(getFinishedJobKey(), JSON.stringify(snapshot));
        localStorage.setItem(getGlobalFinishedJobKey(), JSON.stringify(snapshot));
    } catch {
        // ignore storage errors
    }
}

function parseFinishedSnapshot(raw) {
    if (!raw) return null;
    try {
        const parsed = JSON.parse(raw);
        if (!parsed || (parsed.status !== "done" && parsed.status !== "error")) {
            return null;
        }
        return parsed;
    } catch {
        return null;
    }
}

function restoreFinishedJobSnapshot() {
    try {
        const dismissedId = readDismissedFinishedJobId();
        const scoped = parseFinishedSnapshot(localStorage.getItem(getFinishedJobKey()));
        const globalSnapshot = parseFinishedSnapshot(localStorage.getItem(getGlobalFinishedJobKey()));
        const scopedTs = Number(scoped?.__saved_at || 0);
        const globalTs = Number(globalSnapshot?.__saved_at || 0);
        const job = globalTs >= scopedTs ? (globalSnapshot || scoped) : (scoped || globalSnapshot);
        if (!job) {
            localStorage.removeItem(getFinishedJobKey());
            return false;
        }
        const jid = job.job_id != null ? String(job.job_id) : "";
        if (dismissedId && jid && dismissedId === jid) {
            localStorage.removeItem(getFinishedJobKey());
            localStorage.removeItem(getGlobalFinishedJobKey());
            return false;
        }
        showFinishedJobSummary = true;
        const section = document.getElementById("jobSection");
        if (section) {
            section.classList.remove("hidden");
        }
        bindJobActionButtons();
        renderJob(job);
        return true;
    } catch {
        localStorage.removeItem(getFinishedJobKey());
        return false;
    }
}

function toBaseName(pathLike) {
    if (!pathLike || typeof pathLike !== "string") return "";
    const chunks = pathLike.split(/[\\/]/);
    return chunks[chunks.length - 1] || pathLike;
}

function getCompactJobMetrics(job) {
    const stats = job?.stats || {};
    const filesProcessed = Number(
        stats.files_processed
        ?? stats.processed_files
        ?? stats.processed_pairs
        ?? 0,
    ) || 0;
    const filesTotal = Number(
        stats.files_total
        ?? stats.total_files
        ?? stats.total_pairs
        ?? filesProcessed
        ?? 0,
    ) || 0;
    const pipelinesTotal = Number(
        stats.pipelines_total
        ?? stats.pipelines
        ?? stats.flow_direction_updated_pipelines
        ?? stats.parameters_updated_pipelines
        ?? 0,
    ) || 0;
    const specItemsTotal = Number(
        stats.spec_items_total
        ?? stats.spec_items
        ?? stats.armature_updated_rows
        ?? 0,
    ) || 0;
    const currentFile = toBaseName(String(stats.current_file || stats.current_excel_file || ""));
    return {
        filesProcessed,
        filesTotal,
        pipelinesTotal,
        specItemsTotal,
        currentFile,
    };
}

function maybeLogDetailedProgress(job, metrics) {
    if (job.status !== "processing") {
        return;
    }
    if (metrics.currentFile && metrics.filesTotal > 0) {
        const currentIndex = Math.min(
            metrics.filesTotal,
            Math.max(1, metrics.filesProcessed + 1),
        );
        const fileKey = `${metrics.currentFile}|${currentIndex}|${metrics.filesTotal}`;
        if (fileKey !== lastLoggedFileKey) {
            appendActivityLog(
                t("job.activityProcessingFile", {
                    file: metrics.currentFile,
                    current: currentIndex,
                    total: metrics.filesTotal,
                }),
                "info",
            );
            lastLoggedFileKey = fileKey;
        }
    }
    const progress = Number(job.progress || 0);
    const step = Math.floor(progress / 25);
    if (progress > 0 && progress < 100 && step > lastLoggedProgressStep) {
        appendActivityLog(t("job.activityProgress", { percent: Math.round(progress) }), "info");
        lastLoggedProgressStep = step;
    }
}

export function setJobsViewerRole(role) {
    viewerRole = role || null;
}

export function setJobsViewerUserId(userId) {
    const parsed = Number(userId);
    viewerUserId = Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

export function setJobProcessingStateListener(listener) {
    onProcessingStateChange = typeof listener === "function" ? listener : null;
}

export function pushActivityLog(message, tone = "info") {
    appendActivityLog(message, tone);
}

/** Скрыть блок обработки и сбросить статистику (уход с «Импорта», если нет активной задачи). */
export function clearFinishedJobDisplay() {
    if (watchedJobId) {
        return;
    }
    showFinishedJobSummary = false;
    resetJobUi({ hideSection: true, clearActivity: true });
}

/** Полный сброс при выходе из системы (в т.ч. если обработка ещё шла). */
export function discardImportJobUi() {
    showFinishedJobSummary = false;
    localStorage.removeItem(getActiveJobKey());
    localStorage.removeItem(getFinishedJobKey());
    localStorage.removeItem(getGlobalActiveJobKey());
    clearDismissedFinishedJobId();
    watchedJobId = null;
    lastRenderedJobSnapshot = null;
    clearReconnect();
    stopSocket();
    resetJobUi({ hideSection: true, clearActivity: true });
    connectSocket(null);
}

export function hasWatchedJob() {
    return Number.isFinite(Number(watchedJobId)) && Number(watchedJobId) > 0;
}

export function startLiveUpdates() {
    if (activeSocket) {
        return;
    }
    connectSocket(watchedJobId);
}

export function watchJob(jobId) {
    if (jobId !== null && jobId !== undefined) {
        localStorage.setItem(getActiveJobKey(), String(jobId));
        localStorage.setItem(getGlobalActiveJobKey(), String(jobId));
        localStorage.removeItem(getFinishedJobKey());
        localStorage.removeItem(getGlobalFinishedJobKey());
        clearDismissedFinishedJobId();
        watchedJobId = Number(jobId);
    }
    if (!activeSocket || socketJobId !== watchedJobId) {
        stopSocket();
        clearReconnect();
        connectSocket(watchedJobId);
    }
}

export function resumeActiveJob() {
    const rawJobId = localStorage.getItem(getActiveJobKey()) || localStorage.getItem(getGlobalActiveJobKey());
    if (!rawJobId) {
        restoreFinishedJobSnapshot();
        return;
    }

    const jobId = Number(rawJobId);
    if (!Number.isFinite(jobId) || jobId <= 0) {
        localStorage.removeItem(getActiveJobKey());
        localStorage.removeItem(getGlobalActiveJobKey());
        restoreFinishedJobSnapshot();
        return;
    }

    watchJob(jobId);
}

function renderPipelines(items) {
    const key = Array.isArray(items) ? items.join("||") : "";
    if (key === lastPipelinesKey) {
        return;
    }
    lastPipelinesKey = key;
    renderPipelinesList(items);
}

function connectSocket(jobId) {
    const section = document.getElementById("jobSection");
    if (jobId === null || jobId === undefined) {
        if (!showFinishedJobSummary) {
            resetJobUi({ hideSection: true, clearActivity: true });
        }
    } else {
        showFinishedJobSummary = false;
        section.classList.remove("hidden");
    }
    const shouldResetJobUi = jobId !== null && jobId !== undefined;
    if (shouldResetJobUi) {
        setJobCloseVisible(false);
        resetJobUi({ hideSection: false, clearActivity: true });
        appendActivityLog(t("job.activityStart"), "info");
        setJobLiveIndicator(true);
        setProcessingState(true);
    }

    bindJobActionButtons();

    socketJobId = jobId ?? null;
    activeSocket = createUpdatesSocket(socketJobId);

    activeSocket.onmessage = (event) => {
        let payload;
        try {
            payload = JSON.parse(event.data);
        } catch {
            return;
        }

        if (Array.isArray(payload.pipeline_names)) {
            renderPipelines(payload.pipeline_names);
        }

        const job = payload.job;
        if (!job) {
            currentRenderedJobId = null;
            if (watchedJobId) {
                if (lastRenderedJobSnapshot && isTerminalJobStatus(lastRenderedJobSnapshot)) {
                    // Сервер уже удалил задачу из активных, но финальный снимок у нас есть — оставляем его на экране.
                    finishWatch(lastRenderedJobSnapshot);
                    return;
                }
                // Сохранился старый active_job_id, но задачи уже нет (после перезапуска/очистки).
                dropStaleWatchedJob();
                return;
            }
            if (!watchedJobId && !showFinishedJobSummary) {
                resetJobUi({ hideSection: true, clearActivity: true });
                setProcessingState(false);
            }
            return;
        }
        if (watchedJobId && job.job_id !== watchedJobId) {
            return;
        }
        renderJob(job);
    };

    activeSocket.onerror = () => {
        if (activeSocket) {
            activeSocket.close();
        }
    };

    activeSocket.onclose = (event) => {
        activeSocket = null;
        if (event && (event.code === 4401 || event.code === 4403 || event.code === 1008)) {
            return;
        }
        scheduleReconnect();
    };
}

function renderJob(job) {
    const bar = document.getElementById("progressBar");
    const text = document.getElementById("progressText");
    const pages = document.getElementById("statPages");
    const pipelines = document.getElementById("statPipelines");
    const specs = document.getElementById("statSpecs");
    const time = document.getElementById("statTime");
    const error = document.getElementById("jobError");
    const warn = document.getElementById("jobWarnings");
    const statusText = document.getElementById("jobStatusText");
    const cancelBtn = document.getElementById("jobCancelBtn");
    const invalidSection = document.getElementById("invalidSection");
    const invalidSummary = document.getElementById("invalidSummary");
    const invalidList = document.getElementById("invalidList");
    const invalidToggleBtn = document.getElementById("invalidToggleBtn");
    const metrics = getCompactJobMetrics(job);
    lastRenderedJobSnapshot = job;
    currentRenderedJobId = Number(job?.job_id || 0) || null;
    const cancelledByUser = Boolean(job?.stats?.cancel_requested)
        || String(job?.error || "").toLowerCase().includes("cancel");
    if (cancelBtn) {
        const canCancel = (job.status === "processing" || job.status === "pending") && !cancelledByUser;
        cancelBtn.classList.toggle("hidden", !canCancel);
        cancelBtn.disabled = cancelInFlight || !canCancel;
    }

    bar.style.width = `${job.progress}%`;
    text.textContent = t("common.percent", { value: job.progress });
    warn.textContent = "";
    warn.dataset.tone = "warn";
    error.dataset.tone = "error";

    if (job.stats) {
        const filesProcessed =
            job.stats.files_processed != null
                ? job.stats.files_processed
                : job.stats.processed_files != null
                  ? job.stats.processed_files
                  : job.stats.processed_pairs != null
                    ? job.stats.processed_pairs
                    : 0;
        const filesTotal =
            job.stats.files_total != null
                ? job.stats.files_total
                : job.stats.total_files != null
                  ? job.stats.total_files
                  : job.stats.total_pairs != null
                    ? job.stats.total_pairs
                    : filesProcessed || 0;
        if (filesTotal) {
            let line = t("job.filesProgress", { processed: filesProcessed, total: filesTotal });
            const tp = job.stats.total_pages;
            const pp = job.stats.processed_pages;
            if (tp && pp != null) {
                line += ` · ${t("job.ocrPagesSuffix", { cur: pp, total: tp })}`;
            } else if (job.stats.total_pairs != null && job.stats.processed_pairs != null) {
                line += ` · ${t("job.ocrPairsSuffix", { cur: job.stats.processed_pairs, total: job.stats.total_pairs })}`;
            }
            pages.textContent = line;
        }

        const pipelinesValue =
            job.stats.pipelines_total
            ?? job.stats.pipelines
            ?? job.stats.flow_direction_updated_pipelines
            ?? job.stats.parameters_updated_pipelines;
        if (pipelinesValue !== undefined && pipelinesValue !== null) {
            pipelines.textContent = pipelinesValue;
        }

        const specsValue =
            job.stats.spec_items_total
            ?? job.stats.spec_items
            ?? job.stats.armature_updated_rows;
        if (specsValue !== undefined && specsValue !== null) {
            specs.textContent = specsValue;
        }

        if (job.stats.duration_sec !== undefined && job.stats.duration_sec !== null) {
            time.textContent = Number(job.stats.duration_sec).toFixed(1);
        }
    }

    if (job.status === "error") {
        refreshJobEmbedmentPendingSection([], false);
        const sectionEl = document.getElementById("jobSection");
        if (sectionEl) {
            sectionEl.dataset.summary = "error";
        }
        if (cancelledByUser) {
            error.textContent = "";
            statusText.textContent = t("job.processingCancelled");
            appendJobStatusLog(t("job.activityCancelled"), "warn", "cancelled");
        } else {
            const backendError = String(job?.error || "").trim();
            error.textContent = backendError || t("job.processingError");
            statusText.textContent = t("job.processingErrorFinal");
            appendJobStatusLog(t("job.activityError"), "error", job.status);
        }
        setJobLiveIndicator(false);
        setProcessingState(false);
        if (job.progress != null) {
            bar.style.width = `${job.progress}%`;
            text.textContent = t("common.percent", { value: job.progress });
        }
        finishWatch(job);
        return;
    }

    if (job.stats && (Array.isArray(job.stats.invalid_rows) || Array.isArray(job.stats.blocked_pipelines))) {
        const blocked = Array.isArray(job.stats.blocked_pipelines) ? job.stats.blocked_pipelines : [];
        const invalidRows = Array.isArray(job.stats.invalid_rows) ? job.stats.invalid_rows : [];

        if (blocked.length || invalidRows.length) {
            const problemFilesWithReasons = buildProblemFilesWithReasons(invalidRows, t);
            const problemFiles = problemFilesWithReasons.map((item) => item.fileName);
            invalidSection.classList.remove("hidden");
            const invalidKey = problemFilesWithReasons
                .map((item) => `${item.fileName}:${item.reasons.join("|")}`)
                .join("||");
            if (invalidKey !== lastInvalidFilesKey) {
                lastInvalidFilesKey = invalidKey;
                invalidFilesExpanded = false;
                invalidList.innerHTML = "";
                for (const item of problemFilesWithReasons) {
                    const li = document.createElement("li");
                    if (item.reasons.length) {
                        li.textContent = t("job.fileWithReasonsPrefix", {
                            name: item.fileName,
                            reasons: item.reasons.join("; "),
                        });
                    } else {
                        li.textContent = t("job.filePrefix", { name: item.fileName });
                    }
                    invalidList.appendChild(li);
                }
            }
            if (problemFiles.length !== lastLoggedInvalidFilesCount) {
                appendActivityLog(t("job.activityInvalidFilesCount", { count: problemFiles.length }), "warn");
                lastLoggedInvalidFilesCount = problemFiles.length;
            }
            invalidSummary.textContent = t("job.invalidFilesCountOnly", { count: problemFiles.length });
            if (invalidToggleBtn) {
                invalidToggleBtn.classList.remove("hidden");
                invalidToggleBtn.textContent = invalidFilesExpanded
                    ? t("job.hideInvalidFiles")
                    : t("job.showInvalidFiles");
            }
            invalidList.classList.toggle("hidden", !invalidFilesExpanded);
        } else {
            invalidSection.classList.add("hidden");
            invalidSummary.textContent = "";
            invalidList.innerHTML = "";
            invalidFilesExpanded = false;
            lastInvalidFilesKey = "";
            lastLoggedInvalidFilesCount = 0;
            if (invalidToggleBtn) {
                invalidToggleBtn.classList.add("hidden");
            }
        }
    } else {
        invalidSection.classList.add("hidden");
        invalidSummary.textContent = "";
        invalidList.innerHTML = "";
        invalidList.classList.add("hidden");
        invalidFilesExpanded = false;
        lastInvalidFilesKey = "";
        lastLoggedInvalidFilesCount = 0;
        if (invalidToggleBtn) {
            invalidToggleBtn.classList.add("hidden");
        }
    }

    const unresolvedFromStats =
        job.stats && Array.isArray(job.stats.undefined_spec_names)
            ? job.stats.undefined_spec_names
            : [];
    const unresolvedSources =
        job.stats && job.stats.undefined_spec_sources && typeof job.stats.undefined_spec_sources === "object"
            ? job.stats.undefined_spec_sources
            : {};
    const unresolvedFullNames =
        job.stats && job.stats.undefined_spec_full_names && typeof job.stats.undefined_spec_full_names === "object"
            ? job.stats.undefined_spec_full_names
            : {};
    void refreshUndefinedSpecSection(unresolvedFromStats, unresolvedSources, unresolvedFullNames);

    const embedmentPending =
        job.stats && Array.isArray(job.stats.embedment_pending)
            ? job.stats.embedment_pending
            : [];
    const waitingEmbedment =
        job.status === "processing" && Boolean(job.stats?.waiting_embedment_input);
    refreshJobEmbedmentPendingSection(embedmentPending, waitingEmbedment);

    if (job.status === "processing" && job.stats?.waiting_embedment_input) {
        const n = Number(
            job.stats?.embedment_pending_total || embedmentPending.length || 0,
        );
        statusText.textContent =
            n > 0
                ? t("job.waitingEmbedmentInputCount", { count: n })
                : t("job.waitingEmbedmentInput");
        appendJobStatusLog(t("job.activityWaitingEmbedment"), "warn", "waiting_embedment_input");
        setJobLiveIndicator(true);
        setProcessingState(true);
        return;
    }

    if (job.status === "processing" && job.stats?.waiting_user_input) {
        const pending = Number(job.stats?.undefined_spec_names_total || unresolvedFromStats.length || 0);
        statusText.textContent =
            pending > 0
                ? t("job.waitingUserInputCount", { count: pending })
                : t("job.waitingUserInput");
        appendJobStatusLog(t("job.activityWaitingInput"), "warn", "waiting_user_input");
        setJobLiveIndicator(true);
        setProcessingState(true);
        return;
    }

    if (job.status === "pending") {
        statusText.textContent = t("job.processingPending");
        appendJobStatusLog(t("job.activityPending"), "info", "pending");
        setJobLiveIndicator(true);
        setProcessingState(true);
        return;
    }

    if (job.status === "processing") {
        statusText.textContent = t("job.processingLive");
        appendJobStatusLog(t("job.activityProcessing"), "info", "processing");
        maybeLogDetailedProgress(job, metrics);
        setJobLiveIndicator(true);
        setProcessingState(true);
    }

    if (job.status === "done") {
        error.textContent = "";
        const sectionEl = document.getElementById("jobSection");
        if (sectionEl) {
            sectionEl.dataset.summary = "success";
        }
        const source = job.stats?.source || "file";
        if (source === "excel") {
            statusText.textContent = t("job.processingCompletedExcel");
        } else if (source === "word") {
            statusText.textContent = t("job.processingCompletedWord");
        } else if (source === "ocr_pdf" || source === "ocr_standalone") {
            statusText.textContent = t("job.processingCompletedOcr");
        } else {
            statusText.textContent = t("job.processingCompletedPdf");
        }
        bar.style.width = "100%";
        text.textContent = t("common.percent", { value: 100 });
        appendJobStatusLog(
            t("job.activityDoneSummary", {
                processed: metrics.filesProcessed || metrics.filesTotal || 0,
                total: metrics.filesTotal || metrics.filesProcessed || 0,
                pipelines: metrics.pipelinesTotal,
                specItems: metrics.specItemsTotal,
            }),
            "success",
            job.status,
        );
        setJobLiveIndicator(false);
        setProcessingState(false);
        finishWatch(job);
    }
}

function embedmentJobMarkerKey(m) {
    return [
        m.pipeline_name,
        m.embedment_group_key,
        m.instrument_tag,
        m.crop_image_url,
        m.full_name,
    ].join("|");
}

function refreshJobEmbedmentPendingSection(markers, visible) {
    const sectionEl = document.getElementById("jobEmbedmentPendingSection");
    const summaryEl = document.getElementById("jobEmbedmentPendingSummary");
    const listEl = document.getElementById("jobEmbedmentPendingList");
    const msgEl = document.getElementById("jobEmbedmentPendingMsg");
    if (!sectionEl || !summaryEl || !listEl) {
        return;
    }

    const canEdit =
        viewerRole === "admin" || viewerRole === "engineer" || viewerRole === "demo";
    if (!visible || !markers.length || !canEdit) {
        sectionEl.classList.add("hidden");
        summaryEl.textContent = "";
        listEl.innerHTML = "";
        if (msgEl) {
            msgEl.textContent = "";
            msgEl.dataset.tone = "info";
        }
        lastJobEmbedmentRenderKey = "";
        return;
    }

    const renderKey = markers.map(embedmentJobMarkerKey).sort().join("||");
    if (renderKey === lastJobEmbedmentRenderKey) {
        sectionEl.classList.remove("hidden");
        return;
    }
    lastJobEmbedmentRenderKey = renderKey;

    sectionEl.classList.remove("hidden");
    summaryEl.textContent = t("job.embedmentPendingHelp");
    listEl.innerHTML = "";
    if (msgEl) {
        msgEl.textContent = "";
        msgEl.dataset.tone = "info";
    }

    for (const m of markers) {
        const pipelineName = (m.pipeline_name || "").trim();
        const pl = document.createElement("div");
        pl.className = "section-help";
        pl.textContent = t("job.embedmentPendingPipeline", { name: pipelineName || "—" });
        listEl.appendChild(pl);

        const group = {
            instrument_tag: m.instrument_tag,
            embedment_group_key: m.embedment_group_key,
            crop_image_url: m.crop_image_url,
            name: m.full_name,
            elements: Array.isArray(m.elements) && m.elements.length ? m.elements : [{}],
        };
        listEl.appendChild(
            renderEmbedmentGroup(pipelineName, group, { messageEl: msgEl }),
        );
    }
}

function scheduleReconnect() {
    clearReconnect();
    reconnectTimer = setTimeout(() => {
        connectSocket(watchedJobId);
    }, 1500);
}

function clearReconnect() {
    if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
    }
}

function stopSocket() {
    if (activeSocket) {
        activeSocket.onclose = null;
        activeSocket.onerror = null;
        activeSocket.onmessage = null;
        activeSocket.close();
        activeSocket = null;
    }
    socketJobId = null;
}

function finishWatch(job = null) {
    localStorage.removeItem(getActiveJobKey());
    localStorage.removeItem(getGlobalActiveJobKey());
    watchedJobId = null;
    clearReconnect();
    stopSocket();
    showFinishedJobSummary = true;
    saveFinishedJobSnapshot(job);
    currentRenderedJobId = null;
    lastRenderedJobSnapshot = job || lastRenderedJobSnapshot;
    cancelInFlight = false;
    setJobLiveIndicator(false);
    setProcessingState(false);
    setJobCloseVisible(true);
    connectSocket(null);
}

function bindJobActionButtons() {
    if (!saveSpecSectionsBound) {
        const saveBtn = document.getElementById("saveSpecSectionsBtn");
        if (saveBtn) {
            saveBtn.onclick = onSaveSpecSectionsClicked;
        }
        const cancelBtn = document.getElementById("jobCancelBtn");
        if (cancelBtn) {
            cancelBtn.onclick = onCancelJobClicked;
        }
        const invalidToggleBtn = document.getElementById("invalidToggleBtn");
        if (invalidToggleBtn) {
            invalidToggleBtn.onclick = () => {
                invalidFilesExpanded = !invalidFilesExpanded;
                const invalidList = document.getElementById("invalidList");
                invalidToggleBtn.textContent = invalidFilesExpanded
                    ? t("job.hideInvalidFiles")
                    : t("job.showInvalidFiles");
                if (invalidList) {
                    invalidList.classList.toggle("hidden", !invalidFilesExpanded);
                }
            };
        }
        const closeBtn = document.getElementById("jobCloseBtn");
        if (closeBtn) {
            closeBtn.onclick = () => {
                if (watchedJobId) {
                    return;
                }
                const jid =
                    lastRenderedJobSnapshot?.job_id ??
                    parseFinishedSnapshot(localStorage.getItem(getFinishedJobKey()))?.job_id ??
                    parseFinishedSnapshot(localStorage.getItem(getGlobalFinishedJobKey()))?.job_id;
                if (jid != null && jid !== "") {
                    setDismissedFinishedJobId(jid);
                }
                showFinishedJobSummary = false;
                localStorage.removeItem(getFinishedJobKey());
                localStorage.removeItem(getGlobalFinishedJobKey());
                resetJobUi({ hideSection: true, clearActivity: true });
                setProcessingState(false);
            };
        }
        saveSpecSectionsBound = true;
    }
}

async function onCancelJobClicked() {
    const jobId = watchedJobId || currentRenderedJobId;
    if (!jobId || cancelInFlight) {
        return;
    }
    if (!(await confirmDialog(t("job.cancelConfirm"), { confirmTone: "danger" }))) {
        return;
    }
    cancelInFlight = true;
    const cancelBtn = document.getElementById("jobCancelBtn");
    if (cancelBtn) {
        cancelBtn.disabled = true;
    }
    try {
        await cancelJob(jobId);
        appendActivityLog(t("job.cancelRequested"), "warn");
    } catch (err) {
        const warn = document.getElementById("jobWarnings");
        if (warn) {
            warn.textContent = err?.payload?.message || t("job.cancelFailed");
            warn.dataset.tone = "error";
        }
    } finally {
        cancelInFlight = false;
    }
}

async function refreshUndefinedSpecSection(preferredNames, preferredSources = {}, preferredFullNames = {}) {
    const sectionEl = document.getElementById("undefinedSpecSection");
    const summaryEl = document.getElementById("undefinedSpecSummary");
    const listEl = document.getElementById("undefinedSpecList");
    if (viewerRole !== "admin" && viewerRole !== "engineer" && viewerRole !== "demo") {
        sectionEl.classList.add("hidden");
        summaryEl.textContent = "";
        listEl.innerHTML = "";
        return;
    }
    const existingRows = listEl.querySelectorAll(".undefined-item");
    for (const row of existingRows) {
        const itemName = row.dataset.itemName;
        if (!itemName) {
            continue;
        }
        const tableSel = row.querySelector("select.undefined-table-select");
        const sectionSel = row.querySelector("select.undefined-section-select");
        if (tableSel?.value) {
            undefinedSelectedTable.set(itemName, tableSel.value);
        }
        if (sectionSel && !sectionSel.classList.contains("hidden") && sectionSel.value) {
            undefinedSelectedSection.set(itemName, sectionSel.value);
        }
    }

    let names = Array.isArray(preferredNames) ? preferredNames.filter(Boolean) : [];
    const sourceByName = { ...(preferredSources || {}) };
    const fullNameByName = { ...(preferredFullNames || {}) };
    for (const [name, fullName] of undefinedFullNames.entries()) {
        if (!fullNameByName[name]) {
            fullNameByName[name] = fullName;
        }
    }
    try {
        const data = await getUndefinedSpecNames();
        if (typeof data?.user_undefined_label === "string" && data.user_undefined_label.trim()) {
            userUndefinedSectionLabel = data.user_undefined_label.trim();
        }
        const rawAllowedSections = Array.isArray(data?.allowed_sections) ? data.allowed_sections : allowedSections;
        allowedSections = rawAllowedSections.filter((section) => section !== userUndefinedSectionLabel);
        const rawTables = Array.isArray(data?.allowed_tables) ? data.allowed_tables : [];
        allowedTables = rawTables.filter(Boolean);
        if (data?.table_to_sections && typeof data.table_to_sections === "object") {
            tableToSections = { ...data.table_to_sections };
        } else {
            tableToSections = {};
        }
        if (Array.isArray(data.undefined_names) && data.undefined_names.length) {
            const merged = new Set([...names, ...data.undefined_names]);
            names = Array.from(merged);
        }
        if (data?.undefined_full_names && typeof data.undefined_full_names === "object") {
            Object.assign(fullNameByName, data.undefined_full_names);
        }
    } catch {
        // ignore network errors in live updates
    }
    names = Array.from(new Set(names)).sort((a, b) => a.localeCompare(b));

    if (!names.length) {
        sectionEl.classList.add("hidden");
        summaryEl.textContent = "";
        listEl.innerHTML = "";
        lastUndefinedRenderKey = "";
        undefinedSelectedTable.clear();
        undefinedSelectedSection.clear();
        undefinedCustomKeys.clear();
        undefinedFullNames.clear();
        undefinedUnknownClicked.clear();
        return;
    }

    const namesSet = new Set(names);
    for (const key of Array.from(undefinedFullNames.keys())) {
        if (!namesSet.has(key)) {
            undefinedFullNames.delete(key);
        }
    }
    for (const key of Array.from(undefinedUnknownClicked.values())) {
        if (!namesSet.has(key)) {
            undefinedUnknownClicked.delete(key);
        }
    }

    for (const name of names) {
        const fullName = String(fullNameByName[name] || "").trim();
        if (fullName) {
            undefinedFullNames.set(name, fullName);
        }
    }

    const sourceKey = names.map((name) => `${name}:${sourceByName[name] || ""}`).join("||");
    const fullNameKey = names.map((name) => `${name}:${undefinedFullNames.get(name) || ""}`).join("||");
    const tablesKey = allowedTables.join("||");
    const ttsKey = JSON.stringify(tableToSections);
    const renderKey = `${names.join("||")}__${tablesKey}__${ttsKey}__${allowedSections.join("||")}__${sourceKey}__${fullNameKey}`;
    if (renderKey === lastUndefinedRenderKey) {
        sectionEl.classList.remove("hidden");
        summaryEl.textContent = t("job.undefinedSpecShort");
        return;
    }
    lastUndefinedRenderKey = renderKey;

    sectionEl.classList.remove("hidden");
    summaryEl.textContent = t("job.undefinedSpecLong");
    listEl.innerHTML = "";

    for (const name of names) {
        const row = document.createElement("div");
        row.className = "undefined-item";
        row.dataset.itemName = name;

        const nameWrapEl = document.createElement("div");
        nameWrapEl.className = "undefined-item-name";
        const nameEl = document.createElement("div");
        const source = sourceByName[name];
        if (source) {
            const sourceFile = source.split(/[\\/]/).pop() || source;
            nameEl.textContent = t("job.undefinedSpecFile", { name, file: sourceFile });
        } else {
            nameEl.textContent = name;
        }
        nameWrapEl.appendChild(nameEl);

        const fullNameEl = document.createElement("div");
        fullNameEl.className = "undefined-item-full-name hidden";
        if (undefinedUnknownClicked.has(name)) {
            const shownFullName = (undefinedFullNames.get(name) || name).trim() || name;
            fullNameEl.textContent = t("job.undefinedSpecFullName", { name: shownFullName });
            fullNameEl.classList.remove("hidden");
        }
        nameWrapEl.appendChild(fullNameEl);

        const keyInput = document.createElement("input");
        keyInput.type = "text";
        keyInput.dataset.name = name;
        keyInput.placeholder = t("job.mappingPlaceholder");
        keyInput.value = undefinedCustomKeys.get(name) || name;
        keyInput.oninput = () => {
            undefinedCustomKeys.set(name, keyInput.value);
        };

        const selectsWrap = document.createElement("div");
        selectsWrap.className = "undefined-item-selects";

        const tableSelect = document.createElement("select");
        tableSelect.className = "undefined-table-select";
        tableSelect.dataset.name = name;
        const tablePlaceholder = document.createElement("option");
        tablePlaceholder.value = "";
        tablePlaceholder.textContent = t("job.chooseTable");
        tableSelect.appendChild(tablePlaceholder);
        for (const tbl of allowedTables) {
            const opt = document.createElement("option");
            opt.value = tbl;
            opt.textContent = tbl;
            tableSelect.appendChild(opt);
        }

        const sectionSelect = document.createElement("select");
        sectionSelect.className = "undefined-section-select hidden";
        sectionSelect.dataset.name = name;

        const syncSectionSelect = (tableLabel) => {
            const secs = Array.isArray(tableToSections[tableLabel]) ? tableToSections[tableLabel] : [];
            sectionSelect.innerHTML = "";
            const phSec = document.createElement("option");
            phSec.value = "";
            phSec.textContent = t("job.chooseSectionInTable");
            sectionSelect.appendChild(phSec);
            for (const s of secs) {
                const o = document.createElement("option");
                o.value = s;
                o.textContent = s;
                sectionSelect.appendChild(o);
            }
            if (secs.length > 1) {
                sectionSelect.classList.remove("hidden");
                const savedSec = undefinedSelectedSection.get(name);
                if (savedSec && secs.includes(savedSec)) {
                    sectionSelect.value = savedSec;
                }
            } else {
                sectionSelect.classList.add("hidden");
                sectionSelect.value = "";
                undefinedSelectedSection.delete(name);
            }
        };

        tableSelect.onchange = () => {
            const tbl = tableSelect.value;
            if (tbl) {
                undefinedSelectedTable.set(name, tbl);
            } else {
                undefinedSelectedTable.delete(name);
            }
            syncSectionSelect(tbl);
        };

        sectionSelect.onchange = () => {
            if (sectionSelect.value) {
                undefinedSelectedSection.set(name, sectionSelect.value);
            } else {
                undefinedSelectedSection.delete(name);
            }
        };

        const initialTable = undefinedSelectedTable.get(name);
        if (initialTable && allowedTables.includes(initialTable)) {
            tableSelect.value = initialTable;
            syncSectionSelect(initialTable);
        }

        selectsWrap.appendChild(tableSelect);
        selectsWrap.appendChild(sectionSelect);

        const actionsEl = document.createElement("div");
        actionsEl.className = "undefined-item-actions";

        const showUnknownBtn = document.createElement("button");
        showUnknownBtn.type = "button";
        showUnknownBtn.className = "undefined-item-action-btn btn-secondary";
        showUnknownBtn.textContent = t("job.showUnknownFullName");
        if (undefinedUnknownClicked.has(name)) {
            showUnknownBtn.classList.add("hidden");
        }
        showUnknownBtn.onclick = () => {
            const shownFullName = (undefinedFullNames.get(name) || name).trim() || name;
            undefinedUnknownClicked.add(name);
            fullNameEl.textContent = t("job.undefinedSpecFullName", { name: shownFullName });
            fullNameEl.classList.remove("hidden");
            showUnknownBtn.classList.add("hidden");
        };

        const markNotSpecBtn = document.createElement("button");
        markNotSpecBtn.type = "button";
        markNotSpecBtn.className = "undefined-item-action-btn btn-danger";
        markNotSpecBtn.textContent = t("job.markAsNotSpec");
            markNotSpecBtn.onclick = async () => {
            const msg = document.getElementById("saveSpecSectionsMsg");
            const fullName = (undefinedFullNames.get(name) || "").trim();
            const customKey = (keyInput.value || "").trim();
            const mappingKey = fullName || customKey || name;
            showUnknownBtn.disabled = true;
            markNotSpecBtn.disabled = true;
            tableSelect.disabled = true;
            sectionSelect.disabled = true;
            keyInput.disabled = true;
            try {
                await saveSpecSections({ items: [{ name: mappingKey, mark_not_spec: true }] });
                msg.textContent = t("job.markAsNotSpecSaved");
                msg.dataset.tone = "success";
                appendActivityLog(msg.textContent, "success");
                undefinedSelectedTable.delete(name);
                undefinedSelectedSection.delete(name);
                undefinedCustomKeys.delete(name);
                undefinedFullNames.delete(name);
                undefinedUnknownClicked.delete(name);
                lastUndefinedRenderKey = "";
                await refreshUndefinedSpecSection([]);
            } catch {
                msg.textContent = t("job.markAsNotSpecFailed");
                msg.dataset.tone = "error";
                appendActivityLog(msg.textContent, "error");
                showUnknownBtn.disabled = false;
                markNotSpecBtn.disabled = false;
                tableSelect.disabled = false;
                sectionSelect.disabled = false;
                keyInput.disabled = false;
            }
        };
        actionsEl.appendChild(showUnknownBtn);
        actionsEl.appendChild(markNotSpecBtn);

        row.appendChild(nameWrapEl);
        row.appendChild(keyInput);
        row.appendChild(selectsWrap);
        row.appendChild(actionsEl);
        listEl.appendChild(row);
    }
}

async function onSaveSpecSectionsClicked() {
    const msg = document.getElementById("saveSpecSectionsMsg");
    const rows = Array.from(document.querySelectorAll("#undefinedSpecList .undefined-item"));
    const items = [];
    const resolvedOriginalNames = [];
    for (const row of rows) {
        const itemName = row.dataset.itemName;
        const input = row.querySelector("input[data-name]");
        const tableSel = row.querySelector("select.undefined-table-select");
        const sectionSel = row.querySelector("select.undefined-section-select");
        if (!input || !itemName) {
            continue;
        }
        const customKey = (input.value || "").trim();
        if (!customKey) {
            continue;
        }
        if (!tableSel?.value) {
            continue;
        }
        const table = tableSel.value;
        const secs = Array.isArray(tableToSections[table]) ? tableToSections[table] : [];
        if (secs.length > 1 && !sectionSel?.value) {
            continue;
        }
        const payloadItem = { name: customKey, table };
        if (secs.length > 1) {
            payloadItem.section = sectionSel.value;
        }
        const fullHint = (undefinedFullNames.get(itemName) || "").trim();
        if (fullHint) {
            payloadItem.full_name = fullHint;
        }
        items.push(payloadItem);
        resolvedOriginalNames.push(itemName);
    }
    const count = items.length;
    if (!count) {
        msg.textContent = t("job.chooseAtLeastOneTableSection");
        msg.dataset.tone = "warn";
        return;
    }
    if (
        !(await confirmDialog(t("job.specSectionsSaveConfirm"), {
            confirmText: t("job.specSectionsSaveConfirmOk"),
            cancelText: t("common.cancel"),
        }))
    ) {
        return;
    }
    try {
        await saveSpecSections({ items });
        msg.textContent = t("job.mappingSaved", { count });
        msg.dataset.tone = "success";
        appendActivityLog(msg.textContent, "success");
        for (const name of resolvedOriginalNames) {
            undefinedSelectedTable.delete(name);
            undefinedSelectedSection.delete(name);
            undefinedCustomKeys.delete(name);
            undefinedFullNames.delete(name);
            undefinedUnknownClicked.delete(name);
        }
        lastUndefinedRenderKey = "";
        await refreshUndefinedSpecSection([]);
    } catch {
        msg.textContent = t("job.mappingSaveFailed");
        msg.dataset.tone = "error";
        appendActivityLog(msg.textContent, "error");
    }
}

function setJobLiveIndicator(isVisible) {
    const indicator = document.getElementById("jobLiveIndicator");
    if (!indicator) return;
    indicator.classList.toggle("hidden", !isVisible);
    if (!isVisible) return;
    const liveText = document.getElementById("jobLiveText");
    if (liveText) {
        liveText.textContent = t("job.processingLive");
    }
}

function setProcessingState(isProcessing) {
    if (onProcessingStateChange) {
        onProcessingStateChange(Boolean(isProcessing));
    }
}

function clearActivityLog() {
    const list = document.getElementById("activityLogList");
    if (list) {
        list.innerHTML = "";
    }
    lastLoggedJobStatus = null;
    lastLoggedProgressStep = -1;
    lastLoggedFileKey = "";
    lastLoggedInvalidFilesCount = 0;
}

function resetJobUi({ hideSection, clearActivity }) {
    const section = document.getElementById("jobSection");
    if (section) {
        delete section.dataset.summary;
    }
    if (section && hideSection) {
        section.classList.add("hidden");
    } else if (section && !hideSection) {
        section.classList.remove("hidden");
    }
    setJobCloseVisible(showFinishedJobSummary && !watchedJobId);
    document.getElementById("jobStatusText").textContent = "";
    document.getElementById("jobError").textContent = "";
    document.getElementById("jobWarnings").textContent = "";
    document.getElementById("progressBar").style.width = "0%";
    document.getElementById("progressText").textContent = t("common.percent", { value: 0 });
    const dash = t("common.emDash");
    document.getElementById("statPages").textContent = dash;
    document.getElementById("statPipelines").textContent = dash;
    document.getElementById("statSpecs").textContent = dash;
    document.getElementById("statTime").textContent = dash;
    document.getElementById("invalidSection").classList.add("hidden");
    document.getElementById("invalidSummary").textContent = "";
    document.getElementById("invalidList").innerHTML = "";
    document.getElementById("invalidList").classList.add("hidden");
    const invalidToggleBtn = document.getElementById("invalidToggleBtn");
    if (invalidToggleBtn) {
        invalidToggleBtn.classList.add("hidden");
    }
    invalidFilesExpanded = false;
    lastInvalidFilesKey = "";
    const cancelBtn = document.getElementById("jobCancelBtn");
    if (cancelBtn) {
        cancelBtn.classList.add("hidden");
        cancelBtn.disabled = false;
    }
    cancelInFlight = false;
    document.getElementById("undefinedSpecSection").classList.add("hidden");
    document.getElementById("undefinedSpecSummary").textContent = "";
    document.getElementById("undefinedSpecList").innerHTML = "";
    document.getElementById("saveSpecSectionsMsg").textContent = "";
    document.getElementById("saveSpecSectionsMsg").dataset.tone = "info";
    lastUndefinedRenderKey = "";
    const jobEmbSec = document.getElementById("jobEmbedmentPendingSection");
    if (jobEmbSec) {
        jobEmbSec.classList.add("hidden");
    }
    const jobEmbSum = document.getElementById("jobEmbedmentPendingSummary");
    if (jobEmbSum) {
        jobEmbSum.textContent = "";
    }
    const jobEmbList = document.getElementById("jobEmbedmentPendingList");
    if (jobEmbList) {
        jobEmbList.innerHTML = "";
    }
    const jobEmbMsg = document.getElementById("jobEmbedmentPendingMsg");
    if (jobEmbMsg) {
        jobEmbMsg.textContent = "";
        jobEmbMsg.dataset.tone = "info";
    }
    lastJobEmbedmentRenderKey = "";
    undefinedSelectedTable.clear();
    undefinedSelectedSection.clear();
    undefinedCustomKeys.clear();
    undefinedFullNames.clear();
    undefinedUnknownClicked.clear();
    setJobLiveIndicator(false);
    if (clearActivity) {
        clearActivityLog();
    }
}

function appendJobStatusLog(text, tone, statusKey) {
    if (lastLoggedJobStatus === statusKey) {
        return;
    }
    lastLoggedJobStatus = statusKey;
    appendActivityLog(text, tone);
}

function appendActivityLog(text, tone = "info") {
    if (!text) return;
    const list = document.getElementById("activityLogList");
    if (!list) return;
    const item = document.createElement("li");
    item.className = "activity-log-item";
    item.dataset.tone = tone;
    const time = new Date();
    const hh = String(time.getHours()).padStart(2, "0");
    const mm = String(time.getMinutes()).padStart(2, "0");
    const ss = String(time.getSeconds()).padStart(2, "0");
    const ts = document.createElement("span");
    ts.className = "activity-log-time";
    ts.textContent = `${hh}:${mm}:${ss}`;
    item.appendChild(ts);
    item.append(` ${text}`);
    list.prepend(item);
    while (list.children.length > 80) {
        list.removeChild(list.lastChild);
    }
}
