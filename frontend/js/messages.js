/**
 * Все пользовательские строки интерфейса (редактирование, будущий перевод).
 * Ключи вида "раздел.подраздел.имя" — функция t("раздел.подраздел.имя", { param }).
 */
export const UI_MESSAGES = {
    meta: {
        documentTitle: "Паспорта трубопроводов",
    },
    pageMeta: {
        import: {
            title: "Импорт и задачи",
            subtitle: "Загрузите PDF, Word или Excel архивом (zip, rar) или отдельными файлами (pdf, word, excel).",
            nextStep: "Важно: новые трубопроводы добавляются только из чертежей pdf и автоматически появляются в списке паспортов.\nCначала загрузите все чертежи pdf, затем остальные файлы.",
        },
        pipelines: {
            title: "Паспорта",
            subtitle: "Найдите нужный номер трубопровода, отметьте один или несколько и скачайте.",
            nextStep: "При множественном выборе скачаются все выбранные паспорта в ZIP-архиве.",
        },
        admin: {
            title: "Администрирование",
            subtitle: "Управление пользователями, чек-листом и логами системы.",
            nextStep: "Здесь можно добавить/удалить/изменить роли пользователей, настроить общий чек-лист и просмотреть логи по источникам.",
        },
        settings: {
            title: "Настройки",
            subtitle: "Справочники и закладные.",
            nextStep: "Справочник — кнопка «Сохранить файл». Закладная — «Сохранить» в открытой карточке.",
        },
    },
    authPage: {
        mainTitle: "Паспорта трубопроводов",
        loginTitle: "Вход в систему",
        help: "Введите учетные данные для входа в систему.",
        nextStep: "При входе по временному паролю необходимо сменить его на новый и войти снова.",
        placeholderUsername: "Логин",
        placeholderPassword: "Пароль",
        placeholderMfaCode: "Код MFA",
        mfaRowHint: "Шаг 2: введите код из приложения-аутентификатора.",
        loginButton: "Войти",
        forcePasswordTitle: "Требуется смена пароля",
        forcePasswordHelp: "Для первого входа необходимо задать новый пароль.",
        placeholderNewPassword: "Новый пароль",
        changePasswordButton: "Сменить пароль",
        showPassword: "Показать пароль",
        hidePassword: "Скрыть пароль",
    },
    layout: {
        workspaceTitle: "Паспорта трубопроводов",
        logout: "Выйти",
        sidebarTitle: "Разделы",
        navImport: "Импорт и задачи",
        navPipelines: "Паспорта",
        navSettings: "Настройки",
        navAdmin: "Админка",
    },
    checklist: {
        sidebarTitle: "Чек-лист",
        sidebarHelp: "Выполняйте строго сверху вниз. Отмечайте шаги по мере выполнения.",
        empty: "Администратор ещё не добавил шаги.",
        resetButton: "Сбросить мой прогресс",
        resetConfirm: "Сбросить весь отмеченный прогресс по чек-листу? Шаги останутся, галочки очистятся.",
        loadFailed: "Не удалось загрузить чек-лист.",
        updateFailed: "Не удалось сохранить отметку.",
        resetFailed: "Не удалось сбросить прогресс.",
    },
    workspace: {
        currentUser: "Текущий пользователь: {username} ({role})",
    },
    importPage: {
        pdfCardTitle: "Загрузка PDF",
        pdfCardHelp: "Чертежи трубопроводов в формате PDF. Один или несколько .pdf, либо архив (ZIP, RAR).",
        uploadPdfButton: "Загрузить PDF",
        wordCardTitle: "Загрузка Word",
        wordCardHelp: "ВИК в формате Word. Один или несколько .docx, либо архив (ZIP, RAR).",
        uploadWordButton: "Загрузить Word",
        excelCardTitle: "Загрузка Excel",
        excelCardHelp: "АОСР, контроль сварных соединений, акты испытаний и перечень арматуры в формате Excel. Один или несколько .xlsx, либо архив (ZIP, RAR).",
        uploadExcelButton: "Загрузить Excel",
        fileCheckTitle: "Проверка файла",
        fileCheckHelp: "Загрузите один PDF со схемой — появятся два снимка вырезанных областей (параметры и спецификация) с красной сеткой, проблемными местами считаются те, где есть разрывы красной сетки.",
        fileCheckButton: "Проверить файл",
        fileCheckResultLabel: "Результат проверки",
        fileCheckClose: "Закрыть",
        fileCheckParamsTitle: "Таблица параметров",
        fileCheckSpecTitle: "Таблица спецификации",
    },
    jobPanel: {
        title: "Обработка файлов",
        help: "Статус обновляется автоматически. Дождитесь завершения или сообщения о требуемых действиях.",
        closeButton: "Закрыть",
        statFiles: "Файлов обработано:",
        statPipelines: "Найдено корректных трубопроводов:",
        statSpecs: "Найдено элементов спецификаций:",
        statTime: "Время обработки:",
        statTimeUnit: "сек",
        activityLogTitle: "Ход работы",
        cancelButton: "Отменить обработку",
        saveSpecSectionsButton: "Сохранить выбранные разделы",
    },
    pipelinesPage: {},
    embedments: {
        cardTitle: "Закладные для приборов",
        cardHelp: "По скрину таблицы с чертежа заполните одну или несколько строк (кнопка «Добавить элемент») и сохраните.",
        pipelineLabel: "Трубопровод:",
        loadButton: "Загрузить",
        selectPipeline: "— выберите трубопровод —",
        noGroups: "Нет строк закладных для этого трубопровода.",
        loadError: "Не удалось загрузить закладные.",
        saved: "Сохранено, обновлено строк: {count}.",
        saveError: "Не удалось сохранить.",
        saveButton: "Сохранить",
        saveConfirm: "Сохранить введённые данные по этой закладной? Изменение после сохранения невозможно.",
        nameRequired: "Заполните поле «Наименование» для каждой строки перед сохранением.",
        fieldElementName: "Наименование (по таблице на скрине)",
        fieldLocation: "Место установки",
        fieldDn: "DN",
        fieldPn: "PN",
        fieldMaterial: "Марка материала",
        fieldGost: "ГОСТ / ТУ",
        noImage: "Нет фрагмента чертежа для этой закладной.",
        tagLabel: "Прибор:",
        elementTitle: "Элемент таблицы {n}",
        addElement: "Добавить элемент",
        removeElement: "Удалить",
        maxElements: "Не больше {max} элементов на одну закладную.",
    },
    settingsPage: {
        cardTitle: "Справочники (файлы)",
        cardHelp: "Выберите файл и заполните таблицу.",
        selectPlaceholder: "— выберите файл —",
        reloadButton: "Обновить список",
        formatButton: "Форматировать",
        saveButton: "Сохранить файл",
        fallbackJsonLabel: "Содержимое (JSON)",
        keyColumn: "Ключ / фрагмент",
        valueColumn: "Значение",
        tableColumn: "Таблица паспорта",
        specTablePlaceholder: "— выберите —",
        specLegacyValue: "Как в файле: {value}",
        addRow: "Добавить строку",
        removeRow: "Удалить",
        supportExact: "Точное совпадение",
        supportFamily: "Семейство или общий шаблон",
        unstructuredFallback:
            "Файл в неожиданном формате — открыт текстовый редактор. Приведите к нужной структуре или исправьте вручную.",
        embedmentsTitle: "Закладные",
        embedmentsSearchPlaceholder: "Номер прибора",
        refreshEmbedments: "Обновить",
        noEmbedments: "Нет закладных в базе.",
        embedmentsNoSearchHits: "Нет закладных по этому запросу.",
        embedmentsLoadError: "Не удалось загрузить закладные.",
        listLoadError: "Не удалось загрузить список файлов.",
        fileLoadError: "Не удалось загрузить файл.",
        saveOk: "Сохранено: {title}",
        saveError: "Не удалось сохранить.",
        noFileSelected: "Выберите файл.",
        invalidJson: "Текст не является корректным JSON. Проверьте кавычки, запятые и скобки.",
        formatOk: "JSON отформатирован.",
        formatError: "Не удалось отформатировать: невалидный JSON.",
        formatEmpty: "Нет текста для форматирования.",
    },
    adminPage: {
        cardTitle: "Администрирование",
        cardHelp: "Управление пользователями, общим чек-листом и аудитом изменений.",
        nextStep: "Для нового пользователя необходимо придумать логин, выдать роль и передать ему временный пароль вместе с логином.",
        checklistBlockTitle: "Чек-лист для пользователей",
        checklistBlockHelp: "Здесь задаётся общий список шагов для всех пользователей. Каждый пользователь отмечает выполнение только у себя; сброс прогресса доступен в боковой панели.",
        checklistPlaceholderTitle: "Текст нового шага",
        checklistAddButton: "Добавить шаг",
        checklistTableOrder: "Порядок",
        checklistTableTitle: "Шаг",
        checklistSaveButton: "Сохранить",
        checklistDeleteButton: "Удалить",
        checklistMoveUpButton: "↑",
        checklistMoveDownButton: "↓",
        checklistReordered: "Порядок шагов обновлён.",
        checklistReorderFailed: "Не удалось изменить порядок шагов.",
        checklistDeleteConfirm: "Удалить этот шаг у всех? Прогресс пользователей по нему будет очищен.",
        checklistTitleRequired: "Введите текст шага.",
        checklistCreated: "Шаг добавлен.",
        checklistCreateFailed: "Не удалось добавить шаг.",
        checklistUpdated: "Шаг обновлён.",
        checklistUpdateFailed: "Не удалось обновить шаг.",
        checklistDeleted: "Шаг удалён.",
        checklistDeleteFailed: "Не удалось удалить шаг.",
        usersBlockTitle: "Пользователи",
        placeholderNewUsername: "Новый логин",
        labelActive: "активен",
        createUserButton: "Создать",
        tableHeaderId: "ID",
        tableHeaderUsername: "Логин",
        tableHeaderRole: "Роль",
        tableHeaderActive: "Активен",
        tableHeaderMfa: "MFA",
        tableHeaderActions: "Действия",
        mfaBlockTitle: "MFA администратора",
        mfaGenerateSecret: "Сгенерировать секрет",
        mfaDisable: "Отключить MFA",
        mfaSecretLabel: "Секрет:",
        mfaUriLabel: "URI OTP:",
        placeholderMfaAppCode: "Код из приложения",
        mfaVerifyButton: "Подтвердить MFA",
        auditBlockTitle: "Логи",
        auditRefreshButton: "Обновить логи",
        auditHelp: "Логи разделены на 3 источника: парсинг, ошибки и действия пользователей. Скачивание и очистка работают для выбранного источника.",
        logSourceParsing: "Парсинг",
        logSourceErrors: "Ошибки",
        logSourceActions: "Действия пользователя",
        parsingPipelinePlaceholder: "Поиск (трубопровод/действие/request_id)",
        parsingFileTypeAny: "Тип файла: любой",
        parsingFileTypeUnknown: "Неизвестный",
        parsingResetButton: "Сбросить фильтры",
        parsingDownloadButton: "Скачать логи",
        parsingClearButton: "Стереть все логи",
        parsingPrevButton: "Назад",
        parsingNextButton: "Вперёд",
    },
    roles: {
        admin: "Администратор",
        engineer: "Инженер",
        demo: "Демо",
        adminLower: "администратор",
        engineerLower: "инженер",
        demoLower: "демо",
    },
    auditLog: {
        line: "{timestamp} | user={userId} | {action} | {details}",
        compactLine: "{ts} · {sourceType} · Трубопровод {pipeline} · {field} · {status}",
    },
    auth: {
        initFailed: "Не удалось инициализировать приложение.",
        loginAndPasswordRequired: "Укажите логин и пароль.",
        mfaCodeRequired: "Введите код MFA для завершения входа.",
        mfaStepHint: "Шаг 2: введите код MFA и нажмите «Войти».",
        loginSuccess: "Вход выполнен.",
        forcePasswordChange: "Требуется сменить пароль.",
        loginError: "Ошибка входа.",
        newPasswordRequired: "Введите новый пароль.",
        passwordChanged: "Пароль успешно изменён. Войдите с новым паролем.",
        passwordChangeFailed: "Не удалось сменить пароль.",
        sessionEnded: "Сессия завершена.",
        sessionExpired: "Сессия истекла. Выполните вход снова.",
        authYes: "Статус: вход выполнен",
        authNo: "Статус: вход не выполнен",
        roleUnknown: "роль не определена",
        userUnknown: "пользователь не определён",
    },
    upload: {
        choosePdf: "Выберите PDF-файлы/архив для загрузки.",
        chooseExcel: "Выберите Excel-файлы/архив для загрузки.",
        chooseWord: "Выберите DOCX-файлы/архив для загрузки.",
        sendingFiles: "Файлы отправляются на обработку...",
        filesAccepted: "Файлы приняты. Обработка началась.",
        ocrImportDone: "Распознавание выполнено, результаты сохранены (JSON в каталоге parsed_output).",
        ocrImportDoneWithErrors: "Распознавание завершено; для части файлов есть ошибки ({count}). Проверьте ответ сервера.",
        pdfUploadError: "Ошибка загрузки PDF. Попробуйте обновить страницу и повторить загрузку.",
        excelUploadError: "Ошибка загрузки Excel. Попробуйте обновить страницу и повторить загрузку.",
        wordUploadError: "Ошибка загрузки Word. Попробуйте обновить страницу и повторить загрузку.",
        reasonNetworkError: "Нет соединения с сервером. Проверьте сеть и повторите попытку.",
        reasonTimeoutError: "Сервер не ответил вовремя. Повторите загрузку.",
        reasonUnsupportedExtension: "Неподдерживаемое расширение файла.",
        reasonUnsupportedMime: "Неподдерживаемый тип файла.",
        reasonFileTooLarge: "Файл слишком большой.",
        reasonFileTooLargeWithLimit: "Файл превышает лимит {limit} МБ.",
        reasonArchiveCorrupted: "Архив повреждён или не содержит подходящих файлов.",
        reasonArchiveServerTool: "Сервер не может распаковать RAR на текущей конфигурации.",
        reasonUnknownImportKind: "Выбран неподдерживаемый тип импорта.",
        reasonEmptyFile: "Файл пустой.",
        reasonServerError: "Внутренняя ошибка сервера. Повторите попытку позже.",
        blockedByProcessing: "Идёт обработка. Новые загрузки временно недоступны.",
    },
    fileCheck: {
        chooseSinglePdf: "Выберите один PDF-файл для проверки.",
        onlyOneFile: "Для проверки нужно выбрать ровно один PDF-файл.",
        sending: "Файл отправляется на проверку...",
        completed: "Снимки получены. Страница PDF: {page}.",
        failed: "Не удалось проверить файл. Попробуйте снова.",
        noImage: "Снимок не сформирован.",
    },
    job: {
        processingPending: "Задача в очереди на запуск...",
        processingLive: "Идёт обработка...",
        processingCompletedPdf: "Обработка PDF успешно завершена.",
        processingCompletedOcr: "Распознавание (OCR) успешно завершено.",
        processingCompletedExcel: "Обработка Excel успешно завершена.",
        processingCompletedWord: "Обработка Word успешно завершена.",
        processingError: "Ошибка обработки. Проверьте проблемные файлы.",
        processingErrorFinal: "Обработка завершилась с ошибкой. Попробуйте обновить страницу и повторить загрузку.",
        processingCancelled: "Обработка отменена пользователем.",
        waitingUserInput: "Ожидание выбора таблицы паспорта пользователем.",
        waitingUserInputCount: "Ожидание выбора таблицы паспорта пользователем: {count} элементов.",
        waitingEmbedmentInput: "Ожидание заполнения закладных по фрагменту чертежа.",
        waitingEmbedmentInputCount: "Ожидание заполнения закладных: {count} групп.",
        embedmentPendingHelp: "По каждой строке заполните поля по таблице на скриншоте и нажмите «Сохранить». Импорт продолжится автоматически.",
        embedmentPendingPipeline: "Трубопровод: {name}",
        activityWaitingEmbedment: "Ожидание заполнения закладных пользователем.",
        invalidFilesSummary: "Проблемных файлов: {filesCount}. Проблемных записей: {rowsCount}.",
        invalidFilesCountOnly: "Некорректных файлов: {count}.",
        showInvalidFiles: "Развернуть список файлов",
        hideInvalidFiles: "Свернуть список файлов",
        filePrefix: "файл {name}",
        fileWithReasonsPrefix: "файл {name}: {reasons}",
        invalidReasonFallback: "неизвестная ошибка",
        invalidReasonFileImport: "не удалось обработать PDF-файл",
        invalidReasonPipelineSave: "ошибка сохранения данных трубопровода",
        invalidReasonNoDataExtracted: "не удалось извлечь данные из PDF",
        invalidReasonNoSpecifications: "нет элементов спецификации в файле",
        invalidReasonNoPipesOnSpecPage: "на странице спецификации отсутствуют трубы",
        invalidReasonSectionUndefined: "не определён раздел спецификации",
        invalidReasonSpecTableRow: "проблема в таблице спецификации",
        invalidReasonSpecTableSection: "проблема в разделе спецификации",
        invalidReasonSpecTableMissing: "не найдена таблица спецификации",
        invalidReasonParamsTableMissing: "не найдена таблица параметров",
        invalidReasonPdfCorrupted: "PDF-файл повреждён или имеет некорректную структуру",
        invalidReasonPdfProtected: "PDF-файл защищён паролем или ограничениями",
        invalidReasonPdfUnreadableScan: "не удалось распознать данные со скана PDF",
        invalidReasonPdfFormatUnsupported: "неподдерживаемый формат содержимого PDF",
        invalidReasonDataValidation: "ошибка проверки данных в таблице",
        invalidReasonCrossFileDuplicate: "одна и та же линия в PDF на разных схемах",
        invalidReasonCrossFilePrefixMismatch: "разные линии в PDF на одной схеме",
        invalidTableSpecification: "таблица спецификации",
        invalidTableParameters: "таблица параметров",
        invalidContextTableRow: "{table}, строка {row}",
        invalidContextTableElement: "{table}, элемент «{name}»",
        invalidContextTableOnly: "{table}",
        invalidContextRowOnly: "строка {row}",
        invalidContextElementOnly: "элемент «{name}»",
        andMoreFiles: "... и ещё {count} файлов",
        undefinedSpecShort: "Выберите таблицу паспорта (4.1–4.4) для элемента или отметьте, что это не элемент спецификации.",
        undefinedSpecLong:
            "Выберите таблицу паспорта (4.1–4.4) для элемента или отметьте, что это не элемент спецификации. "
            + "При необходимости откройте полное имя или поправьте ключ сопоставления.",
        undefinedSpecFile: "{name} (файл: {file})",
        undefinedSpecFullName: "Полное имя: {name}",
        mappingPlaceholder: "Ключ сопоставления (можно сократить)",
        chooseTable: "Выберите таблицу",
        chooseSectionInTable: "Уточните раздел",
        chooseSection: "Выберите раздел",
        showUnknownFullName: "Неизвестно",
        markAsNotSpec: "Не элемент спецификации",
        markAsNotSpecSaved: "Элемент помечен как «не элемент спецификации» и больше не будет запрашиваться.",
        markAsNotSpecFailed: "Не удалось сохранить пометку «не элемент спецификации». Попробуйте снова.",
        chooseAtLeastOneSection: "Выберите хотя бы один раздел.",
        chooseAtLeastOneTableSection: "Выберите таблицу для хотя бы одного элемента.",
        specSectionsSaveConfirm:
            "Будет сохранено сопоставление элемента с таблицей паспорта.\n\n" +
            "Продолжить?",
        specSectionsSaveConfirmOk: "Сохранить",
        mappingSaved: "Сопоставления сохранены: {count}. Импорт продолжится автоматически.",
        mappingSaveFailed: "Не удалось сохранить сопоставления. Попробуйте обновить страницу и повторить сохранение.",
        activityStart: "Запущено отслеживание обработки.",
        activityPending: "Задача ожидает запуск. При необходимости её можно отменить.",
        activityProcessing: "Идёт обработка файлов.",
        activityProcessingFile: "Файл: {file} ({current}/{total}).",
        activityProgress: "Прогресс: {percent}%.",
        activityDone: "Обработка успешно завершена.",
        activityDoneSummary: "Готово: файлов {processed}/{total}, трубопроводов {pipelines}, элементов {specItems}.",
        activityError: "Обработка завершилась с ошибкой. Попробуйте обновить страницу и повторить загрузку.",
        activityCancelled: "Обработка отменена пользователем.",
        activityInvalidFilesCount: "Обнаружено некорректных файлов: {count}.",
        activityWaitingInput: "Ожидание выбора таблиц паспорта пользователем.",
        cancelConfirm: "Вы уверены, что хотите отменить обработку?",
        cancelRequested: "Запрошена отмена обработки. Ожидайте остановки задачи.",
        cancelFailed: "Не удалось отменить обработку.",
        filesProgress: "{processed} / {total}",
        ocrPagesSuffix: "стр. {cur}/{total}",
        ocrPairsSuffix: "пар {cur}/{total}",
    },
    pipelines: {
        empty: "Паспорта пока не сформированы. Сначала загрузите PDF-файлы.",
        searchingPlaceholder: "Поиск по названию паспорта",
        download: "Скачать",
        selectAll: "Выбрать все",
        clearSelection: "Снять выбор",
        downloadSelectedZip: "Скачать выбранные ZIP",
        selectedCount: "Выбрано: {count}",
        downloadingSingle: "Скачивание паспорта: {name}...",
        downloadedSingle: "Паспорт {name} успешно скачан.",
        downloadSingleError: "Не удалось скачать паспорт. Попробуйте обновить страницу и повторить скачивание.",
        noMatches: "По вашему запросу ничего не найдено.",
        chooseAtLeastOne: "Выберите хотя бы один паспорт.",
        downloadingZip: "Формируется ZIP-архив выбранных паспортов...",
        downloadedZip: "ZIP-архив с выбранными паспортами успешно скачан.",
        downloadZipError: "Не удалось скачать ZIP-архив паспортов. Попробуйте обновить страницу и повторить скачивание.",
        demoLimitReached: "Достигнут лимит скачиваний для демо-доступа ({limit} за {periodDays} дн.).",
        zipFallbackFilename: "паспорта_трубопроводов.zip",
    },
    admin: {
        initFailed: "Не удалось инициализировать админ-панель. Попробуйте обновить страницу и повторить вход.",
        roleSaveHint: "Изменение роли для {username} не сохранено. Нажмите «Сохранить роль».",
        roleSaveButton: "Сохранить роль",
        deleteButton: "Удалить",
        deactivateUser: "Отключить",
        enableUser: "Включить",
        userActiveChanged: "Пользователь {username} {state}.",
        activeStateEnabled: "включён",
        activeStateDisabled: "отключён",
        activeChangeFailed: "Не удалось изменить статус пользователя. Попробуйте обновить страницу и повторить действие.",
        deleteConfirm: "Удалить пользователя {username}?",
        roleNotChanged: "Роль пользователя {username} не изменилась.",
        roleChanged: "Роль пользователя {username} обновлена.",
        roleChangeFailed: "Не удалось обновить роль. Попробуйте обновить страницу и повторить изменение.",
        userDeleted: "Пользователь {username} удалён.",
        userDeleteFailed: "Не удалось удалить пользователя. Попробуйте обновить страницу и повторить удаление.",
        usernameRequired: "Введите логин пользователя.",
        userCreatedWithPassword: "Создан пользователь {username}. Временный пароль: {password}",
        userCreateFailed: "Не удалось создать пользователя. Попробуйте обновить страницу и повторить создание.",
        mfaSecretGenerated: "Секрет MFA сгенерирован. Подтвердите кодом.",
        mfaSetupFailed: "Не удалось сгенерировать MFA.",
        mfaCodeRequired: "Введите код MFA.",
        mfaEnabled: "MFA успешно включена.",
        mfaVerifyFailed: "Не удалось подтвердить MFA.",
        mfaDisabled: "MFA отключена.",
        mfaDisableFailed: "Не удалось отключить MFA.",
        auditLoadFailed: "Не удалось загрузить аудит-лог.",
        parsingDownloadOk: "Логи успешно скачаны.",
        parsingDownloadFailed: "Не удалось скачать логи.",
        parsingClearConfirm: "Удалить все parsing-логи для пользователя {login}?",
        logsClearConfirmBySource: "Удалить логи выбранного источника «{source}» для выбранного пользователя?",
        logsClearPasswordPrompt: "Введите пароль доступа для удаления логов:",
        logsClearPasswordRequired: "Пароль доступа обязателен для удаления логов.",
        logsClearOkBySource: "Логи источника «{source}» удалены.",
        parsingClearOk: "Логи пользователя {login} удалены.",
        parsingClearFailed: "Не удалось удалить логи.",
        parsingLoginRequired: "Не удалось определить логин пользователя для фильтра логов.",
        parsingPageInfo: "Показано: {from}–{to}",
        parsingPageInfoEmpty: "Ничего не найдено",
        yes: "да",
        no: "нет",
        enabled: "включено",
        disabled: "выключено",
        notAvailable: "нет данных",
    },
    common: {
        yes: "Да",
        no: "Нет",
        confirm: "Подтвердить",
        cancel: "Отмена",
        problematicFile: "Проблемный файл: {name}",
        problematicFiles: "Проблемные файлы: {names}",
        requestId: "request_id: {requestId}",
        unknownError: "Произошла ошибка. Попробуйте обновить страницу и повторить действие.",
        emDash: "–",
        percent: "{value}%",
        ellipsis: "…",
    },
    api: {
        noPdfFilesSelected: "Не выбраны PDF-файлы.",
        noExcelFilesSelected: "Не выбраны Excel-файлы.",
        noWordFilesSelected: "Не выбраны Word-файлы.",
    },
    backendErrors: {
        invalidCredentials: "Неверный логин или пароль.",
        userInactive: "Пользователь отключён. Обратитесь к администратору.",
        refreshTokenRequired: "Требуется токен обновления сессии.",
        invalidUser: "Недопустимый пользователь.",
        passwordChangeTokenUsed: "Токен смены пароля уже использован.",
        authenticationRequired: "Требуется авторизация.",
        currentPasswordInvalid: "Текущий пароль указан неверно.",
        userNotFound: "Пользователь не найден.",
        usernameExists: "Пользователь с таким логином уже существует.",
        adminCannotDeleteOwn: "Администратор не может удалить свою учётную запись.",
        filesOrArchiveOnlyOne: "Передайте либо файлы, либо архив, но не одновременно.",
        invalidTokenSignature: "Неверная подпись токена.",
        invalidToken: "Недействительный токен.",
        invalidTokenType: "Неверный тип токена.",
        tokenExpired: "Срок действия токена истёк.",
        insufficientPermissions: "Недостаточно прав для выполнения действия.",
        requestValidationFailed: "Ошибка валидации запроса.",
        internalServerError: "Внутренняя ошибка сервера.",
        checklistItemNotFound: "Шаг чек-листа не найден.",
        titleRequired: "Укажите текст шага.",
        fileValidationFailed: "Файл не прошёл проверку.",
        unknownPdfImportKind: "Неизвестный тип PDF-импорта.",
        unknownWordImportKind: "Неизвестный тип импорта Word.",
        userIdentifierRequired: "Укажите пользователя для просмотра логов.",
        uploadedFileEmpty: "Файл пустой.",
        logsClearPasswordNotConfigured: "Пароль очистки логов не настроен на сервере.",
        logsClearPasswordRequired: "Для очистки логов нужен пароль доступа.",
        logsClearPasswordInvalid: "Неверный пароль доступа к очистке логов.",
        timeoutError: "Сервер не ответил вовремя.",
        networkError: "Нет соединения с сервером.",
    },
};

