function toBaseName(pathLike) {
    if (!pathLike || typeof pathLike !== "string") return "";
    const chunks = pathLike.split(/[\\/]/);
    return chunks[chunks.length - 1] || pathLike;
}

function extractRowNumber(row) {
    if (typeof row === "number" && Number.isFinite(row)) {
        return String(row);
    }
    if (typeof row === "string") {
        const firstToken = row.trim();
        // Берём только "чистый" порядковый номер из начала строки,
        // чтобы не ловить числа из наименований/ГОСТ/DN/EN.
        const m = firstToken.match(/^0*\d+$/);
        return m ? m[0] : "";
    }
    if (row && typeof row === "object" && !Array.isArray(row)) {
        for (const key of ["row", "row_num", "row_number", "line", "line_number", "index", "no"]) {
            const value = row[key];
            if (value === null || value === undefined) continue;
            // Спецкейс: если row хранится как массив ячеек, порядковый номер в первой ячейке.
            if (Array.isArray(value) && value.length > 0) {
                const firstCell = String(value[0] ?? "").trim();
                const firstCellMatch = firstCell.match(/^0*\d+$/);
                if (firstCellMatch) return firstCellMatch[0];
            } else {
                const token = String(value).trim();
                const m = token.match(/^0*\d+$/);
                if (m) return m[0];
            }
        }
        return "";
    }
    if (Array.isArray(row)) {
        // Для строк таблицы берём только первую колонку как порядковый номер.
        const firstCell = String(row[0] ?? "").trim();
        const m = firstCell.match(/^0*\d+$/);
        if (m) return m[0];
    }
    return "";
}

function extractElementName(row) {
    if (!row || typeof row !== "object") return "";
    for (const key of ["full_name", "item_name", "name"]) {
        const value = String(row[key] || "").trim();
        if (value) return value;
    }
    return "";
}

function detectTableLabel(section, rawError, t) {
    const normalized = String(rawError || "").toLowerCase();
    if (
        section === "process_tables"
        || section === "specification"
        || section === "pipes"
        || section === "section_undefined"
    ) {
        return t("job.invalidTableSpecification");
    }
    if (section === "save_or_update") {
        return t("job.invalidTableSpecification");
    }
    if (
        normalized.includes("parameters table not found")
        || normalized.includes("params table not found")
        || normalized.includes("no parameters table")
    ) {
        return t("job.invalidTableParameters");
    }
    if (
        normalized.includes("specification table not found")
        || normalized.includes("spec table not found")
        || normalized.includes("no specification table")
    ) {
        return t("job.invalidTableSpecification");
    }
    return "";
}

function buildLocationSuffix(row, section, rawError, t) {
    const rowNo = extractRowNumber(row);
    const elementName = extractElementName(row);
    const table = detectTableLabel(section, rawError, t);
    if (table && rowNo) {
        return ` (${t("job.invalidContextTableRow", { table, row: rowNo })})`;
    }
    if (table && elementName) {
        return ` (${t("job.invalidContextTableElement", { table, name: elementName })})`;
    }
    if (table) {
        return ` (${t("job.invalidContextTableOnly", { table })})`;
    }
    if (rowNo) {
        return ` (${t("job.invalidContextRowOnly", { row: rowNo })})`;
    }
    if (elementName) {
        return ` (${t("job.invalidContextElementOnly", { name: elementName })})`;
    }
    return "";
}

function buildShortLocationSuffix(row, t) {
    const rowNo = extractRowNumber(row);
    const elementName = extractElementName(row);
    if (rowNo) {
        return ` (${t("job.invalidContextRowOnly", { row: rowNo })})`;
    }
    if (elementName) {
        return ` (${t("job.invalidContextElementOnly", { name: elementName })})`;
    }
    return "";
}

