# Qodo Code Review Log

Qodo Code Review установлен на `GoatWhistle/harness-hack` до появления первой строки продуктового кода.

Каждый milestone проходит через отдельный pull request. Для каждого PR здесь фиксируются:

| PR | Milestone | Находки Qodo | Исправлено | Отклонено с обоснованием |
|---|---|---|---|---|
| [#1](https://github.com/GoatWhistle/harness-hack/pull/1) | M1 — mandate guard | Research и execution guard находились в одном привилегированном пакете | Принято: news, signals и backtest вынесены в отдельный пакет `mandate-research` | Нет |
| [#1](https://github.com/GoatWhistle/harness-hack/pull/1) | M1 — deep review | 9 bugs, включая 3 High: pending exposure, конкурентные submit, обход мандата через close | Исправлены все 9; добавлены broker-clock, NY cutoff, пагинация, reservation model, lock и регрессионные тесты | Нет |
| [#2](https://github.com/GoatWhistle/harness-hack/pull/2) | M2 — TrueForge integration, deep review | 7 bugs: финальность отказа, crash provenance, конфликт intent ID, opt-in close, point-in-time revisions, нормализация символов, configurable guard URL | Все 7 исправлены с регрессионными тестами; повторный review запрошен | Нет |

Подробности исправлений deep review PR #1:

1. Открытые лимитные ордера резервируют worst-case позицию и gross exposure; встречные заявки не взаимозачитываются.
2. Проверка и submit сериализованы одним lock внутри единственного процесса guard.
3. `close_position` первоначально проходил полный `OrderIntent`; в M2 заменён на отдельную явно opt-in
   политику risk-reducing market close, которая всё равно проверяет позицию, session и expiry.
4. Торговая сессия подтверждается broker clock Alpaca; отсутствие clock закрывает путь fail-closed.
5. История ордеров пагинируется за пределы лимита Alpaca в 500 элементов.
6. News signal отбрасывает события, опубликованные позже текущего бара.
7. Нулевые и отрицательные thresholds отвергаются до расчёта.
8. Торговый день начинается в полночь `America/New_York`, а не UTC.
9. Схема разрешает только реализованные контракты `limit` и `market`; неполные stop-типы отклоняются.

Подробности исправлений deep review PR #2:

1. Отказанный `intent_id` становится терминальным и не может исполниться после изменения рынка.
2. До broker submit пишется durable `prepared`; найденный после сбоя broker order переводится в
   `submitted_reconciled` и сохраняет право безопасной отмены.
3. `intent_id` навсегда связывается с canonical fingerprint символа, стороны, количества, типа и цены.
4. Risk-reducing market close по умолчанию запрещён и требует явного поля в YAML.
5. News revisions дедуплицируются внутри каждого point-in-time окна, а не до временного cutoff.
6. Payload symbols очищаются от пробелов, приводятся к uppercase, пустые значения отбрасываются.
7. Внешний адрес guard задаётся отдельным валидируемым `MANDATE_GUARD_URL`.

Правила проекта для ревью:

- Любая возможность обратиться к live trading endpoint — блокирующая находка.
- Секреты, ключи, значения `.env` и персональные данные запрещены.
- Денежные величины и лимиты считаются через `Decimal`, не `float`.
- `submit` обязан повторять проверку на свежем состоянии; результат предыдущего dry-run не считается разрешением.
- Граница ровно на лимите разрешена, превышение на минимальную денежную единицу запрещено.
- Ошибка или неполные рыночные данные приводят к отказу, а не к пропуску проверки.
- Торговое поведение должно иметь детерминированные тесты и объяснимую причину решения.
