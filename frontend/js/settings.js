import {
    getAdminAllInstrumentEmbedments,
    getAdminSettingsFileContent,
    listAdminSettingsFiles,
    putAdminSettingsFileContent,
} from "./api.js";
import { renderEmbedmentGroup } from "./embedments.js";
import { t } from "./messages.js";

/** @type {{ title_ru?: string, hint_ru?: string } | null} */
let lastLoadedMeta = null;
/** @type {string | null} */
let currentFilename = null;
/** @type {"armature" | "support" | "spec" | "raw"} */
let currentMode = "raw";

/** @type {object[]} */
let cachedAdminEmbedments = [];

function setSettingsMsg(text, tone = "info") {
    const el = document.getElementById("settingsPageMsg");
    if (!el) return;
    el.textContent = text || "";
    el.dataset.tone = tone;
}

function setEmbedmentsMsg(text, tone = "info") {
    const el = document.getElementById("settingsEmbedmentsMsg");
    if (!el) return;
    el.textContent = text || "";
    el.dataset.tone = tone;
}

function updateFileMeta(meta) {
    const wrap = document.getElementById("settingsFileMeta");
    const titleEl = document.getElementById("settingsSelectedTitle");
    const hintEl = document.getElementById("settingsFileHint");
    if (!wrap || !titleEl || !hintEl) return;
    if (!meta || !meta.title_ru) {
        wrap.classList.add("hidden");
        titleEl.textContent = "";
        hintEl.textContent = "";
        return;
    }
    wrap.classList.remove("hidden");
    titleEl.textContent = meta.title_ru;
    hintEl.textContent = meta.hint_ru || "";
}

function isPlainObject(x) {
    return Boolean(x) && typeof x === "object" && !Array.isArray(x);
}

function isStringKeyedMap(x) {
    if (!isPlainObject(x)) return false;
    for (const v of Object.values(x)) {
        if (v !== null && typeof v !== "string" && typeof v !== "number") {
            return false;
        }
    }
    return true;
}

function isSupportGostValue(value) {
    if (!isPlainObject(value)) return false;
    if (!("exact" in value) || !("family" in value)) return false;
    return isStringKeyedMap(value.exact) && isStringKeyedMap(value.family);
}

// --- spec_item_sections.json: таблицы 4.1–4.4 (как в импорте) → разделы в JSON ---

const SPEC_TABLE_4_1 = "Таблица 4.1";
const SPEC_TABLE_4_2 = "Таблица 4.2";
const SPEC_TABLE_4_3 = "Таблица 4.3";
const SPEC_TABLE_4_4 = "Таблица 4.4";

const SPEC_TABLE_ORDER = [SPEC_TABLE_4_1, SPEC_TABLE_4_2, SPEC_TABLE_4_3, SPEC_TABLE_4_4];

/** @type {Record<string, string>} */
const SECTION_RU_TO_TABLE = {
    Трубы: SPEC_TABLE_4_1,
    "Соединительные детали": SPEC_TABLE_4_1,
    Арматура: SPEC_TABLE_4_2,
    Фланцы: SPEC_TABLE_4_3,
    Опоры: SPEC_TABLE_4_3,
    Закладная: SPEC_TABLE_4_4,
};

/**
 * @param {string} name
 */
function normalizeItemNameForSpec(name) {
    return String(name || "")
        .trim()
        .split(/\s+/)
        .filter(Boolean)
        .join(" ");
}

/**
 * Соответствует resolve_table_choice_to_section_ru (item_name задан).
 * @param {string} table
 * @param {string} itemName
 */
function resolveTableToSectionRu(table, itemName) {
    const nk = normalizeItemNameForSpec(itemName);
    if (table === SPEC_TABLE_4_1) {
        if (nk && /^(труба|трубы)\b/i.test(nk)) return "Трубы";
        if (nk) return "Соединительные детали";
        return "Соединительные детали";
    }
    if (table === SPEC_TABLE_4_3) {
        if (nk && /^(опора|опоры)\b/i.test(nk)) return "Опоры";
        if (nk) return "Фланцы";
        return "Фланцы";
    }
    if (table === SPEC_TABLE_4_2) return "Арматура";
    if (table === SPEC_TABLE_4_4) return "Закладная";
    return "Соединительные детали";
}