function inferFriendlyReasonFromRawError(rawError, section, t) {
    const normalized = String(rawError || "").toLowerCase();
    if (!normalized) return "";

    if (normalized.includes("no_data_extracted_from_pdf")) {
        return t("job.invalidReasonNoDataExtracted");
    }
    if (normalized.includes("no_specifications_in_file")) {
        return t("job.invalidReasonNoSpecifications");
    }
    if (normalized.includes("no_pipes_on_spec_page")) {
        return t("job.invalidReasonNoPipesOnSpecPage");
    }
    if (normalized.includes("password") || normalized.includes("encrypted") || normalized.includes("permission")) {
        return t("job.invalidReasonPdfProtected");
    }
    if (
        normalized.includes("corrupt")
        || normalized.includes("damaged")
        || normalized.includes("malformed")
        || normalized.includes("xref")
        || normalized.includes("trailer")
        || normalized.includes("eof")
    ) {
        return t("job.invalidReasonPdfCorrupted");
    }
    if (
        normalized.includes("ocr")
        || normalized.includes("image-only")
        || normalized.includes("no text layer")
        || normalized.includes("cannot extract text")
        || normalized.includes("unreadable")
    ) {
        return t("job.invalidReasonPdfUnreadableScan");
    }
    if (
        normalized.includes("unsupported")
        || normalized.includes("not a pdf")
        || normalized.includes("invalid pdf")
    ) {
        return t("job.invalidReasonPdfFormatUnsupported");
    }
    if (
        normalized.includes("specification table not found")
        || normalized.includes("spec table not found")
        || normalized.includes("no specification table")
    ) {
        return t("job.invalidReasonSpecTableMissing");
    }
    if (
        normalized.includes("parameters table not found")
        || normalized.includes("params table not found")
        || normalized.includes("no parameters table")
    ) {
        return t("job.invalidReasonParamsTableMissing");
    }
    if (
        normalized.includes("validation")
        || normalized.includes("invalid value")
        || normalized.includes("value error")
    ) {
        return t("job.invalidReasonDataValidation");
    }
    if (section === "process_tables" || section === "specification" || section === "pipes") {
        return t("job.invalidReasonSpecTableRow");
    }
    if (section === "file_import") {
        return t("job.invalidReasonFileImport");
    }
    return "";
}

function describeInvalidRowReason(row, t) {
    if (!row || typeof row !== "object") {
        return t("job.invalidReasonFallback");
    }
    const section = String(row.section || "").trim();
    const rawError = String(row.error || "").trim();
    const rowNo = extractRowNumber(row.row);
    const elementName = extractElementName(row);

    const inferredReason = inferFriendlyReasonFromRawError(rawError, section, t);
    if (inferredReason && section !== "save_or_update") {
        return `${inferredReason}${buildLocationSuffix(row, section, rawError, t)}`;
    }
    if (row.kind === "section_undefined") {
        return `${t("job.invalidReasonSectionUndefined")}${buildLocationSuffix(row, section, rawError, t)}`;
    }
    if (section === "cross_file_duplicate") {
        return t("job.invalidReasonCrossFileDuplicate");
    }
    if (section === "cross_file_prefix_mismatch") {
        return t("job.invalidReasonCrossFilePrefixMismatch");
    }
    if (section === "file_import") {
        return t("job.invalidReasonFileImport");
    }
    if (section === "save_or_update") {
        const saveReason = inferredReason || t("job.invalidReasonPipelineSave");
        return `${saveReason}${buildLocationSuffix(row, section, rawError, t)}`;
    }
    if (section === "specification" || section === "pipes") {
        return `${t("job.invalidReasonSpecTableSection")}${buildShortLocationSuffix(row, t)}`;
    }
    if (section === "process_tables") {
        return `${t("job.invalidReasonSpecTableRow")}${buildShortLocationSuffix(row, t)}`;
    }
    // Для пользователя лучше показать понятный доменный fallback,
    // если есть хотя бы контекст строки/элемента.
    if (rowNo || elementName) {
        return `${t("job.invalidReasonSpecTableRow")}${buildShortLocationSuffix(row, t)}`;
    }
    return `${t("job.invalidReasonFallback")}${buildLocationSuffix(row, section, rawError, t)}`;
}

export function buildProblemFilesWithReasons(invalidRows, t) {
    const byFile = new Map();
    for (const item of invalidRows) {
        const fileName = toBaseName(item?.source);
        if (!fileName) continue;
        if (!byFile.has(fileName)) {
            byFile.set(fileName, new Set());
        }
        byFile.get(fileName).add(describeInvalidRowReason(item, t));
    }
    return Array.from(byFile.entries()).map(([fileName, reasonsSet]) => ({
        fileName,
        reasons: Array.from(reasonsSet).filter(Boolean),
    }));
}
