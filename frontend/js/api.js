import { t, translateBackendMessage } from "./messages.js";

const DEFAULT_REQUEST_TIMEOUT_MS = 120000;

function buildClientError({ status = 0, payload = null, fileNames = [] }) {
    const safePayload = payload && typeof payload === "object"
        ? payload
        : {
              error: "unknown_error",
              message: t("common.unknownError"),
              details: {},
          };
    const err = new Error(safePayload.message || `HTTP ${status}`);
    err.status = status;
    err.payload = safePayload;
    err.fileNames = Array.from(
        new Set(Array.isArray(fileNames) ? fileNames.filter(Boolean) : []),
    );
    return err;
}

async function parseApiError(res) {
    let payload = null;
    try {
        payload = await res.json();
    } catch {
        payload = null;
    }
    if (!payload || typeof payload !== "object") {
        payload = {
            error: "http_error",
            status_code: res.status,
            message: res.status >= 500 ? t("backendErrors.internalServerError") : `HTTP ${res.status}`,
            details: {},
            request_id: "N/A",
        };
    }
    if (payload && typeof payload.message === "string") {
        payload.message = translateBackendMessage(payload.message);
    }
    if (Array.isArray(payload?.details?.errors)) {
        payload.details.errors = payload.details.errors.map((item) => {
            if (!item || typeof item !== "object") {
                return item;
            }
            if (typeof item.msg === "string") {
                return {
                    ...item,
                    msg: translateBackendMessage(item.msg),
                };
            }
            return item;
        });
    }
    const fileNames = [];
    if (Array.isArray(payload?.details?.files)) {
        for (const name of payload.details.files) {
            if (typeof name === "string" && name.trim()) {
                fileNames.push(name.trim());
            }
        }
    }
    throw buildClientError({
        status: res.status,
        payload,
        fileNames,
    });
}

let authLostHandler = null;
let refreshInFlight = null;
let authLostHandled = false;

function normalizePath(path) {
    try {
        return new URL(String(path), window.location.origin).pathname;
    } catch {
        return String(path || "");
    }
}

function isSessionlessAuthPath(path) {
    const normalized = normalizePath(path);
    return (
        normalized === "/auth/login"
        || normalized === "/auth/refresh"
        || normalized === "/auth/change-password"
    );
}

function shouldAttemptRefresh(path) {
    const normalized = normalizePath(path);
    return !isSessionlessAuthPath(normalized) && normalized !== "/auth/logout";
}

async function notifyAuthLost() {
    if (authLostHandled) {
        return;
    }
    authLostHandled = true;
    if (typeof authLostHandler === "function") {
        try {
            await authLostHandler();
        } catch {
            // no-op
        }
    }
}

async function refreshWithSingleFlight() {
    if (!refreshInFlight) {
        refreshInFlight = (async () => {
            const res = await fetch("/auth/refresh", {
                method: "POST",
                credentials: "include",
                cache: "no-store",
            });
            if (!res.ok) {
                await parseApiError(res);
            }
        })().finally(() => {
            refreshInFlight = null;
        });
    }
    await refreshInFlight;
}

export function setAuthLostHandler(handler) {
    authLostHandler = typeof handler === "function" ? handler : null;
    authLostHandled = false;
}

export function resetAuthLostState() {
    authLostHandled = false;
}

async function request(path, options = {}) {
    const { _retryAfterRefresh = false, timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS, ...fetchOptions } = options || {};
    const controller = new AbortController();
    const hasExternalSignal = Boolean(fetchOptions.signal);
    const timeout = Number(timeoutMs || 0);
    let timeoutId = null;
    if (!hasExternalSignal && timeout > 0) {
        timeoutId = window.setTimeout(() => controller.abort(), timeout);
    }
    let res;
    try {
        res = await fetch(path, {
            credentials: "include",
            cache: "no-store",
            ...fetchOptions,
            signal: hasExternalSignal ? fetchOptions.signal : controller.signal,
        });
    } catch (error) {
        const timeoutReached = !hasExternalSignal && timeout > 0 && controller.signal.aborted;
        if (error?.name === "AbortError" && timeoutReached) {
            throw buildClientError({
                payload: {
                    error: "timeout_error",
                    message: t("backendErrors.timeoutError"),
                    details: { reason: "timeout_error" },
                    request_id: "N/A",
                },
            });
        }
        throw buildClientError({
            payload: {
                error: "network_error",
                message: t("backendErrors.networkError"),
                details: { reason: "network_error" },
                request_id: "N/A",
            },
        });
    } finally {
        if (timeoutId !== null) {
            window.clearTimeout(timeoutId);
        }
    }
    if (res.status === 401 && !_retryAfterRefresh && shouldAttemptRefresh(path)) {
        try {
            await refreshWithSingleFlight();
            return await request(path, { ...fetchOptions, timeoutMs, _retryAfterRefresh: true });
        } catch {
            await notifyAuthLost();
        }
    }
    if (res.status === 401 && !isSessionlessAuthPath(path)) {
        await notifyAuthLost();
    }
    if (!res.ok) {
        await parseApiError(res);
    }
    return res;
}