const BACKEND_ERROR_KEY_MAP = new Map([
    ["Invalid credentials", "invalidCredentials"],
    ["User is inactive", "userInactive"],
    ["Refresh token is required", "refreshTokenRequired"],
    ["Invalid user", "invalidUser"],
    ["Password change token is already used", "passwordChangeTokenUsed"],
    ["Authentication required", "authenticationRequired"],
    ["Current password is invalid", "currentPasswordInvalid"],
    ["User not found", "userNotFound"],
    ["Username already exists", "usernameExists"],
    ["Admin cannot delete own account", "adminCannotDeleteOwn"],
    ["Provide either files or archive, not both", "filesOrArchiveOnlyOne"],
    ["Invalid token signature", "invalidTokenSignature"],
    ["Invalid token", "invalidToken"],
    ["Invalid token type", "invalidTokenType"],
    ["Token expired", "tokenExpired"],
    ["Insufficient permissions", "insufficientPermissions"],
    ["Request validation failed", "requestValidationFailed"],
    ["Internal server error", "internalServerError"],
    ["Checklist item not found", "checklistItemNotFound"],
    ["Title is required", "titleRequired"],
    ["File validation failed", "fileValidationFailed"],
    ["Неизвестный тип PDF-импорта", "unknownPdfImportKind"],
    ["Неизвестный тип импорта Word", "unknownWordImportKind"],
    ["User identifier is required", "userIdentifierRequired"],
    ["Uploaded file is empty", "uploadedFileEmpty"],
    ["Logs clear password is not configured", "logsClearPasswordNotConfigured"],
    ["Access password is required", "logsClearPasswordRequired"],
    ["Access password is invalid", "logsClearPasswordInvalid"],
]);

