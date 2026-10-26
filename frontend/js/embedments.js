import { listInstrumentEmbedments, patchInstrumentEmbedments } from "./api.js";
import { confirmDialog } from "./dialogs.js";
import { t } from "./messages.js";

let embedmentsBound = false;

export const MAX_EMBEDMENT_ELEMENT_ROWS = 20;

function setEmbedmentsMessage(text = "", tone = "info", el) {
    const msg = el ?? document.getElementById("embedmentsMsg");
    if (!msg) return;
    msg.textContent = text || "";
    msg.dataset.tone = tone;
}

export function refreshEmbedmentsPipelineOptions(names) {
    const sel = document.getElementById("embedmentsPipelineSelect");
    if (!sel) return;
    const cur = sel.value;
    sel.innerHTML = "";
    const ph = document.createElement("option");
    ph.value = "";
    ph.textContent = t("embedments.selectPipeline");
    sel.appendChild(ph);
    for (const n of names || []) {
        const o = document.createElement("option");
        o.value = n;
        o.textContent = n;
        sel.appendChild(o);
    }
    if (cur && (names || []).includes(cur)) {
        sel.value = cur;
    }
}

const FIELD_KEYS = ["name", "dn", "pn", "material_grade", "gost"];

function fieldLabel(key) {
    const map = {
        name: "embedments.fieldElementName",
        dn: "embedments.fieldDn",
        pn: "embedments.fieldPn",
        material_grade: "embedments.fieldMaterial",
        gost: "embedments.fieldGost",
    };
    return t(map[key] || key);
}

function readElementBlock(wrap) {
    const out = {};
    for (const key of FIELD_KEYS) {
        const inp = wrap.querySelector(`input[data-field="${key}"]`);
        out[key] = (inp?.value ?? "").trim() || "---";
    }
    return out;
}

function createElementBlock(initial, index1, { removable, onRemove }) {
    const wrap = document.createElement("div");
    wrap.className = "embedment-element-block";

    const head = document.createElement("div");
    head.className = "embedment-element-head";

    const title = document.createElement("span");
    title.className = "embedment-element-title";
    title.textContent = t("embedments.elementTitle", { n: index1 });
    head.appendChild(title);

    if (removable) {
        const rm = document.createElement("button");
        rm.type = "button";
        rm.className = "embedment-remove-element btn-danger";
        rm.textContent = t("embedments.removeElement");
        rm.onclick = () => {
            wrap.remove();
            onRemove?.();
        };
        head.appendChild(rm);
    }
    wrap.appendChild(head);

    const fieldsWrap = document.createElement("div");
    fieldsWrap.className = "embedment-element-fields";

    const init = initial && typeof initial === "object" ? initial : {};
    for (const key of FIELD_KEYS) {
        const row = document.createElement("label");
        row.className = "embedment-field-row";
        const span = document.createElement("span");
        span.textContent = fieldLabel(key);
        const input = document.createElement("input");
        input.type = "text";
        input.dataset.field = key;
        const v = init[key];
        input.value = v && v !== "---" ? String(v) : "";
        row.appendChild(span);
        row.appendChild(input);
        fieldsWrap.appendChild(row);
    }
    wrap.appendChild(fieldsWrap);
    return wrap;
}

/**
 * @param {string} pipelineName
 * @param {object} group — как в ответе GET instrument-embedments
 * @param {{
 *   messageEl?: HTMLElement | null,
 *   pipelineNames?: string[],
 *   onSaved?: (info: { updated: number }) => void | Promise<void>,
 * }} [options]
 */