export async function uploadPdf(files, options = {}) {
    const { pdfImportKind = "pipeline_drawings", pagesLimit = 0 } = options;
    const form = new FormData();
    const list = Array.from(files || []);
    if (!list.length) {
        throw new Error(t("api.noPdfFilesSelected"));
    }

    form.append("pdf_import_kind", String(pdfImportKind || "pipeline_drawings"));
    form.append("pages_limit", String(Math.max(0, Number(pagesLimit) || 0)));

    // Один архив (ZIP или RAR) — отправляем как archive.
    const one = list[0].name.toLowerCase();
    if (list.length === 1 && (one.endsWith(".zip") || one.endsWith(".rar"))) {
        form.append("archive", list[0]);
    } else if (list.length === 1) {
        form.append("file", list[0]);
    } else {
        for (const f of list) {
            form.append("files", f);
        }
    }

    const res = await request("/pipelines/from-pdf", {
        method: "POST",
        body: form,
    });
    return res.json();
}

export async function uploadWord(files, options = {}) {
    const { wordImportKind = "passport_vik", pagesLimit = 0 } = options;
    const form = new FormData();
    const list = Array.from(files || []);
    if (!list.length) {
        throw new Error(t("api.noWordFilesSelected"));
    }

    form.append("word_import_kind", String(wordImportKind || "passport_vik"));
    form.append("pages_limit", String(Math.max(0, Number(pagesLimit) || 0)));

    const one = list[0].name.toLowerCase();
    if (list.length === 1 && (one.endsWith(".zip") || one.endsWith(".rar"))) {
        form.append("archive", list[0]);
    } else if (list.length === 1) {
        form.append("file", list[0]);
    } else {
        for (const f of list) {
            form.append("files", f);
        }
    }

    const res = await request("/pipelines/from-word", {
        method: "POST",
        body: form,
    });
    return res.json();
}

export async function uploadExcel(files) {
    const form = new FormData();
    const list = Array.from(files || []);
    if (!list.length) {
        throw new Error(t("api.noExcelFilesSelected"));
    }

    const one = list[0].name.toLowerCase();
    if (list.length === 1 && (one.endsWith(".zip") || one.endsWith(".rar"))) {
        form.append("archive", list[0]);
    } else if (list.length === 1) {
        form.append("file", list[0]);
    } else {
        for (const f of list) {
            form.append("files", f);
        }
    }

    const res = await request("/pipelines/from-excel", {
        method: "POST",
        body: form,
    });
    return res.json();
}

export async function getPipelines() {
    const res = await request("/pipelines/all");
    const data = await res.json();
    return data.pipeline_names || [];
}

export async function getActiveJob() {
    const res = await request("/pipelines/jobs/active");
    return res.json();
}

export async function cancelJob(jobId) {
    const res = await request(`/pipelines/jobs/${encodeURIComponent(jobId)}/cancel`, {
        method: "POST",
    });
    return res.json();
}

export async function fetchPdfDrawingCheck(file, { page = 1, signal } = {}) {
    const form = new FormData();
    form.append("file", file);
    form.append("page", String(Math.max(1, Number(page) || 1)));
    const res = await request("/pipelines/pdf-drawing-check", {
        method: "POST",
        body: form,
        signal,
        timeoutMs: 180000,
    });
    return res.json();
}

export async function getUndefinedSpecNames() {
    const res = await request("/pipelines/spec-sections/undefined");
    return res.json();
}

