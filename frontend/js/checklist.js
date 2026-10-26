import {
    adminCreateChecklistItem,
    adminDeleteChecklistItem,
    adminUpdateChecklistItem,
    fetchChecklist,
    resetChecklist,
    setChecklistItemDone,
} from "./api.js";
import { confirmDialog } from "./dialogs.js";
import { t } from "./messages.js";

let sidebarListenersBound = false;
let adminChecklistDraftItems = [];

function setChecklistSidebarMsg(text, tone = "info") {
    const el = document.getElementById("checklistSidebarMsg");
    if (!el) return;
    if (!text) {
        el.textContent = "";
        el.classList.add("hidden");
        return;
    }
    el.textContent = text;
    el.dataset.tone = tone;
    el.classList.remove("hidden");
}

function setAdminChecklistMsg(text, tone = "info") {
    const el = document.getElementById("adminChecklistMsg");
    if (!el) return;
    el.textContent = text || "";
    el.dataset.tone = tone;
}

export function clearChecklistUi() {
    const items = document.getElementById("checklistItems");
    const empty = document.getElementById("checklistEmpty");
    if (items) items.innerHTML = "";
    if (empty) empty.classList.add("hidden");
    setChecklistSidebarMsg("");
}

export async function loadChecklist(options = {}) {
    const listEl = document.getElementById("checklistItems");
    const emptyEl = document.getElementById("checklistEmpty");
    if (!listEl) return;
    try {
        setChecklistSidebarMsg("");
        const prefetchedItems = Array.isArray(options.items) ? options.items : null;
        const data = prefetchedItems === null ? await fetchChecklist(options) : null;
        const items = prefetchedItems ?? (Array.isArray(data?.items) ? data.items : []);
        listEl.innerHTML = "";
        if (!items.length) {
            emptyEl?.classList.remove("hidden");
            return;
        }
        emptyEl?.classList.add("hidden");
        for (const it of items) {
            const row = document.createElement("label");
            row.className = "checklist-row";
            row.setAttribute("role", "listitem");
            const cb = document.createElement("input");
            cb.type = "checkbox";
            cb.dataset.itemId = String(it.id);
            cb.checked = Boolean(it.done);
            const span = document.createElement("span");
            span.className = "checklist-row-label";
            span.textContent = it.title;
            row.appendChild(cb);
            row.appendChild(span);
            listEl.appendChild(row);
        }
    } catch (err) {
        setChecklistSidebarMsg(err?.payload?.message || t("checklist.loadFailed"), "error");
        emptyEl?.classList.add("hidden");
    }
}

export function initChecklistSidebar() {
    if (sidebarListenersBound) return;
    sidebarListenersBound = true;
    const listEl = document.getElementById("checklistItems");
    listEl?.addEventListener("change", async (ev) => {
        const input = ev.target;
        if (!input || input.type !== "checkbox") return;
        const id = input.dataset.itemId;
        if (!id) return;
        const done = input.checked;
        try {
            await setChecklistItemDone(id, done);
        } catch (err) {
            input.checked = !done;
            setChecklistSidebarMsg(err?.payload?.message || t("checklist.updateFailed"), "error");
        }
    });

    document.getElementById("checklistResetBtn")?.addEventListener("click", async () => {
        if (!(await confirmDialog(t("checklist.resetConfirm"), { confirmTone: "danger" }))) return;
        try {
            await resetChecklist();
            await loadChecklist();
        } catch (err) {
            setChecklistSidebarMsg(err?.payload?.message || t("checklist.resetFailed"), "error");
        }
    });
}

function sortChecklistItems(items) {
    return [...items].sort((a, b) => {
        const o = (a.sort_order ?? 0) - (b.sort_order ?? 0);
        if (o !== 0) return o;
        return (a.id ?? 0) - (b.id ?? 0);
    });
}

async function persistAdminChecklistOrder(items) {
    for (let index = 0; index < items.length; index += 1) {
        const item = items[index];
        await adminUpdateChecklistItem(item.id, {
            title: item.title,
            sortOrder: index + 1,
        });
    }
}

function moveAdminChecklistItem(items, fromIndex, toIndex) {
    const next = [...items];
    const [moved] = next.splice(fromIndex, 1);
    if (!moved) {
        return [...items];
    }
    next.splice(toIndex, 0, moved);
    return next;
}

async function onReorderAdminChecklistItem(fromIndex, toIndex) {
    if (
        fromIndex < 0
        || fromIndex >= adminChecklistDraftItems.length
        || toIndex < 0
        || toIndex >= adminChecklistDraftItems.length
        || fromIndex === toIndex
    ) {
        return;
    }
    const items = moveAdminChecklistItem(adminChecklistDraftItems, fromIndex, toIndex);
    adminChecklistDraftItems = items;
    renderAdminChecklistRows(adminChecklistDraftItems);
    try {
        await persistAdminChecklistOrder(adminChecklistDraftItems);
        await syncChecklistViews();
        setAdminChecklistMsg(t("adminPage.checklistReordered"), "success");
    } catch (err) {
        await refreshAdminChecklistTable();
        setAdminChecklistMsg(
            err?.payload?.message || t("adminPage.checklistReorderFailed"),
            "error"
        );
    }
}

async function onMoveAdminChecklistItem(index, direction) {
    const targetIndex = index + direction;
    await onReorderAdminChecklistItem(index, targetIndex);
}

