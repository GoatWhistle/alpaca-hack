# MANDATE hackathon demo — storyboard and voiceover

Approximate source duration: 4:20. Recommended final cut: 2:45–3:10.

The story should be about an inspectable agent organization, not a dashboard tour. Keep the dependency graph and trader-room reasoning as the climax. Do not claim profitability; the clip visibly shows paper trading, rejected candidates, parked plans, and a real trade ledger.

## Recommended cut

| Time | Source | What to show | Voiceover (English) |
|---|---:|---|---|
| 0:00–0:18 | 0:00–0:20 | Desk overview: account equity, exposure, news, recent fills, runner state. | “Most AI trading demos end with a signal. MANDATE starts with the harder question: can we inspect every decision that reaches the market? This is a stateful trading desk for Alpaca paper markets.” |
| 0:18–0:43 | 0:50–1:05 | Trade ledger. Keep the table and one or two exit reasons visible. | “Every fill becomes an auditable record. We pair entries and exits, show holding time and P&L, and preserve the reason a position was closed — or why a candidate was rejected. Paper results are visible, including losses; nothing is hidden behind a headline metric.” |
| 0:43–1:04 | 1:10–1:32 | Signal cards and market/news feed. | “Research workers collect market data, attributable news, corporate actions, movers, and IPO events. Quantitative signals are scored against liquidity, freshness, and news–price alignment. A signal is evidence — it is not yet an order.” |
| 1:04–1:12 | 1:40–1:48 | Brief source article view. Cut quickly; avoid reading the whole page. | “The system keeps a source trail. The main trader receives bounded evidence with provenance instead of an ungrounded news summary.” |
| 1:12–1:39 | 1:50–2:20 | Dependency map, including feedback lines and position watcher. | “This is the architecture: feeds enter the news gate and research hub; hypotheses flow to the main trader; market, risk, and execution critics challenge the plan; deterministic policy controls the broker boundary. Open positions flow back through a watcher, so the next decision sees what happened after entry.” |
| 1:39–1:54 | 2:40–2:55 | Services, data feeds, quality gate, strategy scorecard. | “The operations view makes health and degradation explicit: services, feed quality, candidate counts, and strategy diagnostics. If a source is stale or a critic is unavailable, the system records that state instead of pretending it was a successful approval.” |
| 1:54–2:48 | 2:50–4:10 | Main trader room. Show active hypotheses, critic synthesis, parked plan, and the side chat/fork. | “The trader room is a conversation, not a black-box score. The main agent explains the hypothesis it is testing, cites the evidence, receives summarized worker results, and records what changed its mind. Here, the plan is parked because the execution evidence is not fresh enough. That is a successful safety outcome: uncertainty becomes HOLD, not an invented trade.” |
| 2:48–3:05 | 4:10–4:20 | Final trader-room frame or dependency graph. | “MANDATE is an observable organization of agents: probabilistic reasoning in the front, deterministic execution at the back, and a complete audit trail between them. The goal is not to make an AI sound confident. The goal is to make its decisions inspectable.” |

## Sections to remove or accelerate

- Source 0:20–0:42: loading/blank table states.
- Repeated ledger scrolling after the first useful rows.
- Long static external-news browsing; keep only the article/source context.
- Repeated dependency-map hovering; keep one clean graph view and one tooltip if needed.
- Repeated trader-room frames where no new hypothesis, critic result, or user interaction appears.

## Suggested on-screen labels

Use short labels, not paragraphs:

- `Evidence in`
- `Hypothesis under test`
- `Critics challenge`
- `Deterministic policy`
- `PARK / HOLD when uncertain`
- `Broker write boundary`
- `Position feedback`

## Opening title card

```text
MANDATE
An inspectable multi-agent trading desk
Evidence → hypotheses → challenge → deterministic execution
```

## Closing card

```text
MANDATE
Stateful agents. Explicit dependencies. Auditable paper execution.
alpaca.miposts.com
github.com/GoatWhistle/alpaca-hack
```

## Delivery notes

- Record the voiceover in English for the hackathon; keep it calm and engineering-focused.
- Speak at roughly 125–140 words per minute. The recommended script is about 380 words.
- Do not narrate the displayed negative P&L as a success. Frame it as auditability and honest failure handling.
- Avoid saying “the model decides and trades.” Say “the model proposes; deterministic policy and the executor decide whether anything can reach Alpaca.”
- If the final video must stay near 4:20, hold on the dependency graph and trader room rather than the loading screens.
