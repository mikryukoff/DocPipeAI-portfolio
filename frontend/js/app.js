import {
    getAdminAuditLogs,
    getAdminErrorLogs,
    changePassword,
    clearAdminAuditLogs,
    clearAdminErrorLogs,
    clearAdminParsingLogs,
    createAdminUser,
    downloadAdminAuditLogs,
    downloadAdminErrorLogs,
    downloadAdminParsingLogs,
    deleteAdminUser,
    getAdminParsingLogs,
    getActiveJob,
    getCurrentUser,
    listAdminUsers,
    login,
    logout,
    resetAuthLostState,
    setAuthLostHandler,
    updateAdminUserActive,
    updateAdminUserRole,
    fetchPdfDrawingCheck,
    uploadExcel,
    uploadPdf,
    uploadWord,
} from "./api.js";
import {
    clearFinishedJobDisplay,
    discardImportJobUi,
    hasWatchedJob,
    pushActivityLog,
    resumeActiveJob,
    setJobProcessingStateListener,
    setJobsViewerRole,
    setJobsViewerUserId,
    startLiveUpdates,
    watchJob,
} from "./jobs.js";
import {
    bindAdminChecklistActions,
    clearChecklistUi,
    initChecklistSidebar,
    loadChecklist,
    refreshAdminChecklistTable,
} from "./checklist.js";
import { confirmDialog, promptDialog } from "./dialogs.js";
import { bindDomI18n, pageMeta, t } from "./messages.js";
import { initEmbedmentsPanel } from "./embedments.js";
import { loadPipelines } from "./pipelines.js";
import { bindSettingsPage, onSettingsPageShown } from "./settings.js";

let changePasswordToken = null;
let isAuthenticated = false;
let currentRole = null;
let currentUsername = null;
let currentUserId = null;
let isAdminUiReady = false;
let isSettingsBound = false;
let currentPage = "import";
let isProcessingLocked = true;
let inflightUploadCount = 0;
let parsingLogsOffset = 0;
const parsingLogsLimit = 50;
let lastParsingRowsCount = 0;
let adminLogSource = "parsing";

function roleLabel(role) {
    const r = String(role || "").toLowerCase();
    if (r === "admin") return t("roles.adminLower");
    if (r === "engineer") return t("roles.engineerLower");
    if (r === "demo") return t("roles.demoLower");
    return role || t("auth.roleUnknown");
}

function ensureSettingsPageBound() {
    if (!isSettingsBound) {
        bindSettingsPage();
        isSettingsBound = true;
    }
}

function setBanner(id, text = "", tone = "info") {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = text || "";
    el.dataset.tone = tone;
}

function updatePageHeader(pageName) {
    const meta = pageMeta(pageName);
    document.getElementById("pageTitle").textContent = meta.title;
    document.getElementById("pageSubtitle").textContent = meta.subtitle;
    document.getElementById("pageNextStep").textContent = meta.nextStep;
}

function setActivePage(pageName) {
    if (pageName !== "import") {
        clearFinishedJobDisplay();
    }
    currentPage = pageName;
    const pages = {
        import: "pageImport",
        pipelines: "pagePipelines",
        settings: "pageSettings",
        admin: "pageAdmin",
    };
    for (const [key, pageId] of Object.entries(pages)) {
        document.getElementById(pageId).classList.toggle("hidden", key !== pageName);
    }
    document.getElementById("navImportBtn").classList.toggle("active", pageName === "import");
    document.getElementById("navPipelinesBtn").classList.toggle("active", pageName === "pipelines");
    const navSettings = document.getElementById("navSettingsBtn");
    if (navSettings) {
        navSettings.classList.toggle("active", pageName === "settings");
    }
    document.getElementById("navAdminBtn").classList.toggle("active", pageName === "admin");
    updatePageHeader(pageName);
    // Восстанавливаем прогресс только для авторизованного пользователя:
    // иначе берётся "глобальный" снимок до определения userId и закрытый блок может всплыть снова.
    if (pageName === "import" && isAuthenticated) {
        resumeActiveJob();
    }
    if (pageName === "settings") {
        void onSettingsPageShown();
    }
}

function resetPasswordFieldVisibility(inputId, buttonId) {
    const input = document.getElementById(inputId);
    const btn = document.getElementById(buttonId);
    if (!input || !btn) return;
    input.type = "password";
    btn.classList.remove("is-visible");
    const show = t("authPage.showPassword");
    btn.setAttribute("aria-label", show);
    btn.setAttribute("title", show);
    btn.setAttribute("aria-pressed", "false");
}

function bindPasswordVisibilityToggle(inputId, buttonId) {
    const input = document.getElementById(inputId);
    const btn = document.getElementById(buttonId);
    if (!input || !btn) return;

    const syncLabels = (visible) => {
        const label = visible ? t("authPage.hidePassword") : t("authPage.showPassword");
        btn.setAttribute("aria-label", label);
        btn.setAttribute("title", label);
        btn.setAttribute("aria-pressed", visible ? "true" : "false");
    };

    syncLabels(false);
    btn.addEventListener("click", () => {
        const nextVisible = input.type === "password";
        input.type = nextVisible ? "text" : "password";
        btn.classList.toggle("is-visible", nextVisible);
        syncLabels(nextVisible);
    });
}

function bindNavigation() {
    document.getElementById("navImportBtn").onclick = () => setActivePage("import");
    document.getElementById("navPipelinesBtn").onclick = () => setActivePage("pipelines");
    const navSettingsBtn = document.getElementById("navSettingsBtn");
    if (navSettingsBtn) {
        navSettingsBtn.onclick = () => setActivePage("settings");
    }
    document.getElementById("navAdminBtn").onclick = () => {
        if (currentRole === "admin") {
            setActivePage("admin");
        }
    };
}