export async function saveSpecSections(mappings) {
    const res = await request("/pipelines/spec-sections", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(mappings || {}),
    });
    return res.json();
}

export async function listInstrumentEmbedments(pipelineName) {
    const enc = encodeURIComponent(pipelineName);
    const res = await request(`/pipelines/instrument-embedments/${enc}`);
    return res.json();
}

export async function patchInstrumentEmbedments(pipelineName, body) {
    const enc = encodeURIComponent(pipelineName);
    const res = await request(`/pipelines/instrument-embedments/${enc}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body || {}),
    });
    return res.json();
}

export async function login({ username, password }) {
    const res = await fetch("/auth/login", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            username,
            password,
        }),
    });
    if (!res.ok) {
        await parseApiError(res);
    }
    return res.json();
}

export async function refreshSession() {
    const res = await request("/auth/refresh", { method: "POST" });
    return res.json();
}

export async function logout() {
    const res = await request("/auth/logout", { method: "POST" });
    return res.json();
}

export async function getCurrentUser() {
    const res = await request("/auth/me");
    return res.json();
}

export async function changePassword({ newPassword, currentPassword = null, changePasswordToken = null }) {
    const res = await request("/auth/change-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            new_password: newPassword,
            current_password: currentPassword,
            change_password_token: changePasswordToken,
        }),
    });
    return res.json();
}

export async function downloadPassport(pipelineName) {
    const res = await request(`/pipelines/${encodeURIComponent(pipelineName)}/passport`);
    await downloadBlob(res, `${pipelineName}.docx`);
}

export async function downloadPassportsZip(pipelineNames) {
    const list = Array.isArray(pipelineNames) ? pipelineNames.filter(Boolean) : [];
    const res = await request("/pipelines/passports/zip", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pipeline_names: list }),
    });
    await downloadBlob(res, t("pipelines.zipFallbackFilename"));
}

async function downloadBlob(response, fallbackFilename) {
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^"]+)"?/i);
    const resolvedFilename = (match && match[1]) || fallbackFilename;
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = resolvedFilename;
    link.click();
    URL.revokeObjectURL(url);
}

export async function listAdminUsers() {
    const res = await request("/admin/users");
    return res.json();
}

export async function createAdminUser({ username, role, isActive }) {
    const res = await request("/admin/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            username,
            role,
            is_active: isActive,
        }),
    });
    return res.json();
}

export async function deleteAdminUser(userId) {
    const res = await request(`/admin/users/${userId}`, { method: "DELETE" });
    return res.json();
}

export async function updateAdminUserRole(userId, role) {
    const res = await request(`/admin/users/${userId}/role`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role }),
    });
    return res.json();
}

export async function updateAdminUserActive(userId, isActive) {
    const res = await request(`/admin/users/${userId}/active`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_active: isActive }),
    });
    return res.json();
}

export async function getAdminAuditLogs(filters = {}) {
    const query = buildQuery(filters);
    const res = await request(`/admin/audit-logs${query}`);
    return res.json();
}

export async function getAdminJobErrors(filters = {}) {
    const query = buildQuery(filters);
    const res = await request(`/admin/job-errors${query}`);
    return res.json();
}

export async function getAdminAppErrors(filters = {}) {
    const query = buildQuery(filters);
    const res = await request(`/admin/app-errors${query}`);
    return res.json();
}

export async function getAdminErrorLogs(filters = {}) {
    const query = buildQuery(filters);
    const res = await request(`/admin/errors${query}`);
    return res.json();
}

function buildQuery(params = {}) {
    const q = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
        if (value === undefined || value === null) continue;
        const text = String(value).trim();
        if (!text) continue;
        q.set(key, text);
    }
    const s = q.toString();
    return s ? `?${s}` : "";
}

export async function getAdminParsingLogs(filters = {}) {
    const query = buildQuery({
        ...filters,
        tz_offset_min: -new Date().getTimezoneOffset(),
    });
    const res = await request(`/admin/parsing-logs${query}`);
    return res.json();
}

export async function downloadAdminParsingLogs(filters = {}) {
    const query = buildQuery({
        ...filters,
        tz_offset_min: -new Date().getTimezoneOffset(),
    });
    const res = await request(`/admin/parsing-logs/download${query}`);
    await downloadBlob(res, "parsing_logs.jsonl");
}

export async function downloadAdminAuditLogs(filters = {}) {
    const query = buildQuery(filters);
    const res = await request(`/admin/audit-logs/download${query}`);
    await downloadBlob(res, "audit_logs.jsonl");
}

export async function downloadAdminErrorLogs(filters = {}) {
    const query = buildQuery(filters);
    const res = await request(`/admin/errors/download${query}`);
    await downloadBlob(res, "errors_logs.jsonl");
}

export async function clearAdminParsingLogs({ login, confirm = true, accessPassword = "" }) {
    const query = buildQuery({ login, confirm: confirm ? "true" : "false" });
    const res = await request(`/admin/parsing-logs${query}`, {
        method: "DELETE",
        headers: {
            "X-Admin-Clear-Password": String(accessPassword || ""),
        },
    });
    return res.json();
}

export async function clearAdminAuditLogs({ user_id, confirm = true, accessPassword = "" }) {
    const query = buildQuery({ user_id, confirm: confirm ? "true" : "false" });
    const res = await request(`/admin/audit-logs${query}`, {
        method: "DELETE",
        headers: {
            "X-Admin-Clear-Password": String(accessPassword || ""),
        },
    });
    return res.json();
}

export async function clearAdminErrorLogs({ user_id, login, file_type = "", confirm = true, accessPassword = "" }) {
    const query = buildQuery({
        user_id,
        login,
        file_type,
        confirm: confirm ? "true" : "false",
    });
    const res = await request(`/admin/errors${query}`, {
        method: "DELETE",
        headers: {
            "X-Admin-Clear-Password": String(accessPassword || ""),
        },
    });
    return res.json();
}

export async function fetchChecklist(options = {}) {
    const bust = options.bustCache ? `?_=${Date.now()}` : "";
    const res = await request(`/checklist${bust}`);
    return res.json();
}

export async function setChecklistItemDone(itemId, done) {
    const res = await request(`/checklist/items/${itemId}/done`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ done }),
    });
    return res.json();
}

export async function resetChecklist() {
    const res = await request("/checklist/reset", { method: "POST" });
    return res.json();
}

export async function adminCreateChecklistItem(title) {
    const res = await request("/admin/checklist/items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
    });
    return res.json();
}

export async function adminDeleteChecklistItem(itemId) {
    const res = await request(`/admin/checklist/items/${itemId}`, { method: "DELETE" });
    return res.json();
}

export async function adminUpdateChecklistItem(itemId, { title, sortOrder = null }) {
    const body = { title };
    if (sortOrder !== null && sortOrder !== undefined && Number.isFinite(Number(sortOrder))) {
        body.sort_order = Number(sortOrder);
    }
    const res = await request(`/admin/checklist/items/${itemId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    return res.json();
}

export async function listAdminSettingsFiles() {
    const res = await request("/admin/settings-files");
    return res.json();
}

/** @deprecated используйте listAdminSettingsFiles */
export async function listAdminConfigJsonFiles() {
    const res = await request("/admin/config-json");
    return res.json();
}

export async function getAdminSettingsFileContent(filename) {
    const q = new URLSearchParams({ filename });
    const res = await request(`/admin/settings-files/content?${q}`);
    return res.json();
}

/** @deprecated используйте getAdminSettingsFileContent */
export async function getAdminConfigJsonFile(filename) {
    const enc = encodeURIComponent(filename);
    const res = await request(`/admin/config-json/${enc}`);
    return res.json();
}

export async function putAdminSettingsFileContent(filename, value) {
    const q = new URLSearchParams({ filename });
    const res = await request(`/admin/settings-files/content?${q}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value }),
    });
    return res.json();
}

/** Все трубопроводы с закладными приборов из БД (админ). */
export async function getAdminAllInstrumentEmbedments() {
    const res = await request("/admin/instrument-embedments");
    return res.json();
}

/** @deprecated используйте putAdminSettingsFileContent */
export async function putAdminConfigJsonFile(filename, value) {
    const enc = encodeURIComponent(filename);
    const res = await request(`/admin/config-json/${enc}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value }),
    });
    return res.json();
}

export function createUpdatesSocket(jobId = null) {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const url = new URL(`${proto}://${window.location.host}/pipelines/ws`);
    if (jobId !== null && jobId !== undefined) {
        url.searchParams.set("job_id", String(jobId));
    }
    return new WebSocket(url.toString());
}
