# Qodo Code Review Log

Qodo Code Review установлен на `GoatWhistle/harness-hack` до появления первой строки продуктового кода.

Каждый milestone проходит через отдельный pull request. Для каждого PR здесь фиксируются:

| PR | Milestone | Находки Qodo | Исправлено | Отклонено с обоснованием |
|---|---|---|---|---|
| [#1](https://github.com/GoatWhistle/harness-hack/pull/1) | M1 — mandate guard | Research и execution guard находились в одном привилегированном пакете | Принято: news, signals и backtest вынесены в отдельный пакет `mandate-research` | Нет |
| [#1](https://github.com/GoatWhistle/harness-hack/pull/1) | M1 — deep review | 9 bugs, включая 3 High: pending exposure, конкурентные submit, обход мандата через close | Исправлены все 9; добавлены broker-clock, NY cutoff, пагинация, reservation model, lock и регрессионные тесты | Нет |
| [#2](https://github.com/GoatWhistle/harness-hack/pull/2) | M2 — TrueForge integration, deep review | 7 bugs: финальность отказа, crash provenance, конфликт intent ID, opt-in close, point-in-time revisions, нормализация символов, configurable guard URL | Все 7 исправлены с регрессионными тестами; повторный Qodo review: **Bugs 0, Rule violations 0** | Нет |
| [#2](https://github.com/GoatWhistle/harness-hack/pull/2) | M3 — multi-source research MCP + live agent eval | Qodo на commit `26b5da8`: **Bugs 0, Rule violations 0, Skill insights 0** | Внутренний аудит до review исправил неверную привязку NVIDIA RSS к AAPL; добавлены fixed issuer mappings и регрессионный тест | Нет |
| [#2](https://github.com/GoatWhistle/harness-hack/pull/2) | M4 — open-market paper E2E + cleanup | Qodo на commit `49378d4`: **Bugs 0, Rule violations 0, Skill insights 0** | Два approval, broker readback, idempotent retry и provenance-safe cancel зафиксированы в sanitized evidence artifact | Нет |
| [#2](https://github.com/GoatWhistle/harness-hack/pull/2) | M4 — operator dashboard | Qodo на commit `bdb602a`: **Bugs 0, Rule violations 0, Skill insights 0** | Read-only live MCP surface, degraded journal fallback, secret-free browser payload и responsive UI проверены тестами и в браузере | Нет |
| [#2](https://github.com/GoatWhistle/harness-hack/pull/2) | M5 — unified TrueForge operator UI | Qodo на commit `dcdbc31`: **Bugs 0, Rule violations 0, Skill insights 0** | Overview встроен рядом со stock Agent workspace; история, tool calls, composer, approval UI, mobile layout и оригинальная TrueForge palette проверены в живом браузере | Нет |
| [#2](https://github.com/GoatWhistle/harness-hack/pull/2) | M6 — 24/7 autonomy + news control plane | Qodo на commit `215be7b`: **Bugs 0, Rule violations 0, Skill insights 0** | Durable news cursor с retry-очередью, read-only background cycles, chat trajectory approval, restart-safe runtime и автономный UI проверены unit-, live-agent- и browser-E2E тестами | Нет |
| [#2](https://github.com/GoatWhistle/harness-hack/pull/2) | M7 — clean-state reset + compact header | Qodo на commit `8b5ed84`: **Bugs 0, Rule violations 0, Skill insights 0** | Все 32 старые TrueForge-сессии и локальный runtime/audit state очищены; новый цикл стартовал с нуля, компактный header проверен в живом браузере | Нет |
| [#2](https://github.com/GoatWhistle/harness-hack/pull/2) | M8 — realtime Alpaca monitoring control plane | Qodo на commit `30aff5d`: **Bugs 0, Rule violations 0, Skill insights 0** | WebSocket + REST fallback, market quality/SPY gates, observation-only discovery, corporate actions, forward outcomes и approval-gated UI проверены unit-, live-agent- и browser-E2E тестами | Нет |
| [#2](https://github.com/GoatWhistle/harness-hack/pull/2) | M9 — IDE-style monitoring settings drawer | Qodo на commit `a68cbf0`: **Bugs 0, Rule violations 0, Skill insights 0** | Настройки вынесены из runner card в правый header drawer; Overview, Agent workspace, close behavior и responsive layout проверены сборкой и в живом браузере | Нет |
| [#2](https://github.com/GoatWhistle/harness-hack/pull/2) | M10 — deterministic decision intelligence | Qodo на commit `c2c4a0c`: **Bugs 0, Rule violations 0, Skill insights 0** | Аудит 25 сессий превратил повторяемую sandbox-математику в `evaluate_trajectory` Skill/tool; добавлены ATR sizing, SPY regime ensemble, slippage/holdout и 60m outcome feedback loop. Live E2E вызвал только два read-only tool и не использовал `exec` | Нет |

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
- Для лимитов ёмкости (позиция, gross exposure, число ордеров) граница ровно на лимите разрешена;
  превышение на минимальную денежную единицу запрещено. Дневной loss limit — hard stop и срабатывает
  при достижении границы.
- Ошибка или неполные рыночные данные приводят к отказу, а не к пропуску проверки.
- Торговое поведение должно иметь детерминированные тесты и объяснимую причину решения.