function setAuthenticatedState(authenticated, role = null, username = null, userId = null) {
    isAuthenticated = authenticated;
    currentRole = role;
    currentUsername = username;
    currentUserId = authenticated ? userId ?? null : null;
    setJobsViewerRole(role);
    setJobsViewerUserId(currentUserId);
    document.getElementById("authPage").classList.toggle("hidden", authenticated);
    document.getElementById("appContent").classList.toggle("hidden", !authenticated);
    const navAdm = document.getElementById("navAdminBtn");
    const navSt = document.getElementById("navSettingsBtn");
    if (navAdm) {
        navAdm.classList.toggle("hidden", !authenticated || role !== "admin");
    }
    if (navSt) {
        navSt.classList.toggle("hidden", !authenticated);
    }
    document.getElementById("authStatus").textContent = authenticated
        ? `${t("auth.authYes")}${role ? ` (${roleLabel(role)})` : ""}`
        : t("auth.authNo");
    document.getElementById("workspaceUserInfo").textContent = authenticated
        ? t("workspace.currentUser", {
              username: username || t("auth.userUnknown"),
              role: roleLabel(role),
          })
        : "";
    if (authenticated) {
        clearTransientMessages();
    }
    if (!authenticated) {
        resetPasswordFieldVisibility("loginPassword", "loginPasswordToggle");
        resetPasswordFieldVisibility("newPasswordInput", "newPasswordToggle");
        document.getElementById("adminSection").classList.add("hidden");
        clearTransientMessages();
        clearChecklistUi();
        discardImportJobUi();
        setActivePage("import");
    }
}

function clearSessionStateLocally() {
    setAuthenticatedState(false);
    currentRole = null;
    currentUsername = null;
    currentUserId = null;
    isProcessingLocked = false;
    inflightUploadCount = 0;
    syncUploadControlsState();
}

async function forceLogoutToLogin(messageKey = null) {
    try {
        await fetch("/auth/logout", {
            method: "POST",
            credentials: "include",
            cache: "no-store",
        });
    } catch {
        // no-op
    }
    clearSessionStateLocally();
    if (messageKey) {
        setBanner("authMsg", t(messageKey), "warn");
    }
}

function showAuthError(error, fallbackMessage) {
    setBanner("authMsg", error?.payload?.message || fallbackMessage, "error");
}

function extractValidationErrorMessage(error, fallbackMessage) {
    const base = error?.payload;
    if (!base) return fallbackMessage;
    if (base.details && Array.isArray(base.details.errors) && base.details.errors.length) {
        const first = base.details.errors[0];
        if (first.msg) return first.msg;
    }
    return base.message || fallbackMessage;
}

function resolveUploadReasonText(error, fallbackMessage) {
    const status = Number(error?.status || 0);
    const payload = error?.payload || {};
    const details = payload?.details || {};
    const reason = String(details.reason || payload.error || "").trim().toLowerCase();
    if (reason === "network_error") return t("upload.reasonNetworkError");
    if (reason === "timeout_error") return t("upload.reasonTimeoutError");
    if (reason === "unsupported_extension") return t("upload.reasonUnsupportedExtension");
    if (reason === "unsupported_mime" || reason === "unsupported_archive_mime") {
        return t("upload.reasonUnsupportedMime");
    }
    if (reason === "file_too_large" || reason === "archive_too_large") {
        const maxMb = details.max_size_mb;
        if (Number.isFinite(Number(maxMb))) {
            return t("upload.reasonFileTooLargeWithLimit", { limit: Number(maxMb) });
        }
        return t("upload.reasonFileTooLarge");
    }
    if (reason === "archive_corrupted" || reason === "archive_has_no_allowed_files") {
        return t("upload.reasonArchiveCorrupted");
    }
    if (reason === "rar_extraction_tool_unavailable" || reason === "rar_unrar_required") {
        return t("upload.reasonArchiveServerTool");
    }
    if (reason === "unknown_import_kind") return t("upload.reasonUnknownImportKind");
    if (reason === "empty_upload") return t("upload.reasonEmptyFile");
    if (status === 413) return t("upload.reasonFileTooLarge");
    if (status >= 500) return t("upload.reasonServerError");
    if (payload?.message) return payload.message;
    return fallbackMessage;
}

function buildFileOnlyErrorMessage(error, fallbackMessage) {
    const files = Array.isArray(error?.fileNames) ? error.fileNames.filter(Boolean) : [];
    const reasonText = resolveUploadReasonText(error, fallbackMessage);
    let message = reasonText;
    if (files.length === 1) {
        message = `${t("common.problematicFile", { name: files[0] })}. ${reasonText}`;
    } else if (files.length > 1) {
        message = `${t("common.problematicFiles", { names: files.join(", ") })}. ${reasonText}`;
    }
    const requestId = String(error?.payload?.request_id || "").trim();
    if (requestId && requestId !== "N/A") {
        message += ` (${t("common.requestId", { requestId })})`;
    }
    return message;
}

function clearTransientMessages() {
    setBanner("pdfUploadMsg", "");
    setBanner("excelUploadMsg", "");
    setBanner("wordUploadMsg", "");
    setBanner("pdfCheckMsg", "");
    setBanner("uploadLockMsg", "");
    setBanner("pipelinesMsg", "");
    setBanner("adminMsg", "");
    setBanner("adminUsersMsg", "");
    setBanner("saveSpecSectionsMsg", "");
}