/**
 * @param {string} sectionRu
 */
function sectionRuToTableSelectValue(sectionRu) {
    const s = String(sectionRu ?? "").trim();
    const tbl = SECTION_RU_TO_TABLE[s];
    if (tbl) return tbl;
    return `__legacy__:${encodeURIComponent(s)}`;
}

/**
 * @param {string} selectValue
 * @param {string} itemKey
 */
function selectValueToSectionRu(selectValue, itemKey) {
    if (!selectValue) return "";
    if (selectValue.startsWith("__legacy__:")) {
        try {
            return decodeURIComponent(selectValue.slice("__legacy__:".length));
        } catch {
            return "";
        }
    }
    return resolveTableToSectionRu(selectValue, itemKey);
}

/**
 * @param {HTMLSelectElement} selectEl
 * @param {string} selectedValue
 */
function fillSpecTableSelect(selectEl, selectedValue) {
    selectEl.innerHTML = "";
    const ph = document.createElement("option");
    ph.value = "";
    ph.textContent = t("settingsPage.specTablePlaceholder");
    selectEl.appendChild(ph);
    for (const tbl of SPEC_TABLE_ORDER) {
        const opt = document.createElement("option");
        opt.value = tbl;
        const short = tbl.replace("Таблица ", "").trim();
        opt.textContent = short;
        opt.title = tbl;
        selectEl.appendChild(opt);
    }

    if (selectedValue.startsWith("__legacy__:")) {
        let raw = "";
        try {
            raw = decodeURIComponent(selectedValue.slice("__legacy__:".length));
        } catch {
            raw = selectedValue;
        }
        const leg = document.createElement("option");
        leg.value = selectedValue;
        leg.textContent = t("settingsPage.specLegacyValue", { value: raw });
        selectEl.appendChild(leg);
    }

    selectEl.value = selectedValue;
    if (selectEl.value !== selectedValue) {
        selectEl.value = "";
    }
}

/**
 * @param {HTMLElement} rowsHost
 * @param {string} key
 * @param {string} storedSectionRu
 */
function appendSpecKvRow(rowsHost, key, storedSectionRu) {
    const row = document.createElement("div");
    row.className = "settings-kv-row";
    const k = document.createElement("input");
    k.type = "text";
    k.className = "settings-kv-key";
    k.value = key;
    k.setAttribute("autocomplete", "off");
    const sel = document.createElement("select");
    sel.className = "settings-kv-value settings-kv-value-select";
    fillSpecTableSelect(sel, sectionRuToTableSelectValue(String(storedSectionRu ?? "")));
    const rm = document.createElement("button");
    rm.type = "button";
    rm.className = "btn-secondary settings-kv-remove";
    rm.textContent = t("settingsPage.removeRow");
    rm.onclick = () => row.remove();
    row.appendChild(k);
    row.appendChild(sel);
    row.appendChild(rm);
    rowsHost.appendChild(row);
}

/**
 * @param {HTMLElement} rowsHost
 */
function readSpecKvRows(rowsHost) {
    const out = {};
    for (const row of rowsHost.querySelectorAll(".settings-kv-row")) {
        const kInp = row.querySelector(".settings-kv-key");
        const sel = row.querySelector("select.settings-kv-value-select");
        const k = (kInp?.value ?? "").trim();
        if (!k) continue;
        const raw = (sel?.value ?? "").trim();
        if (!raw) continue;
        out[k] = selectValueToSectionRu(raw, k);
    }
    return out;
}

/**
 * @param {Record<string, string | number>} initial
 */