export function t(key, params = {}) {
    const parts = key.split(".");
    let current = UI_MESSAGES;
    for (const part of parts) {
        current = current?.[part];
    }
    if (typeof current !== "string") {
        return key;
    }
    return current.replace(/\{(\w+)}/g, (_, name) => {
        const value = params[name];
        return value === undefined || value === null ? `{${name}}` : String(value);
    });
}

export function pageMeta(pageName) {
    return UI_MESSAGES.pageMeta[pageName] || UI_MESSAGES.pageMeta.import;
}

export function translateBackendMessage(message) {
    const raw = typeof message === "string" ? message.trim() : "";
    if (!raw) return message;
    const key = BACKEND_ERROR_KEY_MAP.get(raw);
    return key ? t(`backendErrors.${key}`) : message;
}

/**
 * Подставляет строки в разметку: data-i18n, data-i18n-placeholder, data-i18n-title.
 * Вызвать один раз при загрузке (до логики страниц).
 */
function applyPageHeaderI18n(pageName) {
    const meta = pageMeta(pageName);
    const titleEl = document.getElementById("pageTitle");
    const subEl = document.getElementById("pageSubtitle");
    const nextEl = document.getElementById("pageNextStep");
    if (!meta || !titleEl) return;
    titleEl.textContent = meta.title;
    if (subEl) subEl.textContent = meta.subtitle;
    if (nextEl) nextEl.textContent = meta.nextStep;
}

