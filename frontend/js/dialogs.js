import { t } from "./messages.js";

function _isBrowserDialogAvailable() {
    return typeof document !== "undefined" && typeof window !== "undefined";
}

function _buildDialog({
    message,
    confirmText,
    cancelText,
    confirmTone = "primary",
    mode = "confirm",
    defaultValue = "",
    inputType = "text",
}) {
    const backdrop = document.createElement("div");
    backdrop.className = "app-dialog-backdrop";

    const panel = document.createElement("div");
    panel.className = "app-dialog";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-modal", "true");
    panel.tabIndex = -1;

    const text = document.createElement("p");
    text.className = "app-dialog-message";
    text.textContent = message || "";
    panel.appendChild(text);

    let input = null;
    if (mode === "prompt") {
        input = document.createElement("input");
        input.type = inputType || "text";
        input.className = "app-dialog-input";
        input.value = defaultValue || "";
        panel.appendChild(input);
    }

    const actions = document.createElement("div");
    actions.className = "app-dialog-actions";

    const cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "btn-muted";
    cancelBtn.textContent = cancelText || t("common.cancel");
    actions.appendChild(cancelBtn);

    const confirmBtn = document.createElement("button");
    confirmBtn.type = "button";
    if (confirmTone === "danger") {
        confirmBtn.className = "btn-danger";
    } else if (confirmTone === "secondary") {
        confirmBtn.className = "btn-secondary";
    } else {
        confirmBtn.className = "primary-action";
    }
    confirmBtn.textContent = confirmText || t("common.confirm");
    actions.appendChild(confirmBtn);

    panel.appendChild(actions);
    backdrop.appendChild(panel);

    return {
        backdrop,
        panel,
        input,
        cancelBtn,
        confirmBtn,
        mode,
    };
}

function _showDialog(config) {
    if (!_isBrowserDialogAvailable()) {
        if (config.mode === "prompt") {
            return Promise.resolve(window.prompt(config.message || "") ?? null);
        }
        return Promise.resolve(window.confirm(config.message || ""));
    }

    return new Promise((resolve) => {
        const dialog = _buildDialog(config);
        const { backdrop, panel, input, cancelBtn, confirmBtn, mode } = dialog;
        let closed = false;

        const close = (value) => {
            if (closed) return;
            closed = true;
            document.removeEventListener("keydown", onKeyDown, true);
            backdrop.remove();
            resolve(value);
        };

        const onKeyDown = (event) => {
            if (event.key === "Escape") {
                event.preventDefault();
                close(mode === "prompt" ? null : false);
                return;
            }
            if (event.key === "Enter") {
                if (mode === "prompt" && document.activeElement === cancelBtn) return;
                event.preventDefault();
                close(mode === "prompt" ? (input?.value ?? "") : true);
            }
        };

        cancelBtn.onclick = () => close(mode === "prompt" ? null : false);
        confirmBtn.onclick = () => close(mode === "prompt" ? (input?.value ?? "") : true);

        backdrop.onclick = (event) => {
            if (event.target === backdrop) {
                close(mode === "prompt" ? null : false);
            }
        };

        document.addEventListener("keydown", onKeyDown, true);
        document.body.appendChild(backdrop);
        if (input) {
            input.focus();
            input.select();
        } else {
            panel.focus();
        }
    });
}

export function confirmDialog(message, options = {}) {
    return _showDialog({
        message,
        mode: "confirm",
        confirmText: options.confirmText || t("common.yes"),
        cancelText: options.cancelText || t("common.no"),
        confirmTone: options.confirmTone || "primary",
    });
}

export function promptDialog(message, options = {}) {
    return _showDialog({
        message,
        mode: "prompt",
        confirmText: options.confirmText || t("common.confirm"),
        cancelText: options.cancelText || t("common.cancel"),
        confirmTone: options.confirmTone || "primary",
        inputType: options.inputType || "text",
        defaultValue: options.defaultValue || "",
    });
}