function buildSpecKvSection(initial) {
    const wrap = document.createElement("div");
    wrap.className = "settings-kv-section settings-kv-section--spec";
    const header = document.createElement("div");
    header.className = "settings-kv-header";
    const hk = document.createElement("span");
    hk.textContent = t("settingsPage.keyColumn");
    const hv = document.createElement("span");
    hv.textContent = t("settingsPage.tableColumn");
    header.appendChild(hk);
    header.appendChild(hv);
    header.appendChild(document.createElement("span"));
    wrap.appendChild(header);
    const rows = document.createElement("div");
    rows.className = "settings-kv-rows";
    const obj = isPlainObject(initial) ? initial : {};
    const entries = Object.entries(obj);
    if (entries.length === 0) {
        appendSpecKvRow(rows, "", "");
    } else {
        for (const [k, v] of entries) {
            appendSpecKvRow(rows, k, String(v));
        }
    }
    const add = document.createElement("button");
    add.type = "button";
    add.className = "btn-secondary settings-kv-add";
    add.textContent = t("settingsPage.addRow");
    add.onclick = () => appendSpecKvRow(rows, "", "");
    wrap.appendChild(rows);
    wrap.appendChild(add);
    return wrap;
}

/**
 * @param {HTMLElement} rowsHost
 * @param {string} key
 * @param {string} val
 */
function appendKvRow(rowsHost, key, val) {
    const row = document.createElement("div");
    row.className = "settings-kv-row";
    const k = document.createElement("input");
    k.type = "text";
    k.className = "settings-kv-key";
    k.value = key;
    k.setAttribute("autocomplete", "off");
    const v = document.createElement("input");
    v.type = "text";
    v.className = "settings-kv-value";
    v.value = val;
    v.setAttribute("autocomplete", "off");
    const rm = document.createElement("button");
    rm.type = "button";
    rm.className = "btn-secondary settings-kv-remove";
    rm.textContent = t("settingsPage.removeRow");
    rm.onclick = () => row.remove();
    row.appendChild(k);
    row.appendChild(v);
    row.appendChild(rm);
    rowsHost.appendChild(row);
}

/**
 * @param {HTMLElement} rowsHost
 */
function readKvRows(rowsHost) {
    const out = {};
    for (const row of rowsHost.querySelectorAll(".settings-kv-row")) {
        const kInp = row.querySelector(".settings-kv-key");
        const vInp = row.querySelector(".settings-kv-value");
        const k = (kInp?.value ?? "").trim();
        if (!k) continue;
        out[k] = String(vInp?.value ?? "").trim();
    }
    return out;
}

/**
 * @param {Record<string, string | number>} initial
 * @param {string} sectionClass
 */
function buildKvSection(initial, sectionClass) {
    const wrap = document.createElement("div");
    wrap.className = `settings-kv-section ${sectionClass}`;
    const header = document.createElement("div");
    header.className = "settings-kv-header";
    const hk = document.createElement("span");
    hk.textContent = t("settingsPage.keyColumn");
    const hv = document.createElement("span");
    hv.textContent = t("settingsPage.valueColumn");
    header.appendChild(hk);
    header.appendChild(hv);
    header.appendChild(document.createElement("span")); // spacer for remove btn column
    wrap.appendChild(header);
    const rows = document.createElement("div");
    rows.className = "settings-kv-rows";
    const obj = isPlainObject(initial) ? initial : {};
    const entries = Object.entries(obj);
    if (entries.length === 0) {
        appendKvRow(rows, "", "");
    } else {
        for (const [k, v] of entries) {
            appendKvRow(rows, k, String(v));
        }
    }
    const add = document.createElement("button");
    add.type = "button";
    add.className = "btn-secondary settings-kv-add";
    add.textContent = t("settingsPage.addRow");
    add.onclick = () => appendKvRow(rows, "", "");
    wrap.appendChild(rows);
    wrap.appendChild(add);
    return wrap;
}

/**
 * @param {HTMLElement} host
 * @param {object} value
 * @param {"armature" | "spec"} mode
 */
