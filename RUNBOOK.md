# One-click benchmark foundation

Распакуйте полный архив и откройте START.cmd. Нужны Python 3.11+ и Git.
Устанавливаются только закреплённые тестовые библиотеки в .bench, не глобально.
В готовом архиве есть wheels: первый тестовый запуск не требует GitHub/API/модели.
Node, Docker, DeepSeek и ключ модели для самопроверки не нужны.

`START.cmd test --offline` — команда для Codex без меню и паузы.
Она запускает существующий suite, новые тесты и реальный локальный контроль:
рабочий bundled-проект -> поломка provider -> обнаруженный FAIL -> восстановление.
Это проверяет бенчмарк, а не качество программирования модели.

Результат: .bench/latest.json -> короткий summary.json. Полные логи отдельно,
не печатаются в контекст и игнорируются обычным поиском. Старые прогоны не затираются.

## Уже закреплённые проекты

HTTPX, Requests, Pluggy остаются исходными ProjectSpec из этого репозитория.
`START.cmd projects --offline` использует seed bundles в .bench/seeds.
`START.cmd projects --allow-network` получает отсутствующие source pins и создаёт seeds.
`--source-dir C:\\data\\sources` принимает <project_id>.bundle или <project_id>/.git.
Источник проверяется по commit, полному source digest и license digest, не по имени папки.
Данные не интерпретируются как квалифицированные coding-задачи.

`START.cmd projects --allow-network --allow-local-build` выполняет существующий
ProjectEnvironmentBuilder и объявленные baseline-команды в disposable worktree.
Включайте только на машине, где допустимо запускать чужой код: это НЕ OS sandbox.
Ключи, домашние настройки Git и пользовательские Python plugins в дочернюю среду не передаются.
Сеть сборки этим режимом не ограничивается allowlist на уровне ОС; статус диагностический.
Предел project_seconds охватывает весь worker; build/baseline уменьшают объявленные таймауты.

## Кампания и intake

Измените BENCHMARK.toml и запустите `START.cmd plan`.
Квоты large не заполняются medium-проектами. При нехватке виден quota_deficits.
Масштаб берётся из существующей классификации, не выдаётся за измеренный LOC.
План содержит одинаковые выбранные проекты для двух arms, repeat count и budget envelope.
planned_usd_per_episode — расчётный параметр, НЕ действующий платёжный ограничитель.
execution_ready=false до реального подключения квалифицированных задач и обоих arms.

`START.cmd discover --allow-network` с GITHUB_TOKEN только для чтения собирает публичные
issue/merged-PR пары. Лимиты API/размера ответа, строгая история и карантин сохраняются.
Raw issues остаются в evaluator-side CAS; summary содержит ссылки, не длинные тексты.
Автосборка произвольного найденного проекта, закрытые тесты и живое DSH/ADCP A/B
не добавлены и не заменены заглушками.

## Обслуживание

Коды выхода: 0 — команда закончилась; 2 — BLOCKED/FAILED/INCOMPLETE; 130 — отмена.
Всегда проверяйте поле status: успешное построение PLAN_ONLY не равно benchmark PASS.
Не удаляйте .bench во время выполнения. Удаление .bench сбрасывает только локальные
окружения, кеши и отчёты; исходные проекты и production ADCP не меняются.
Переезд архива создаёт новое привязанное окружение, не использует старый venv вслепую.