function applyJobPanelInitialI18n() {
    const progressText = document.getElementById("progressText");
    if (progressText) {
        progressText.textContent = t("common.percent", { value: 0 });
    }
    const liveText = document.getElementById("jobLiveText");
    if (liveText) {
        liveText.textContent = t("common.ellipsis");
    }
    const dash = t("common.emDash");
    for (const id of ["statPages", "statPipelines", "statSpecs", "statTime"]) {
        const el = document.getElementById(id);
        if (el) el.textContent = dash;
    }
}

function applyPipelinesToolbarI18n() {
    const search = document.getElementById("pipelinesSearchInput");
    if (search) {
        search.placeholder = t("pipelines.searchingPlaceholder");
    }
    const selectAllBtn = document.getElementById("pipelinesSelectAllBtn");
    if (selectAllBtn) {
        selectAllBtn.textContent = t("pipelines.selectAll");
    }
    const clearBtn = document.getElementById("pipelinesClearSelectionBtn");
    if (clearBtn) {
        clearBtn.textContent = t("pipelines.clearSelection");
    }
    const downloadZipBtn = document.getElementById("pipelinesDownloadSelectedBtn");
    if (downloadZipBtn) {
        downloadZipBtn.textContent = t("pipelines.downloadSelectedZip");
    }
    const counter = document.getElementById("pipelinesSelectedCount");
    if (counter) {
        counter.textContent = t("pipelines.selectedCount", { count: 0 });
    }
    const empty = document.getElementById("pipelinesEmpty");
    if (empty) {
        empty.textContent = t("pipelines.empty");
    }
}

export function bindDomI18n(root = document) {
    if (typeof document !== "undefined") {
        document.title = t("meta.documentTitle");
    }
    root.querySelectorAll("[data-i18n]").forEach((el) => {
        const key = el.getAttribute("data-i18n");
        if (key) {
            el.textContent = t(key);
        }
    });
    root.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
        const key = el.getAttribute("data-i18n-placeholder");
        if (key && "placeholder" in el) {
            el.placeholder = t(key);
        }
    });
    root.querySelectorAll("[data-i18n-title]").forEach((el) => {
        const key = el.getAttribute("data-i18n-title");
        if (key) {
            el.title = t(key);
        }
    });
    applyPageHeaderI18n("import");
    applyJobPanelInitialI18n();
    applyPipelinesToolbarI18n();
}