function renderArmatureOrSpecEditor(host, value, mode) {
    currentMode = mode;
    const map = isStringKeyedMap(value) ? value : {};
    if (mode === "spec") {
        host.appendChild(buildSpecKvSection(map));
        return;
    }
    const section = buildKvSection(map, "settings-kv-section--flat");
    host.appendChild(section);
}

/**
 * @param {HTMLElement} host
 * @param {object} value
 */
function renderSupportGostEditor(host, value) {
    currentMode = "support";
    const exact = isPlainObject(value.exact) ? value.exact : {};
    const family = isPlainObject(value.family) ? value.family : {};

    const hExact = document.createElement("h4");
    hExact.className = "settings-subsection-title";
    hExact.textContent = t("settingsPage.supportExact");
    host.appendChild(hExact);
    const ex = buildKvSection(exact, "settings-kv-section--exact");
    ex.dataset.section = "exact";
    host.appendChild(ex);

    const hFam = document.createElement("h4");
    hFam.className = "settings-subsection-title";
    hFam.textContent = t("settingsPage.supportFamily");
    host.appendChild(hFam);
    const fam = buildKvSection(family, "settings-kv-section--family");
    fam.dataset.section = "family";
    host.appendChild(fam);
}

/**
 * @param {HTMLElement} host
 * @param {string} text
 * @param {{ onFormat?: () => void }} [opts]
 */
function renderRawJsonEditor(host, text, opts = {}) {
    currentMode = "raw";
    const label = document.createElement("label");
    label.className = "settings-json-label";
    label.setAttribute("for", "settingsJsonTextarea");
    label.textContent = t("settingsPage.fallbackJsonLabel");
    const ta = document.createElement("textarea");
    ta.id = "settingsJsonTextarea";
    ta.className = "settings-json-editor";
    ta.spellcheck = false;
    ta.value = text;
    host.appendChild(label);
    host.appendChild(ta);
    const actions = document.createElement("div");
    actions.className = "inline-actions settings-raw-actions";
    if (opts.onFormat) {
        const formatBtn = document.createElement("button");
        formatBtn.type = "button";
        formatBtn.className = "btn-secondary";
        formatBtn.textContent = t("settingsPage.formatButton");
        formatBtn.onclick = opts.onFormat;
        actions.appendChild(formatBtn);
    }
    host.appendChild(actions);
}

function collectEditorValue() {
    const host = document.getElementById("settingsEditorHost");
    if (!host || !currentFilename) return { ok: false, value: null };

    if (currentMode === "raw") {
        const ta = host.querySelector("#settingsJsonTextarea");
        const raw = (ta?.value ?? "").trim();
        if (!raw) {
            setSettingsMsg(t("settingsPage.invalidJson"), "warn");
            return { ok: false, value: null };
        }
        try {
            return { ok: true, value: JSON.parse(raw) };
        } catch {
            setSettingsMsg(t("settingsPage.invalidJson"), "error");
            return { ok: false, value: null };
        }
    }

    if (currentMode === "spec") {
        const rows = host.querySelector(".settings-kv-section--spec .settings-kv-rows");
        if (!rows) return { ok: false, value: null };
        return { ok: true, value: readSpecKvRows(rows) };
    }

    if (currentMode === "armature") {
        const rows = host.querySelector(".settings-kv-rows");
        if (!rows) return { ok: false, value: null };
        return { ok: true, value: readKvRows(rows) };
    }

    if (currentMode === "support") {
        const exactWrap = host.querySelector('.settings-kv-section[data-section="exact"]');
        const familyWrap = host.querySelector('.settings-kv-section[data-section="family"]');
        const exRows = exactWrap?.querySelector(".settings-kv-rows");
        const famRows = familyWrap?.querySelector(".settings-kv-rows");
        if (!exRows || !famRows) return { ok: false, value: null };
        return {
            ok: true,
            value: {
                exact: readKvRows(exRows),
                family: readKvRows(famRows),
            },
        };
    }

    return { ok: false, value: null };
}