function renderPdfCheckSnapshot(containerId, base64Png, altText) {
    const wrap = document.getElementById(containerId);
    if (!wrap) return;
    wrap.innerHTML = "";
    const b64 = typeof base64Png === "string" ? base64Png.trim() : "";
    if (!b64) {
        const empty = document.createElement("div");
        empty.className = "pdf-check-empty";
        empty.textContent = t("fileCheck.noImage");
        wrap.appendChild(empty);
        return;
    }
    const img = document.createElement("img");
    img.className = "pdf-check-screenshot";
    img.alt = altText || "";
    img.src = `data:image/png;base64,${b64}`;
    wrap.appendChild(img);
}

function syncUploadControlsState() {
    const lockInputs = isProcessingLocked;
    const busyNow = inflightUploadCount > 0;
    const pdfInput = document.getElementById("pdfInput");
    const excelInput = document.getElementById("excelInput");
    const wordInput = document.getElementById("wordInput");
    const pdfButton = document.getElementById("uploadBtn");
    const excelButton = document.getElementById("uploadExcelBtn");
    const wordButton = document.getElementById("uploadWordBtn");
    const lockBanner = document.getElementById("uploadLockMsg");
    if (pdfInput) {
        pdfInput.disabled = lockInputs;
    }
    if (excelInput) {
        excelInput.disabled = lockInputs;
    }
    if (wordInput) {
        wordInput.disabled = lockInputs;
    }
    if (pdfButton) {
        pdfButton.disabled = busyNow || lockInputs;
    }
    if (excelButton) {
        excelButton.disabled = busyNow || lockInputs;
    }
    if (wordButton) {
        wordButton.disabled = busyNow || lockInputs;
    }
    if (!lockBanner) return;
    if (lockInputs) {
        setBanner("uploadLockMsg", t("upload.blockedByProcessing"), "warn");
    } else {
        setBanner("uploadLockMsg", "");
    }
}

async function tryWarmupSession() {
    try {
        const me = await getCurrentUser();
        setAuthenticatedState(true, me.role, me.username, me.user_id);
        ensureSettingsPageBound();
        await loadPipelines();
        if (me.role === "admin") {
            await bootstrapAdminUi();
        }
        await loadChecklist();
        return true;
    } catch (err) {
        if (err?.status === 401) {
            return false;
        }
        showAuthError(err, t("auth.initFailed"));
        setAuthenticatedState(false);
        return false;
    }
}

function adminMessage(targetId, text, tone = "info") {
    setBanner(targetId, text, tone);
}

async function bootstrapAdminUi() {
    try {
        await listAdminUsers();
        document.getElementById("adminSection").classList.remove("hidden");
        document.getElementById("navAdminBtn").classList.remove("hidden");
        const navSettingsBtn = document.getElementById("navSettingsBtn");
        if (navSettingsBtn) {
            navSettingsBtn.classList.remove("hidden");
        }
        if (!isAdminUiReady) {
            bindAdminActions();
            isAdminUiReady = true;
        }
        ensureSettingsPageBound();
        await refreshAdminUsers();
        await refreshAuditLogs();
        await refreshAdminChecklistTable();
        bindAdminChecklistActions();
    } catch (err) {
        if (err?.status === 403 || err?.status === 401) {
            document.getElementById("adminSection").classList.add("hidden");
            document.getElementById("navAdminBtn").classList.add("hidden");
            if (currentPage === "admin") {
                setActivePage("import");
            }
            return;
        }
        adminMessage("adminMsg", err?.payload?.message || t("admin.initFailed"), "error");
    }
}

function bindAdminActions() {
    document.getElementById("adminCreateUserBtn").onclick = onCreateAdminUser;
    const sourceSelect = document.getElementById("adminLogSourceSelect");
    if (sourceSelect) {
        adminLogSource = sourceSelect.value || "parsing";
        sourceSelect.onchange = async () => {
            adminLogSource = sourceSelect.value || "parsing";
            parsingLogsOffset = 0;
            updateAdminLogSourceUi();
            await refreshAuditLogs();
        };
    }
    document.getElementById("adminAuditRefreshBtn").onclick = async () => {
        parsingLogsOffset = 0;
        await refreshAuditLogs();
    };
    document.getElementById("adminParsingResetBtn").onclick = onResetParsingFilters;
    document.getElementById("adminParsingDownloadBtn").onclick = onDownloadParsingLogs;
    document.getElementById("adminParsingClearBtn").onclick = onClearParsingLogs;
    document.getElementById("adminParsingPrevBtn").onclick = onPrevParsingPage;
    document.getElementById("adminParsingNextBtn").onclick = onNextParsingPage;
    bindAdminChecklistActions();
    updateAdminLogSourceUi();
}

