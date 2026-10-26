import { downloadPassport, downloadPassportsZip, getPipelines } from "./api.js";
import { refreshEmbedmentsPipelineOptions } from "./embedments.js";
import { t } from "./messages.js";

let allPipelines = [];
let selectedPipelines = new Set();
let currentQuery = "";
let controlsBound = false;

function buildFileOnlyErrorMessage(error, fallbackMessage) {
    if (error?.payload?.error === "demo_limit_exceeded") {
        const limit = error?.payload?.details?.limit ?? "?";
        const periodDays = error?.payload?.details?.period_days ?? "?";
        return t("pipelines.demoLimitReached", { limit, periodDays });
    }
    const files = Array.isArray(error?.fileNames) ? error.fileNames.filter(Boolean) : [];
    if (!files.length) return error?.payload?.message || fallbackMessage;
    if (files.length === 1) return t("common.problematicFile", { name: files[0] });
    return t("common.problematicFiles", { names: files.join(", ") });
}

function setPipelinesMessage(text = "", tone = "info") {
    const msg = document.getElementById("pipelinesMsg");
    if (!msg) return;
    msg.textContent = text || "";
    msg.dataset.tone = tone;
}

function setPipelinesEmptyState(isEmpty) {
    const empty = document.getElementById("pipelinesEmpty");
    if (!empty) return;
    empty.classList.toggle("hidden", !isEmpty);
    if (isEmpty && !currentQuery) {
        empty.textContent = t("pipelines.empty");
    } else if (isEmpty && currentQuery) {
        empty.textContent = t("pipelines.noMatches");
    }
}

function bindPipelinesControls() {
    if (controlsBound) return;
    controlsBound = true;
    const search = document.getElementById("pipelinesSearchInput");
    const selectAllBtn = document.getElementById("pipelinesSelectAllBtn");
    const clearBtn = document.getElementById("pipelinesClearSelectionBtn");
    const downloadZipBtn = document.getElementById("pipelinesDownloadSelectedBtn");
    if (search) {
        search.placeholder = t("pipelines.searchingPlaceholder");
        search.oninput = () => {
            currentQuery = search.value.trim().toLowerCase();
            renderPipelinesList(allPipelines);
        };
    }
    if (selectAllBtn) {
        selectAllBtn.textContent = t("pipelines.selectAll");
        selectAllBtn.onclick = () => {
            for (const name of getFilteredItems()) {
                selectedPipelines.add(name);
            }
            renderPipelinesList(allPipelines);
        };
    }
    if (clearBtn) {
        clearBtn.textContent = t("pipelines.clearSelection");
        clearBtn.onclick = () => {
            selectedPipelines.clear();
            renderPipelinesList(allPipelines);
        };
    }
    if (downloadZipBtn) {
        downloadZipBtn.textContent = t("pipelines.downloadSelectedZip");
        downloadZipBtn.onclick = onDownloadZipClicked;
    }
}

function updateSelectedCounter() {
    const counter = document.getElementById("pipelinesSelectedCount");
    const downloadZipBtn = document.getElementById("pipelinesDownloadSelectedBtn");
    if (counter) {
        counter.textContent = t("pipelines.selectedCount", { count: selectedPipelines.size });
    }
    if (downloadZipBtn) {
        downloadZipBtn.disabled = selectedPipelines.size === 0;
    }
}

function getFilteredItems() {
    if (!currentQuery) {
        return allPipelines.slice();
    }
    return allPipelines.filter((name) => name.toLowerCase().includes(currentQuery));
}

async function onDownloadZipClicked() {
    if (!selectedPipelines.size) {
        setPipelinesMessage(t("pipelines.chooseAtLeastOne"), "warn");
        return;
    }
    const button = document.getElementById("pipelinesDownloadSelectedBtn");
    if (button) {
        button.disabled = true;
    }
    setPipelinesMessage(t("pipelines.downloadingZip"), "info");
    try {
        await downloadPassportsZip(Array.from(selectedPipelines));
        setPipelinesMessage(t("pipelines.downloadedZip"), "success");
    } catch (error) {
        setPipelinesMessage(buildFileOnlyErrorMessage(error, t("pipelines.downloadZipError")), "error");
    } finally {
        if (button) {
            button.disabled = selectedPipelines.size === 0;
        }
    }
}

export function renderPipelinesList(items) {
    allPipelines = Array.isArray(items) ? items.slice() : [];
    const list = document.getElementById("pipelinesList");
    list.innerHTML = "";
    const names = getFilteredItems();
    setPipelinesEmptyState(!names.length);
    bindPipelinesControls();
    if (!names.length) {
        updateSelectedCounter();
        return;
    }

    for (const name of names) {
        const li = document.createElement("li");
        li.className = "pipeline-row";

        const check = document.createElement("input");
        check.type = "checkbox";
        check.className = "pipeline-checkbox";
        check.checked = selectedPipelines.has(name);
        check.onchange = () => {
            if (check.checked) {
                selectedPipelines.add(name);
            } else {
                selectedPipelines.delete(name);
            }
            updateSelectedCounter();
        };

        const label = document.createElement("div");
        label.className = "pipeline-name";
        label.textContent = name;

        const actions = document.createElement("div");
        actions.className = "pipeline-actions";
        const button = document.createElement("button");
        button.className = "btn-secondary";
        button.textContent = t("pipelines.download");
        button.onclick = async () => {
            button.disabled = true;
            setPipelinesMessage(t("pipelines.downloadingSingle", { name }), "info");
            try {
                await downloadPassport(name);
                setPipelinesMessage(t("pipelines.downloadedSingle", { name }), "success");
            } catch (err) {
                const message = buildFileOnlyErrorMessage(err, t("pipelines.downloadSingleError"));
                setPipelinesMessage(message, "error");
            } finally {
                button.disabled = false;
            }
        };

        actions.appendChild(button);
        li.appendChild(check);
        li.appendChild(label);
        li.appendChild(actions);
        list.appendChild(li);
    }
    updateSelectedCounter();
}

export async function loadPipelines() {
    setPipelinesMessage("");
    const items = await getPipelines();
    selectedPipelines = new Set(Array.from(selectedPipelines).filter((name) => items.includes(name)));
    renderPipelinesList(items);
    refreshEmbedmentsPipelineOptions(items);
}