function renderEditorForFile(filename, data) {
    const host = document.getElementById("settingsEditorHost");
    if (!host) return;
    host.innerHTML = "";
    currentFilename = filename;
    let value = data.value;
    let usedStructured = false;

    const tryStructured = () => {
        if (filename === "armature_gost.json") {
            if (isStringKeyedMap(value)) {
                renderArmatureOrSpecEditor(host, value, "armature");
                usedStructured = true;
                return;
            }
        } else if (filename === "spec_item_sections.json") {
            if (isStringKeyedMap(value)) {
                renderArmatureOrSpecEditor(host, value, "spec");
                usedStructured = true;
                return;
            }
        } else if (filename === "support_gost_mapping.json") {
            if (isSupportGostValue(value)) {
                renderSupportGostEditor(host, value);
                usedStructured = true;
            }
        }
    };

    tryStructured();

    if (!usedStructured) {
        if (
            filename === "armature_gost.json"
            || filename === "spec_item_sections.json"
            || filename === "support_gost_mapping.json"
        ) {
            setSettingsMsg(t("settingsPage.unstructuredFallback"), "warn");
        }
        const text = JSON.stringify(value, null, 2);
        renderRawJsonEditor(host, text, {
            onFormat: () => {
                const ta = host.querySelector("#settingsJsonTextarea");
                if (!ta) return;
                const raw = ta.value.trim();
                if (!raw) {
                    setSettingsMsg(t("settingsPage.formatEmpty"), "warn");
                    return;
                }
                try {
                    const v = JSON.parse(raw);
                    ta.value = JSON.stringify(v, null, 2);
                    setSettingsMsg(t("settingsPage.formatOk"), "success");
                } catch {
                    setSettingsMsg(t("settingsPage.formatError"), "error");
                }
            },
        });
    }
}

export async function refreshSettingsFileList({ preserveSelection = true } = {}) {
    const sel = document.getElementById("settingsConfigFileSelect");
    if (!sel) return;
    const prev = preserveSelection ? sel.value : "";
    try {
        const data = await listAdminSettingsFiles();
        const entries = Array.isArray(data.entries) ? data.entries : [];
        sel.innerHTML = "";
        const ph = document.createElement("option");
        ph.value = "";
        ph.textContent = t("settingsPage.selectPlaceholder");
        sel.appendChild(ph);

        for (const e of entries) {
            const opt = document.createElement("option");
            opt.value = encodeURIComponent(e.filename);
            opt.textContent = e.title_ru;
            opt.title = `${e.filename} — ${e.hint_ru || ""}`;
            sel.appendChild(opt);
        }

        if (prev && entries.some((e) => encodeURIComponent(e.filename) === prev)) {
            sel.value = prev;
        }
        setSettingsMsg("");
    } catch (err) {
        setSettingsMsg(err?.payload?.message || t("settingsPage.listLoadError"), "error");
    }
}

async function loadSelectedFileIntoEditor() {
    const sel = document.getElementById("settingsConfigFileSelect");
    if (!sel) return;
    const enc = (sel.value || "").trim();
    if (!enc) {
        currentFilename = null;
        lastLoadedMeta = null;
        updateFileMeta(null);
        const host = document.getElementById("settingsEditorHost");
        if (host) host.innerHTML = "";
        return;
    }
    let filename;
    try {
        filename = decodeURIComponent(enc);
    } catch {
        setSettingsMsg(t("settingsPage.fileLoadError"), "error");
        return;
    }
    try {
        const data = await getAdminSettingsFileContent(filename);
        lastLoadedMeta = {
            title_ru: data.title_ru,
            hint_ru: data.hint_ru,
        };
        updateFileMeta(lastLoadedMeta);
        setSettingsMsg("");
        renderEditorForFile(filename, data);
    } catch (err) {
        lastLoadedMeta = null;
        updateFileMeta(null);
        currentFilename = null;
        const host = document.getElementById("settingsEditorHost");
        if (host) host.innerHTML = "";
        setSettingsMsg(err?.payload?.message || t("settingsPage.fileLoadError"), "error");
    }
}