async function refreshAdminUsers() {
    const body = document.getElementById("adminUsersBody");
    body.innerHTML = "";
    const users = await listAdminUsers();
    for (const user of users) {
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td>${user.id}</td>
            <td>${user.username}</td>
            <td></td>
            <td>${user.is_active ? t("admin.yes") : t("admin.no")}</td>
            <td></td>
        `;

        const roleCell = tr.children[2];
        const roleSelect = document.createElement("select");
        for (const role of ["admin", "engineer", "demo"]) {
            const opt = document.createElement("option");
            opt.value = role;
            opt.textContent = t(`roles.${role}`);
            roleSelect.appendChild(opt);
        }
        roleSelect.value = user.role;
        let pendingRole = user.role;
        roleSelect.onchange = () => {
            pendingRole = roleSelect.value;
            if (pendingRole === user.role) {
                adminMessage("adminUsersMsg", "");
                return;
            }
            adminMessage(
                "adminUsersMsg",
                t("admin.roleSaveHint", { username: user.username }),
                "warn"
            );
        };
        roleCell.appendChild(roleSelect);

        const actionCell = tr.children[4];
        const actionWrap = document.createElement("div");
        actionWrap.className = "table-actions";
        const saveRoleBtn = document.createElement("button");
        saveRoleBtn.className = "btn-secondary";
        saveRoleBtn.textContent = t("admin.roleSaveButton");
        saveRoleBtn.onclick = async () => {
            if (pendingRole === user.role) {
                adminMessage("adminUsersMsg", t("admin.roleNotChanged", { username: user.username }), "info");
                return;
            }
            try {
                await updateAdminUserRole(user.id, pendingRole);
                user.role = pendingRole;
                adminMessage("adminUsersMsg", t("admin.roleChanged", { username: user.username }), "success");
            } catch (err) {
                adminMessage("adminUsersMsg", err?.payload?.message || t("admin.roleChangeFailed"), "error");
                roleSelect.value = user.role;
                pendingRole = user.role;
            }
        };
        const delBtn = document.createElement("button");
        delBtn.className = "btn-danger";
        delBtn.textContent = t("admin.deleteButton");
        delBtn.onclick = async () => {
            if (!(await confirmDialog(
                t("admin.deleteConfirm", { username: user.username }),
                { confirmTone: "danger" },
            ))) return;
            try {
                await deleteAdminUser(user.id);
                await refreshAdminUsers();
                await refreshAuditLogs();
                adminMessage("adminUsersMsg", t("admin.userDeleted", { username: user.username }), "success");
            } catch (err) {
                adminMessage("adminUsersMsg", err?.payload?.message || t("admin.userDeleteFailed"), "error");
            }
        };
        actionWrap.appendChild(saveRoleBtn);
        if (user.id !== currentUserId) {
            const activeBtn = document.createElement("button");
            activeBtn.type = "button";
            activeBtn.className = "btn-muted";
            activeBtn.textContent = user.is_active ? t("admin.deactivateUser") : t("admin.enableUser");
            activeBtn.onclick = async () => {
                const nextActive = !user.is_active;
                try {
                    await updateAdminUserActive(user.id, nextActive);
                    adminMessage(
                        "adminUsersMsg",
                        t("admin.userActiveChanged", {
                            username: user.username,
                            state: nextActive ? t("admin.activeStateEnabled") : t("admin.activeStateDisabled"),
                        }),
                        "success"
                    );
                    await refreshAdminUsers();
                    await refreshAuditLogs();
                } catch (err) {
                    adminMessage(
                        "adminUsersMsg",
                        err?.payload?.message || t("admin.activeChangeFailed"),
                        "error"
                    );
                }
            };
            actionWrap.appendChild(activeBtn);
        }
        actionWrap.appendChild(delBtn);
        actionCell.appendChild(actionWrap);

        body.appendChild(tr);
    }
    populateParsingLoginFilter(users);
}

async function onCreateAdminUser() {
    const username = document.getElementById("adminNewUsername").value.trim();
    const role = document.getElementById("adminNewRole").value;
    const isActive = document.getElementById("adminNewActive").checked;
    if (!username) {
        adminMessage("adminUsersMsg", t("admin.usernameRequired"), "warn");
        return;
    }
    try {
        const created = await createAdminUser({ username, role, isActive });
        adminMessage(
            "adminUsersMsg",
            t("admin.userCreatedWithPassword", {
                username: created.username,
                password: created.temporary_password,
            }),
            "success"
        );
        document.getElementById("adminNewUsername").value = "";
        await refreshAdminUsers();
        await refreshAuditLogs();
    } catch (err) {
        adminMessage("adminUsersMsg", err?.payload?.message || t("admin.userCreateFailed"), "error");
    }
}

function populateParsingLoginFilter(users) {
    const select = document.getElementById("adminParsingLoginSelect");
    if (!select) return;
    const list = Array.isArray(users) ? users : [];
    const prev = select.value;
    select.innerHTML = "";
    for (const user of list) {
        const opt = document.createElement("option");
        opt.value = String(user.id);
        opt.dataset.username = user.username;
        opt.textContent = `${user.username} (#${user.id})`;
        select.appendChild(opt);
    }
    if (!select.options.length) {
        const fallback = document.createElement("option");
        fallback.value = currentUserId ? String(currentUserId) : "";
        fallback.dataset.username = currentUsername || "";
        fallback.textContent = currentUsername || t("auth.userUnknown");
        select.appendChild(fallback);
    }
    select.value = prev && Array.from(select.options).some((o) => o.value === prev)
        ? prev
        : select.options[0].value;
    updateAdminLogSourceUi();
}

function getSelectedAdminUserFilter() {
    const select = document.getElementById("adminParsingLoginSelect");
    if (!select) {
        return {
            userId: currentUserId ?? null,
            login: currentUsername || "",
        };
    }
    const selected = select.options[select.selectedIndex] || null;
    const userId = Number(selected?.value || 0);
    const login = selected?.dataset?.username || currentUsername || "";
    return {
        userId: Number.isFinite(userId) && userId > 0 ? userId : null,
        login,
    };
}

function getParsingFilters() {
    const selectedUser = getSelectedAdminUserFilter();
    return {
        login: selectedUser.login || currentUsername || "",
        user_id: selectedUser.userId || "",
        pipeline: document.getElementById("adminParsingPipelineInput")?.value || "",
        date_from: document.getElementById("adminParsingDateFrom")?.value || "",
        date_to: document.getElementById("adminParsingDateTo")?.value || "",
        file_type: document.getElementById("adminParsingFileTypeSelect")?.value || "",
        limit: parsingLogsLimit,
        offset: parsingLogsOffset,
    };
}

function getAdminFiltersCommon() {
    const selectedUser = getSelectedAdminUserFilter();
    return {
        user_id: selectedUser.userId || "",
        date_from: document.getElementById("adminParsingDateFrom")?.value || "",
        date_to: document.getElementById("adminParsingDateTo")?.value || "",
        text: document.getElementById("adminParsingPipelineInput")?.value || "",
        limit: parsingLogsLimit,
        offset: parsingLogsOffset,
    };
}

function updateAdminLogSourceUi() {
    const source = adminLogSource || "parsing";
    const downloadBtn = document.getElementById("adminParsingDownloadBtn");
    const clearBtn = document.getElementById("adminParsingClearBtn");
    const fileTypeSelect = document.getElementById("adminParsingFileTypeSelect");
    const loginSelect = document.getElementById("adminParsingLoginSelect");
    if (downloadBtn) {
        downloadBtn.disabled = false;
    }
    if (clearBtn) {
        const hasSelectedUser = Boolean(loginSelect?.value);
        clearBtn.disabled = source === "actions" && !hasSelectedUser;
    }
    if (fileTypeSelect) {
        fileTypeSelect.disabled = !(source === "parsing" || source === "errors");
    }
}

function getAdminLogSourceLabel(source) {
    if (source === "actions") return t("adminPage.logSourceActions");
    if (source === "errors") return t("adminPage.logSourceErrors");
    return t("adminPage.logSourceParsing");
}

async function refreshAuditLogs() {
    const list = document.getElementById("adminAuditList");
    const source = adminLogSource || "parsing";
    const parsingFilters = getParsingFilters();
    if (!parsingFilters.login) {
        adminMessage("adminMsg", t("admin.parsingLoginRequired"), "warn");
        list.innerHTML = "";
        lastParsingRowsCount = 0;
        updateParsingPaginationUi();
        return;
    }
    try {
        let rows = [];
        if (source === "actions") {
            const common = getAdminFiltersCommon();
            rows = await getAdminAuditLogs({
                user_id: common.user_id,
                action: common.text,
                date_from: common.date_from,
                date_to: common.date_to,
                limit: common.limit,
                offset: common.offset,
            });
        } else if (source === "errors") {
            const common = getAdminFiltersCommon();
            rows = await getAdminErrorLogs({
                user_id: common.user_id,
                login: getSelectedAdminUserFilter().login || currentUsername || "",
                text: common.text,
                file_type: document.getElementById("adminParsingFileTypeSelect")?.value || "",
                date_from: common.date_from,
                date_to: common.date_to,
                limit: common.limit,
                offset: common.offset,
            });
        } else {
            rows = await getAdminParsingLogs(parsingFilters);
        }
        lastParsingRowsCount = rows.length;
        list.innerHTML = "";
        for (const row of rows) {
            const li = document.createElement("li");
            li.textContent = formatCompactLogLine(row, source);
            list.appendChild(li);
        }
        if (!rows.length) {
            const li = document.createElement("li");
            li.textContent = t("admin.parsingPageInfoEmpty");
            list.appendChild(li);
        }
        updateParsingPaginationUi();
    } catch (err) {
        adminMessage("adminMsg", err?.payload?.message || t("admin.auditLoadFailed"), "error");
    }
}

function formatCompactParsingLogLine(row) {
    const ts = formatTsLocal(row?.ts);
    const sourceType = String(row?.source_type || "unknown");
    const pipeline = String(row?.pipeline || t("admin.notAvailable"));
    const field = String(row?.field || t("admin.notAvailable"));
    const sourceFile = String(row?.source_file || t("admin.notAvailable"));
    const status = String(row?.raw?.status || "parsed");
    const fileShort = sourceFile.length > 40 ? `${sourceFile.slice(0, 40)}...` : sourceFile;
    return t("auditLog.compactLine", {
        ts,
        sourceType,
        pipeline,
        field,
        sourceFile: fileShort,
        status,
    });
}

function formatCompactAuditLine(row) {
    const ts = formatTsLocal(row?.timestamp || row?.ts);
    const userId = row?.user_id ?? t("admin.notAvailable");
    const action = String(row?.action || t("admin.notAvailable"));
    const details = row?.details && typeof row.details === "object" ? JSON.stringify(row.details) : "";
    const trimmed = details.length > 120 ? `${details.slice(0, 120)}...` : details;
    return `${ts} · user=${userId} · ${action}${trimmed ? ` · ${trimmed}` : ""}`;
}

function formatCompactErrorLine(row) {
    const ts = formatTsLocal(row?.ts);
    const kind = String(row?.source_kind || "error");
    const level = String(row?.level || "ERROR").toUpperCase();
    const file = String(row?.filename || "");
    const path = String(row?.path || "");
    const sourceRef = file || path || "-";
    const msg = String(row?.message || t("admin.notAvailable"));
    const requestId = String(row?.request_id || "").trim();
    const requestSuffix = requestId && requestId !== "N/A" ? ` · req=${requestId}` : "";
    return `${ts} · ${kind} · ${level} · ${sourceRef} · ${msg}${requestSuffix}`;
}

function formatTsLocal(value) {
    const raw = String(value || "").trim();
    if (!raw) return t("admin.notAvailable");
    const parsed = new Date(raw);
    if (Number.isNaN(parsed.getTime())) {
        return raw;
    }
    // Показываем локальное время пользователя браузера, чтобы исключить путаницу с UTC.
    return parsed.toLocaleString();
}

function formatCompactLogLine(row, source) {
    if (source === "actions") return formatCompactAuditLine(row);
    if (source === "errors") return formatCompactErrorLine(row);
    return formatCompactParsingLogLine(row);
}

function updateParsingPaginationUi() {
    const prev = document.getElementById("adminParsingPrevBtn");
    const next = document.getElementById("adminParsingNextBtn");
    const info = document.getElementById("adminParsingPageInfo");
    if (!prev || !next || !info) return;
    prev.disabled = parsingLogsOffset <= 0;
    next.disabled = lastParsingRowsCount < parsingLogsLimit;
    if (!lastParsingRowsCount) {
        info.textContent = t("admin.parsingPageInfoEmpty");
        return;
    }
    const from = parsingLogsOffset + 1;
    const to = parsingLogsOffset + lastParsingRowsCount;
    info.textContent = t("admin.parsingPageInfo", { from, to });
}

async function onPrevParsingPage() {
    parsingLogsOffset = Math.max(0, parsingLogsOffset - parsingLogsLimit);
    await refreshAuditLogs();
}

async function onNextParsingPage() {
    if (lastParsingRowsCount < parsingLogsLimit) return;
    parsingLogsOffset += parsingLogsLimit;
    await refreshAuditLogs();
}

async function onResetParsingFilters() {
    const pipeline = document.getElementById("adminParsingPipelineInput");
    const from = document.getElementById("adminParsingDateFrom");
    const to = document.getElementById("adminParsingDateTo");
    const type = document.getElementById("adminParsingFileTypeSelect");
    if (pipeline) pipeline.value = "";
    if (from) from.value = "";
    if (to) to.value = "";
    if (type) type.value = "";
    parsingLogsOffset = 0;
    await refreshAuditLogs();
}

async function onDownloadParsingLogs() {
    try {
        const source = adminLogSource || "parsing";
        const selectedUser = getSelectedAdminUserFilter();
        const common = getAdminFiltersCommon();
        const fileType = document.getElementById("adminParsingFileTypeSelect")?.value || "";
        if (source === "actions") {
            await downloadAdminAuditLogs({
                user_id: common.user_id,
                action: common.text,
                date_from: common.date_from,
                date_to: common.date_to,
            });
        } else if (source === "errors") {
            await downloadAdminErrorLogs({
                user_id: common.user_id,
                login: selectedUser.login || currentUsername || "",
                text: common.text,
                file_type: fileType,
                date_from: common.date_from,
                date_to: common.date_to,
            });
        } else {
            const { login, pipeline, date_from, date_to, file_type } = getParsingFilters();
            if (!login) {
                adminMessage("adminMsg", t("admin.parsingLoginRequired"), "warn");
                return;
            }
            await downloadAdminParsingLogs({ login, pipeline, date_from, date_to, file_type });
        }
        adminMessage("adminMsg", t("admin.parsingDownloadOk"), "success");
    } catch (err) {
        adminMessage("adminMsg", err?.payload?.message || t("admin.parsingDownloadFailed"), "error");
    }
}

async function onClearParsingLogs() {
    const source = adminLogSource || "parsing";
    const selectedUser = getSelectedAdminUserFilter();
    const login = selectedUser.login || currentUsername || "";
    const userId = selectedUser.userId || "";
    if (!login && !userId) {
        adminMessage("adminMsg", t("admin.parsingLoginRequired"), "warn");
        return;
    }
    const sourceLabel = getAdminLogSourceLabel(source);
    if (source === "actions" && !userId) {
        adminMessage("adminMsg", t("admin.parsingLoginRequired"), "warn");
        return;
    }
    if (!(await confirmDialog(
        t("admin.logsClearConfirmBySource", { source: sourceLabel }),
        { confirmTone: "danger" },
    ))) {
        return;
    }
    const accessPassword = await promptDialog(t("admin.logsClearPasswordPrompt"), {
        confirmText: t("adminPage.parsingClearButton"),
        confirmTone: "danger",
        inputType: "password",
    });
    if (accessPassword === null) {
        return;
    }
    if (!String(accessPassword).trim()) {
        adminMessage("adminMsg", t("admin.logsClearPasswordRequired"), "warn");
        return;
    }
    try {
        if (source === "actions") {
            await clearAdminAuditLogs({
                user_id: userId,
                confirm: true,
                accessPassword,
            });
        } else if (source === "errors") {
            await clearAdminErrorLogs({
                user_id: userId,
                login,
                file_type: document.getElementById("adminParsingFileTypeSelect")?.value || "",
                confirm: true,
                accessPassword,
            });
        } else {
            await clearAdminParsingLogs({ login, confirm: true, accessPassword });
        }
        await refreshAuditLogs();
        adminMessage("adminMsg", t("admin.logsClearOkBySource", { source: sourceLabel }), "success");
    } catch (err) {
        adminMessage("adminMsg", err?.payload?.message || t("admin.parsingClearFailed"), "error");
    }
}

document.getElementById("uploadBtn").onclick = async () => {
    if (!isAuthenticated) return;
    if (isProcessingLocked) {
        setBanner("pdfUploadMsg", t("upload.blockedByProcessing"), "warn");
        return;
    }
    const input = document.getElementById("pdfInput");
    setBanner("pdfUploadMsg", "");
    if (!input.files.length) {
        setBanner("pdfUploadMsg", t("upload.choosePdf"), "warn");
        return;
    }

    const files = Array.from(input.files);
    inflightUploadCount += 1;
    syncUploadControlsState();
    setBanner("pdfUploadMsg", t("upload.sendingFiles"), "info");
    pushActivityLog(t("upload.sendingFiles"), "info");
    try {
        // Тип импорта PDF на UI скрыт: всегда чертежи трубопроводов (см. комментарий в index.html).
        const response = await uploadPdf(files, { pdfImportKind: "pipeline_drawings" });
        if (response?.job_id != null) {
            setBanner("pdfUploadMsg", t("upload.filesAccepted"), "success");
            pushActivityLog(t("upload.filesAccepted"), "success");
            isProcessingLocked = true;
            syncUploadControlsState();
            watchJob(response.job_id);
        } else {
            const results = Array.isArray(response?.results) ? response.results : [];
            const errCount = results.filter((r) => r && r.error).length;
            if (errCount > 0) {
                setBanner(
                    "pdfUploadMsg",
                    t("upload.ocrImportDoneWithErrors", { count: errCount }),
                    "warn",
                );
                pushActivityLog(t("upload.ocrImportDoneWithErrors", { count: errCount }), "warn");
            } else {
                setBanner("pdfUploadMsg", t("upload.ocrImportDone"), "success");
                pushActivityLog(t("upload.ocrImportDone"), "success");
            }
        }
    } catch (error) {
        const message = buildFileOnlyErrorMessage(error, t("upload.pdfUploadError"));
        setBanner("pdfUploadMsg", message, "error");
        pushActivityLog(message, "error");
    } finally {
        inflightUploadCount = Math.max(0, inflightUploadCount - 1);
        syncUploadControlsState();
    }
};

document.getElementById("uploadWordBtn").onclick = async () => {
    if (!isAuthenticated) return;
    if (isProcessingLocked) {
        setBanner("wordUploadMsg", t("upload.blockedByProcessing"), "warn");
        return;
    }
    const input = document.getElementById("wordInput");
    setBanner("wordUploadMsg", "");
    if (!input.files.length) {
        setBanner("wordUploadMsg", t("upload.chooseWord"), "warn");
        return;
    }

    const files = Array.from(input.files);
    inflightUploadCount += 1;
    syncUploadControlsState();
    setBanner("wordUploadMsg", t("upload.sendingFiles"), "info");
    pushActivityLog(t("upload.sendingFiles"), "info");

    try {
        const response = await uploadWord(files, { wordImportKind: "passport_vik" });
        setBanner("wordUploadMsg", t("upload.filesAccepted"), "success");
        pushActivityLog(t("upload.filesAccepted"), "success");
        isProcessingLocked = true;
        syncUploadControlsState();
        watchJob(response.job_id);
    } catch (error) {
        const message = buildFileOnlyErrorMessage(error, t("upload.wordUploadError"));
        setBanner("wordUploadMsg", message, "error");
        pushActivityLog(message, "error");
    } finally {
        inflightUploadCount = Math.max(0, inflightUploadCount - 1);
        syncUploadControlsState();
    }
};

document.getElementById("uploadExcelBtn").onclick = async () => {
    if (!isAuthenticated) return;
    if (isProcessingLocked) {
        setBanner("excelUploadMsg", t("upload.blockedByProcessing"), "warn");
        return;
    }
    const input = document.getElementById("excelInput");
    setBanner("excelUploadMsg", "");
    if (!input.files.length) {
        setBanner("excelUploadMsg", t("upload.chooseExcel"), "warn");
        return;
    }

    const files = Array.from(input.files);
    inflightUploadCount += 1;
    syncUploadControlsState();
    setBanner("excelUploadMsg", t("upload.sendingFiles"), "info");
    pushActivityLog(t("upload.sendingFiles"), "info");

    try {
        const response = await uploadExcel(files);
        setBanner("excelUploadMsg", t("upload.filesAccepted"), "success");
        pushActivityLog(t("upload.filesAccepted"), "success");
        isProcessingLocked = true;
        syncUploadControlsState();
        watchJob(response.job_id);
    } catch (error) {
        const message = buildFileOnlyErrorMessage(error, t("upload.excelUploadError"));
        setBanner("excelUploadMsg", message, "error");
        pushActivityLog(message, "error");
    } finally {
        inflightUploadCount = Math.max(0, inflightUploadCount - 1);
        syncUploadControlsState();
    }
};

function hidePdfCheckResultPanel() {
    const result = document.getElementById("pdfCheckResult");
    if (result) {
        result.classList.add("hidden");
    }
    const w1 = document.getElementById("pdfCheckParamsWrap");
    const w2 = document.getElementById("pdfCheckSpecWrap");
    if (w1) {
        w1.innerHTML = "";
    }
    if (w2) {
        w2.innerHTML = "";
    }
}

const pdfCheckCloseEl = document.getElementById("pdfCheckCloseBtn");
if (pdfCheckCloseEl) {
    pdfCheckCloseEl.addEventListener("click", () => {
        hidePdfCheckResultPanel();
    });
}

document.getElementById("pdfCheckBtn").onclick = async () => {
    if (!isAuthenticated) return;
    const input = document.getElementById("pdfCheckInput");
    const result = document.getElementById("pdfCheckResult");
    setBanner("pdfCheckMsg", "");
    if (result) {
        result.classList.add("hidden");
    }
    const files = Array.from(input?.files || []);
    if (!files.length) {
        setBanner("pdfCheckMsg", t("fileCheck.chooseSinglePdf"), "warn");
        return;
    }
    if (files.length !== 1) {
        setBanner("pdfCheckMsg", t("fileCheck.onlyOneFile"), "warn");
        return;
    }
    const file = files[0];
    if (!String(file.name || "").toLowerCase().endsWith(".pdf")) {
        setBanner("pdfCheckMsg", t("fileCheck.chooseSinglePdf"), "warn");
        return;
    }
    setBanner("pdfCheckMsg", t("fileCheck.sending"), "info");
    try {
        const data = await fetchPdfDrawingCheck(file, { page: 1 });
        renderPdfCheckSnapshot(
            "pdfCheckParamsWrap",
            data?.params_png_base64,
            t("importPage.fileCheckParamsTitle"),
        );
        renderPdfCheckSnapshot(
            "pdfCheckSpecWrap",
            data?.spec_png_base64,
            t("importPage.fileCheckSpecTitle"),
        );
        if (result) {
            result.classList.remove("hidden");
        }
        setBanner(
            "pdfCheckMsg",
            t("fileCheck.completed", {
                page: Number(data?.page || 1),
            }),
            "success",
        );
    } catch (error) {
        const message = error?.payload?.message || t("fileCheck.failed");
        setBanner("pdfCheckMsg", message, "error");
    }
};

document.getElementById("loginBtn").onclick = async () => {
    const username = document.getElementById("loginUsername").value.trim();
    const password = document.getElementById("loginPassword").value;
    setBanner("authMsg", "");
    if (!username || !password) {
        setBanner("authMsg", t("auth.loginAndPasswordRequired"), "warn");
        return;
    }
    try {
        await login({
            username,
            password,
        });
        const me = await getCurrentUser();
        resetPasswordFieldVisibility("loginPassword", "loginPasswordToggle");
        setAuthenticatedState(true, me.role, me.username, me.user_id);
        ensureSettingsPageBound();
        resetAuthLostState();
        isProcessingLocked = true;
        syncUploadControlsState();
        setBanner("authMsg", t("auth.loginSuccess"), "success");
        document.getElementById("forcePasswordSection").classList.add("hidden");
        await loadPipelines();
        if ((me.role || "").toLowerCase() === "admin") {
            await bootstrapAdminUi();
            setActivePage("admin");
        } else {
            setActivePage("import");
        }
        await loadChecklist();
        // Восстанавливаем локальный снимок завершённой задачи сразу после логина,
        // чтобы не требовалось ручное обновление страницы.
        resumeActiveJob();
        let activeJobId = null;
        try {
            const active = await getActiveJob();
            if (active && active.job_id) {
                activeJobId = Number(active.job_id);
                watchJob(activeJobId);
            }
        } catch {
            // ignore; socket updates will reconcile
        }
        startLiveUpdates();
        isProcessingLocked = Boolean(activeJobId || hasWatchedJob());
        syncUploadControlsState();
    } catch (err) {
        if (err?.status === 403 && err?.payload?.error === "force_password_change") {
            changePasswordToken = err.payload.change_password_token;
            document.getElementById("forcePasswordSection").classList.remove("hidden");
            setBanner("authMsg", t("auth.forcePasswordChange"), "warn");
            return;
        }
        showAuthError(err, t("auth.loginError"));
    }
};

document.getElementById("changePasswordBtn").onclick = async () => {
    const newPassword = document.getElementById("newPasswordInput").value;
    setBanner("changePasswordMsg", "");
    if (!newPassword) {
        setBanner("changePasswordMsg", t("auth.newPasswordRequired"), "warn");
        return;
    }
    try {
        const result = await changePassword({
            newPassword,
            changePasswordToken,
        });
        changePasswordToken = null;
        document.getElementById("forcePasswordSection").classList.add("hidden");
        document.getElementById("newPasswordInput").value = "";
        document.getElementById("loginPassword").value = "";
        resetPasswordFieldVisibility("newPasswordInput", "newPasswordToggle");
        if (result?.require_relogin) {
            setAuthenticatedState(false);
        }
        setBanner("changePasswordMsg", "");
        setBanner("authMsg", t("auth.passwordChanged"), "success");
    } catch (err) {
        setBanner("changePasswordMsg", extractValidationErrorMessage(err, t("auth.passwordChangeFailed")), "error");
    }
};

document.getElementById("logoutMainBtn").onclick = async () => {
    try {
        await logout();
    } catch {
        // no-op
    }
    clearSessionStateLocally();
    setBanner("authMsg", t("auth.sessionEnded"), "info");
};

async function init() {
    setAuthLostHandler(async () => {
        await forceLogoutToLogin(isAuthenticated ? "auth.sessionExpired" : null);
    });
    bindDomI18n();
    initChecklistSidebar();
    initEmbedmentsPanel();
    bindPasswordVisibilityToggle("loginPassword", "loginPasswordToggle");
    bindPasswordVisibilityToggle("newPasswordInput", "newPasswordToggle");
    bindNavigation();
    setActivePage("import");
    setJobProcessingStateListener((isProcessing) => {
        isProcessingLocked = Boolean(isProcessing);
        if (!isProcessing) {
            setBanner("pdfUploadMsg", "");
            setBanner("excelUploadMsg", "");
        }
        syncUploadControlsState();
    });
    clearTransientMessages();
    syncUploadControlsState();
    const warmupOk = await tryWarmupSession();
    if (!warmupOk) {
        return;
    }
    // 1) local state after reload in the same browser tab/session
    resumeActiveJob();
    let activeJobId = null;
    // 2) server state fallback (works even when localStorage is empty)
    try {
        const active = await getActiveJob();
        if (active && active.job_id) {
            activeJobId = Number(active.job_id);
            watchJob(activeJobId);
        }
    } catch {
        // ignore until authenticated
    }
    startLiveUpdates();
    isProcessingLocked = Boolean(activeJobId || hasWatchedJob());
    syncUploadControlsState();
}

init().catch((e) => {
    console.error("App init failed:", e);
});
