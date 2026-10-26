# DocPipeAI — краткий обзор для портфолио

Полная эксплуатационная инструкция заказчика **не включена** (NDA).

## Роли

- `admin` — пользователи, журналы, JSON-конфиги
- `engineer` — импорт файлов и выгрузка паспортов
- `demo` — ограниченное число скачиваний

## Типовой поток

1. Импорт PDF-чертежей (новые линии появляются из чертежей).
2. Импорт Excel/Word спецификаций и связанных таблиц.
3. При неизвестных позициях спецификации — разметка секций (`spec_item_sections`).
4. Генерация паспорта `.docx` по шаблону.

## Где смотреть код

- Импорт / jobs: `backend/app/application/`
- Парсинг: `backend/app/domain/`
- Экспорт Word: `backend/app/infrastructure/exporters/`
- UI: `frontend/js/`

Подробнее по переменным окружения: [CONFIGURATION_REFERENCE_RU.md](CONFIGURATION_REFERENCE_RU.md).  
Развёртывание (с плейсхолдерами): [DEPLOYMENT_RU.md](DEPLOYMENT_RU.md).