function normalizeSearchQuery(text) {
    return String(text || "")
        .trim()
        .toLowerCase();
}

const ADMIN_DASH_CHARS = /[\u2010\u2011\u2012\u2013\u2014\u2212\uFE58\uFE63\uFF0D]/g;

/** Как на бэкенде: NFKC, дефисы, ZWSP/BOM, пробелы, нижний регистр — для дедупа и поиска. */
function normalizeAdminTagDedupKey(raw) {
    let s = String(raw || "").normalize("NFKC").replace(ADMIN_DASH_CHARS, "-");
    s = s.replace(/[\u200b\u200c\u200d\ufeff\u2060]/g, "");
    s = s.trim().split(/\s+/).join(" ").trim();
    return s.toLowerCase();
}

function instrumentTagForEntry(entry) {
    const direct = entry.list_instrument_tag;
    if (direct != null && String(direct).trim()) {
        return String(direct).trim();
    }
    const g = entry.group || {};
    return String(g.instrument_tag ?? "").trim();
}

function adminEmbedmentListDedupKey(entry) {
    const tagLine = instrumentTagForEntry(entry);
    if (tagLine) {
        return `i:${normalizeAdminTagDedupKey(tagLine)}`;
    }
    const pipe = String(entry.pipeline_name || "").trim().toLowerCase();
    const pos = entry.position ?? "";
    const page = String(entry.page ?? "");
    return `b:${pipe}:${page}:${pos}`;
}

function adminEmbedmentPipelineLabels(entry) {
    const raw = entry.pipeline_names;
    if (Array.isArray(raw) && raw.length) {
        return raw.map((p) => String(p || "").trim()).filter(Boolean);
    }
    const one = String(entry.pipeline_name || "").trim();
    return one ? [one] : [];
}

function adminFlatRowScore(row) {
    const g = row.group || {};
    const peers = Array.isArray(g.peer_tags) ? g.peer_tags.length : 0;
    const crop = (g.crop_image_url || "").trim() ? 1 : 0;
    const path = (g.drawing_image_path || "").trim() ? 1 : 0;
    return peers * 100 + crop * 10 + path;
}

function dedupeAdminEmbedmentsList(rows) {
    const best = new Map();
    for (const row of rows) {
        const k = adminEmbedmentListDedupKey(row);
        const prev = best.get(k);
        if (prev == null || adminFlatRowScore(row) > adminFlatRowScore(prev)) {
            best.set(k, row);
        }
    }
    return Array.from(best.values());
}

function sortAdminEmbedmentsList(arr) {
    return [...arr].sort((a, b) => {
        const cTag = normalizeAdminTagDedupKey(instrumentTagForEntry(a)).localeCompare(
            normalizeAdminTagDedupKey(instrumentTagForEntry(b)),
        );
        if (cTag !== 0) return cTag;
        const pipesA = adminEmbedmentPipelineLabels(a).sort().join(",");
        const pipesB = adminEmbedmentPipelineLabels(b).sort().join(",");
        const cPipes = pipesA.localeCompare(pipesB);
        if (cPipes !== 0) return cPipes;
        const pa = Number(a.position) || 0;
        const pb = Number(b.position) || 0;
        if (pa !== pb) return pa - pb;
        return String(a.page || "").localeCompare(String(b.page || ""));
    });
}

function embedmentEntryMatchesSearch(entry, qLower) {
    if (!qLower) return true;
    const tag = normalizeAdminTagDedupKey(instrumentTagForEntry(entry));
    if (tag && tag.includes(qLower)) return true;
    const pipes = adminEmbedmentPipelineLabels(entry)
        .join(" ")
        .toLowerCase();
    return pipes.includes(qLower);
}