function renderAdminChecklistRows(items) {
    const body = document.getElementById("adminChecklistBody");
    if (!body) return;
    body.innerHTML = "";
    for (const [index, it] of items.entries()) {
        const tr = document.createElement("tr");
        const tdOrder = document.createElement("td");
        const orderControls = document.createElement("div");
        orderControls.className = "admin-checklist-order-controls";
        const orderPosition = document.createElement("span");
        orderPosition.className = "admin-checklist-order-position";
        orderPosition.textContent = String(index + 1);
        const moveUpBtn = document.createElement("button");
        moveUpBtn.type = "button";
        moveUpBtn.className = "admin-checklist-order-move-btn btn-muted";
        moveUpBtn.textContent = t("adminPage.checklistMoveUpButton");
        moveUpBtn.disabled = index === 0;
        moveUpBtn.onclick = () => {
            void onMoveAdminChecklistItem(index, -1);
        };
        const moveDownBtn = document.createElement("button");
        moveDownBtn.type = "button";
        moveDownBtn.className = "admin-checklist-order-move-btn btn-muted";
        moveDownBtn.textContent = t("adminPage.checklistMoveDownButton");
        moveDownBtn.disabled = index === items.length - 1;
        moveDownBtn.onclick = () => {
            void onMoveAdminChecklistItem(index, 1);
        };
        orderControls.append(orderPosition, moveUpBtn, moveDownBtn);
        tdOrder.appendChild(orderControls);
        const tdTitle = document.createElement("td");
        const titleInput = document.createElement("input");
        titleInput.type = "text";
        titleInput.maxLength = 500;
        titleInput.value = it.title || "";
        titleInput.className = "admin-checklist-title-input";
        tdTitle.appendChild(titleInput);
        const tdAct = document.createElement("td");
        const saveBtn = document.createElement("button");
        saveBtn.type = "button";
        saveBtn.className = "btn-secondary";
        saveBtn.textContent = t("adminPage.checklistSaveButton");
        saveBtn.onclick = async () => {
            const title = (titleInput.value || "").trim();
            if (!title) {
                setAdminChecklistMsg(t("adminPage.checklistTitleRequired"), "warn");
                return;
            }
            try {
                await adminUpdateChecklistItem(it.id, {
                    title,
                    sortOrder: index + 1,
                });
                await syncChecklistViews();
                setAdminChecklistMsg(t("adminPage.checklistUpdated"), "success");
            } catch (err) {
                setAdminChecklistMsg(err?.payload?.message || t("adminPage.checklistUpdateFailed"), "error");
            }
        };
        const delBtn = document.createElement("button");
        delBtn.type = "button";
        delBtn.className = "btn-danger";
        delBtn.textContent = t("adminPage.checklistDeleteButton");
        delBtn.onclick = async () => {
            if (!(await confirmDialog(t("adminPage.checklistDeleteConfirm"), { confirmTone: "danger" }))) return;
            try {
                await adminDeleteChecklistItem(it.id);
                await syncChecklistViews();
                setAdminChecklistMsg(t("adminPage.checklistDeleted"), "success");
            } catch (err) {
                setAdminChecklistMsg(err?.payload?.message || t("adminPage.checklistDeleteFailed"), "error");
            }
        };
        const actionsWrap = document.createElement("div");
        actionsWrap.className = "table-actions";
        actionsWrap.append(saveBtn, delBtn);
        tdAct.append(actionsWrap);
        tr.append(tdOrder, tdTitle, tdAct);
        body.appendChild(tr);
    }
}

export async function refreshAdminChecklistTable(prefetchedItems = null) {
    const body = document.getElementById("adminChecklistBody");
    if (!body) return;
    let items;
    try {
        if (Array.isArray(prefetchedItems)) {
            items = [...prefetchedItems];
        } else {
            const data = await fetchChecklist({ bustCache: true });
            items = Array.isArray(data.items) ? [...data.items] : [];
        }
    } catch (err) {
        setAdminChecklistMsg(err?.payload?.message || t("checklist.loadFailed"), "error");
        return;
    }
    items = sortChecklistItems(items);
    adminChecklistDraftItems = [...items];
    setAdminChecklistMsg("");
    renderAdminChecklistRows(adminChecklistDraftItems);
}

async function syncChecklistViews() {
    const data = await fetchChecklist({ bustCache: true });
    const items = Array.isArray(data.items) ? data.items : [];
    await refreshAdminChecklistTable(items);
    await loadChecklist({ items });
}

async function handleAdminChecklistAdd() {
    const input = document.getElementById("adminChecklistNewTitle");
    const title = (input?.value || "").trim();
    if (!title) {
        setAdminChecklistMsg(t("adminPage.checklistTitleRequired"), "warn");
        return;
    }
    try {
        await adminCreateChecklistItem(title);
        if (input) input.value = "";
        await syncChecklistViews();
        setAdminChecklistMsg(t("adminPage.checklistCreated"), "success");
    } catch (err) {
        setAdminChecklistMsg(err?.payload?.message || t("adminPage.checklistCreateFailed"), "error");
    }
}

/** Вызывать при каждой успешной инициализации админки — переопределяет onclick, как у остальных кнопок админки. */
export function bindAdminChecklistActions() {
    const btn = document.getElementById("adminChecklistAddBtn");
    const input = document.getElementById("adminChecklistNewTitle");
    if (btn) {
        btn.onclick = () => {
            void handleAdminChecklistAdd();
        };
    }
    if (input) {
        input.onkeydown = (e) => {
            if (e.key === "Enter") {
                e.preventDefault();
                void handleAdminChecklistAdd();
            }
        };
    }
}