export function renderEmbedmentGroup(pipelineName, group, options = {}) {
    const msgEl = options.messageEl;
    const pipelineNames =
        Array.isArray(options.pipelineNames) && options.pipelineNames.length
            ? options.pipelineNames
            : pipelineName
              ? [pipelineName]
              : [];

    const wrap = document.createElement("div");
    wrap.className = "embedment-group";

    const head = document.createElement("div");
    head.className = "embedment-group-head";
    const title = document.createElement("div");
    title.className = "embedment-title";
    const tag = group.instrument_tag || group.embedment_group_key || "";
    title.textContent = tag ? `${t("embedments.tagLabel")} ${tag}` : group.name || "—";
    head.appendChild(title);
    wrap.appendChild(head);

    const body = document.createElement("div");
    body.className = "embedment-group-body";

    const imgCol = document.createElement("div");
    imgCol.className = "embedment-image-col";
    if (group.crop_image_url) {
        const img = document.createElement("img");
        img.className = "embedment-crop-img";
        img.alt = "";
        img.src = group.crop_image_url;
        img.loading = "lazy";
        imgCol.appendChild(img);
    } else {
        const p = document.createElement("p");
        p.className = "section-help";
        p.textContent = t("embedments.noImage");
        imgCol.appendChild(p);
    }
    body.appendChild(imgCol);

    const form = document.createElement("div");
    form.className = "embedment-fields";

    const rowsHost = document.createElement("div");
    rowsHost.className = "embedment-elements-list";
    form.appendChild(rowsHost);

    const initialList =
        Array.isArray(group.elements) && group.elements.length > 0
            ? group.elements
            : [{}];

    const addBtn = document.createElement("button");
    addBtn.type = "button";
    addBtn.className = "embedment-add-element btn-secondary";
    addBtn.textContent = t("embedments.addElement");

    const syncAddButtonState = () => {
        const n = rowsHost.querySelectorAll(".embedment-element-block").length;
        addBtn.disabled = n >= MAX_EMBEDMENT_ELEMENT_ROWS;
    };

    const renumberTitles = () => {
        const blocks = rowsHost.querySelectorAll(".embedment-element-block");
        blocks.forEach((b, i) => {
            const sp = b.querySelector(".embedment-element-title");
            if (sp) {
                sp.textContent = t("embedments.elementTitle", { n: i + 1 });
            }
        });
    };

    const updateRemoveVisibility = () => {
        const blocks = rowsHost.querySelectorAll(".embedment-element-block");
        blocks.forEach((b) => {
            const rm = b.querySelector(".embedment-remove-element");
            if (rm) {
                rm.style.display = blocks.length > 1 ? "" : "none";
            }
        });
    };

    const appendBlock = (init) => {
        const idx =
            rowsHost.querySelectorAll(".embedment-element-block").length + 1;
        const block = createElementBlock(init, idx, {
            removable: true,
            onRemove: () => {
                renumberTitles();
                syncAddButtonState();
                updateRemoveVisibility();
            },
        });
        rowsHost.appendChild(block);
        renumberTitles();
        syncAddButtonState();
        updateRemoveVisibility();
    };

    for (const row of initialList) {
        appendBlock(row);
    }

    addBtn.onclick = () => {
        const n = rowsHost.querySelectorAll(".embedment-element-block").length;
        if (n >= MAX_EMBEDMENT_ELEMENT_ROWS) {
            setEmbedmentsMessage(
                t("embedments.maxElements", { max: MAX_EMBEDMENT_ELEMENT_ROWS }),
                "warn",
                msgEl,
            );
            return;
        }
        appendBlock({});
    };
    form.appendChild(addBtn);
    syncAddButtonState();

    const saveBtn = document.createElement("button");
    saveBtn.type = "button";
    saveBtn.className = "primary-action";
    saveBtn.textContent = t("embedments.saveButton");
    saveBtn.onclick = async () => {
        const blocks = rowsHost.querySelectorAll(".embedment-element-block");
        for (const block of blocks) {
            const nameInput = block.querySelector('input[data-field="name"]');
            const nameValue = (nameInput?.value || "").trim();
            if (!nameValue) {
                setEmbedmentsMessage(t("embedments.nameRequired"), "warn", msgEl);
                nameInput?.focus();
                return;
            }
        }
        if (!(await confirmDialog(t("embedments.saveConfirm")))) {
            return;
        }

        saveBtn.disabled = true;
        setEmbedmentsMessage("", "info", msgEl);
        const elements = Array.from(blocks).map((b) => readElementBlock(b));
        try {
            const payload = {
                embedment_group_key: group.embedment_group_key || "",
                instrument_tag: group.instrument_tag || "",
                elements,
            };
            let total = 0;
            for (const pn of pipelineNames) {
                const res = await patchInstrumentEmbedments(pn, payload);
                total += res.updated ?? 0;
            }
            setEmbedmentsMessage(t("embedments.saved", { count: total }), "success", msgEl);
            if (typeof options.onSaved === "function") {
                await options.onSaved({ updated: total });
            }
            await reloadEmbedmentsPipelinePanel();
        } catch {
            setEmbedmentsMessage(t("embedments.saveError"), "error", msgEl);
        } finally {
            saveBtn.disabled = false;
        }
    };
    form.appendChild(saveBtn);
    body.appendChild(form);
    wrap.appendChild(body);
    return wrap;
}

async function loadEmbedmentsForSelection() {
    const sel = document.getElementById("embedmentsPipelineSelect");
    const container = document.getElementById("embedmentsGroups");
    if (!sel || !container) return;
    const name = sel.value.trim();
    container.innerHTML = "";
    if (!name) {
        setEmbedmentsMessage("", "info");
        return;
    }
    setEmbedmentsMessage("", "info");
    try {
        const data = await listInstrumentEmbedments(name);
        const groups = Array.isArray(data.groups) ? data.groups : [];
        if (!groups.length) {
            setEmbedmentsMessage(t("embedments.noGroups"), "info");
            return;
        }
        for (const g of groups) {
            container.appendChild(renderEmbedmentGroup(name, g));
        }
    } catch {
        setEmbedmentsMessage(t("embedments.loadError"), "error");
    }
}

/** Перезагрузка списка закладных на вкладке «Закладные» (если панель есть в DOM). */
export async function reloadEmbedmentsPipelinePanel() {
    await loadEmbedmentsForSelection();
}

export function initEmbedmentsPanel() {
    if (embedmentsBound) return;
    embedmentsBound = true;
    const btn = document.getElementById("embedmentsLoadBtn");
    if (btn) {
        btn.onclick = () => void loadEmbedmentsForSelection();
    }
}