export function renderEmbedmentsFromCache() {
    const container = document.getElementById("settingsEmbedmentsContainer");
    if (!container) return;
    const searchEl = document.getElementById("settingsEmbedmentsSearch");
    const qLower = normalizeSearchQuery(searchEl?.value);
    container.innerHTML = "";

    if (!cachedAdminEmbedments.length) {
        return;
    }

    const filtered = cachedAdminEmbedments.filter((e) => embedmentEntryMatchesSearch(e, qLower));
    if (!filtered.length) {
        setEmbedmentsMsg(
            qLower ? t("settingsPage.embedmentsNoSearchHits") : t("settingsPage.noEmbedments"),
            qLower ? "warn" : "info",
        );
        return;
    }

    setEmbedmentsMsg("");
    const msgEl = document.getElementById("settingsEmbedmentsMsg");
    for (const emb of filtered) {
        const details = document.createElement("details");
        details.className = "settings-embed-item";
        details.open = false;
        const sum = document.createElement("summary");
        sum.className = "settings-embed-item-summary";
        const g = emb.group || {};
        const tagLine = instrumentTagForEntry(emb) || "—";
        const pipes = adminEmbedmentPipelineLabels(emb);
        sum.textContent = tagLine;
        details.appendChild(sum);
        const body = document.createElement("div");
        body.className = "settings-embed-item-body";
        body.appendChild(
            renderEmbedmentGroup(pipes[0] || "", g, {
                messageEl: msgEl,
                pipelineNames: pipes,
                onSaved: refreshSettingsEmbedments,
            }),
        );
        details.appendChild(body);
        container.appendChild(details);
    }
}

export async function refreshSettingsEmbedments() {
    const container = document.getElementById("settingsEmbedmentsContainer");
    if (!container) return;
    setEmbedmentsMsg("");
    container.innerHTML = "";
    cachedAdminEmbedments = [];
    try {
        const data = await getAdminAllInstrumentEmbedments();
        const raw = Array.isArray(data.embedments) ? data.embedments : [];
        cachedAdminEmbedments = sortAdminEmbedmentsList(dedupeAdminEmbedmentsList(raw));
        if (!cachedAdminEmbedments.length) {
            setEmbedmentsMsg(t("settingsPage.noEmbedments"), "info");
            return;
        }
        renderEmbedmentsFromCache();
    } catch (err) {
        setEmbedmentsMsg(
            err?.payload?.message || t("settingsPage.embedmentsLoadError"),
            "error",
        );
    }
}

export async function onSettingsPageShown() {
    await refreshSettingsFileList({ preserveSelection: true });
    await loadSelectedFileIntoEditor();
    await refreshSettingsEmbedments();
}

export function bindSettingsPage() {
    const sel = document.getElementById("settingsConfigFileSelect");
    const reloadBtn = document.getElementById("settingsReloadBtn");
    const saveBtn = document.getElementById("settingsSaveBtn");
    const embReload = document.getElementById("settingsEmbedmentsReload");
    const embSearch = document.getElementById("settingsEmbedmentsSearch");
    if (!sel || !reloadBtn || !saveBtn) return;

    sel.addEventListener("change", () => {
        void loadSelectedFileIntoEditor();
    });
    reloadBtn.addEventListener("click", () => {
        void refreshSettingsFileList({ preserveSelection: true }).then(() =>
            loadSelectedFileIntoEditor(),
        );
    });
    saveBtn.addEventListener("click", async () => {
        if (!currentFilename) {
            setSettingsMsg(t("settingsPage.noFileSelected"), "warn");
            return;
        }
        const parsed = collectEditorValue();
        if (!parsed.ok) return;
        try {
            await putAdminSettingsFileContent(currentFilename, parsed.value);
            const title = lastLoadedMeta?.title_ru || currentFilename;
            setSettingsMsg(t("settingsPage.saveOk", { title }), "success");
        } catch (err) {
            setSettingsMsg(err?.payload?.message || t("settingsPage.saveError"), "error");
        }
    });
    if (embReload) {
        embReload.addEventListener("click", () => {
            void refreshSettingsEmbedments();
        });
    }
    if (embSearch) {
        embSearch.addEventListener("input", () => {
            renderEmbedmentsFromCache();
        });
    }
}
