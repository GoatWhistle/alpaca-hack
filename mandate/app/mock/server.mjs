import { createServer } from "node:http";

const PORT = Number(process.env.MANDATE_MOCK_PORT ?? 8030);
const HOST = process.env.MANDATE_MOCK_HOST ?? "127.0.0.1";

const UNIVERSE = [
  "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "AMD", "AVGO", "ORCL",
  "IBM", "PLTR", "CRM", "ANET", "TSM", "ASML", "ARM", "BABA", "BIDU", "SPY",
];

const state = {
  approvalsResolved: new Set(),
  trajectoryVersion: 7,
  analysisIntervalMinutes: 3,
  degraded: process.env.MANDATE_MOCK_DEGRADED === "true",
  decided: [],
};

function minutesAgo(minutes) {
  return new Date(Date.now() - minutes * 60_000).toISOString();
}

function yesterdayAt(hour, minute) {
  const value = new Date();
  value.setDate(value.getDate() - 1);
  value.setHours(hour, minute, 0, 0);
  return value.toISOString();
}

function mandateState() {
  return {
    mandate: {
      name: "ai-platforms-infrastructure-2026-08-28",
      universe: UNIVERSE,
      instruments: ["equity", "option"],
      order_types: ["limit"],
      session: "regular_hours_only",
      limits: {
        max_position_pct: "40",
        max_gross_exposure_pct: "200",
        max_daily_loss_pct: "2",
        max_orders_per_day: 20,
      },
      wake_me_if: [
        "daily_loss_pct > 1.2",
        "single_symbol_move_pct > 5",
        "any_breach_requiring_override > 0",
      ],
      predecided: [
        {
          when: "daily_loss_pct >= 1",
          then: "park_new_orders",
          reason: "Protect the remaining daily loss budget before the hard stop.",
        },
        {
          when: "single_symbol_move_pct >= 5",
          then: "park_new_orders",
          reason: "Reassess event risk after an exceptional single-name move.",
        },
      ],
      allow_short_positions: true,
      allow_risk_reducing_market_close: true,
      expires: "2099-08-28T20:00:00Z",
    },
    as_of: new Date().toISOString(),
    market_is_open: true,
    usage: {
      max_position_pct: "7.6334",
      gross_exposure_pct: "23.6737",
      daily_loss_pct: "0.0000",
      orders_today: 4,
    },
    headroom: {
      max_position_pct: "2.3666",
      max_gross_exposure_pct: "36.3263",
      max_daily_loss_pct: "2.0000",
      max_orders_per_day: 16,
    },
    wake_triggers: [],
    active_predecisions: [],
  };
}

function sessionState() {
  return {
    as_of: new Date().toISOString(),
    account: {
      status: "ACTIVE",
      equity: "100684.22",
      starting_equity: "100000.00",
      total_pnl: "684.22",
      total_pnl_pct: "0.68422",
      daily_pnl: "286.41",
      gross_exposure_pct: "23.6737",
    },
    market: { is_open: true, clock_timestamp: new Date().toISOString() },
    positions: {
      AAPL: {
        qty: "34", side: "long", asset_class: "us_equity",
        market_price: "228.41", market_value: "7765.94", avg_entry_price: "226.10",
        unrealized_pl: "78.54", unrealized_plpc: "0.0102",
        exit_policy: {
          stop: "0.90x ATR14 adverse move",
          target: "1.50x ATR14 favorable move",
          time_stop: "45m if still within 0.25x ATR14 of entry",
          flatten: "mandatory 15:50 ET session flatten",
        },
      },
      MSFT: {
        qty: "12", side: "long", asset_class: "us_equity",
        market_price: "512.08", market_value: "6144.96", avg_entry_price: "508.20",
        unrealized_pl: "46.56", unrealized_plpc: "0.0076",
        exit_policy: {
          stop: "0.90x ATR14 adverse move",
          target: "1.50x ATR14 favorable move",
          flatten: "mandatory 15:50 ET session flatten",
        },
      },
      NVDA: {
        qty: "28", side: "long", asset_class: "us_equity",
        market_price: "186.42", market_value: "5219.76", avg_entry_price: "183.10",
        unrealized_pl: "92.96", unrealized_plpc: "0.0181",
        exit_policy: {
          stop: "0.90x ATR14 adverse move",
          target: "1.50x ATR14 favorable move",
          flatten: "mandatory 15:50 ET session flatten",
        },
      },
      "NVDA260919C00190000": {
        qty: "2", side: "long", asset_class: "us_option",
        market_price: "1.41", market_value: "282.00", avg_entry_price: "1.24",
        unrealized_pl: "34.00", unrealized_plpc: "0.1371",
        exit_policy: {
          stop: "-25% unrealized P&L",
          target: "+40% unrealized P&L",
          time_stop: "180m in the dead band",
          expiry: "close at DTE <= 2",
          flatten: "mandatory 15:50 ET session flatten",
        },
      },
      BABA: {
        qty: "-20", side: "short", asset_class: "us_equity",
        market_price: "94.12", market_value: "-1882.40", avg_entry_price: "92.87",
        unrealized_pl: "-25.00", unrealized_plpc: "-0.0135",
        exit_policy: {
          stop: "0.90x ATR14 adverse move",
          target: "1.50x ATR14 favorable move",
          flatten: "mandatory 15:50 ET session flatten",
        },
      },
    },
    orders_today: 4,
    pending_orders: [
      {
        id: "mock-order-901", symbol: "NVDA", side: "buy", qty: "6", filled_qty: "0",
        type: "limit", limit_price: "182.90", status: "working", legs: 0,
      },
      {
        id: "mock-order-902", symbol: "CRM", side: "buy", qty: "11", filled_qty: "4",
        type: "limit", limit_price: "268.15", status: "partially_filled", legs: 0,
      },
    ],
    journal: journal(),
  };
}

function brokerOrders() {
  const filled = ({ id, symbol, assetClass = "us_equity", side, intent, qty, price, minutes }) => ({
    id,
    client_order_id: `mandate-demo-${id}`,
    replaces: null,
    replaced_by: null,
    symbol,
    asset_class: assetClass,
    side,
    position_intent: intent,
    ratio_qty: null,
    qty: String(qty),
    filled_qty: String(qty),
    filled_avg_price: String(price),
    order_class: "simple",
    status: "filled",
    submitted_at: minutesAgo(minutes + 1),
    filled_at: minutesAgo(minutes),
    legs: [],
  });
  return [
    filled({ id: "amd-entry", symbol: "AMD", side: "buy", intent: "buy_to_open", qty: 45, price: 161.20, minutes: 320 }),
    filled({ id: "amd-exit", symbol: "AMD", side: "sell", intent: "sell_to_close", qty: 45, price: 162.46, minutes: 262 }),
    filled({ id: "avgo-entry", symbol: "AVGO", side: "sell", intent: "sell_to_open", qty: 18, price: 348.50, minutes: 245 }),
    filled({ id: "aapl-entry", symbol: "AAPL", side: "buy", intent: "buy_to_open", qty: 34, price: 226.10, minutes: 214 }),
    filled({ id: "avgo-exit", symbol: "AVGO", side: "buy", intent: "buy_to_close", qty: 18, price: 345.80, minutes: 196 }),
    filled({ id: "msft-entry", symbol: "MSFT", side: "buy", intent: "buy_to_open", qty: 12, price: 508.20, minutes: 180 }),
    filled({ id: "nvda-entry", symbol: "NVDA", side: "buy", intent: "buy_to_open", qty: 28, price: 183.10, minutes: 166 }),
    filled({ id: "nvda-call-entry", symbol: "NVDA260919C00190000", assetClass: "us_option", side: "buy", intent: "buy_to_open", qty: 2, price: 1.24, minutes: 120 }),
    filled({ id: "baba-entry", symbol: "BABA", side: "sell", intent: "sell_to_open", qty: 20, price: 92.87, minutes: 80 }),
  ];
}

function journal() {
  return [
    {
      at: yesterdayAt(15, 42),
      action: "submit_order",
      outcome: "submitted",
      rationale: "Closing MSFT trend entry ahead of the session end; sizing well inside position headroom.",
      details: {
        intent_id: "msft-trend-close-09",
        client_order_id: "mandate-5d2ea71c48f09b3316ad7e02",
        order: { symbol: "MSFT", side: "buy", qty: "12", order_type: "limit", limit_price: "511.40", instrument: "equity" },
        mandate_fingerprint: "a41f77b2c9e80d6153ba4f2e7c08d9165be3247af80c5d1e93b6ca70f42d8e15",
      },
    },
    {
      at: yesterdayAt(16, 58),
      action: "park",
      outcome: "parked",
      rationale: "Session closed before the ARM setup confirmed; carried nothing overnight.",
      details: { intended_action: "buy 22 ARM limit 148.60" },
    },
    {
      at: minutesAgo(214),
      action: "submit_order",
      outcome: "prepared",
      rationale: "Momentum plus confirmed volume breakout on AAPL; sizing capped by ATR14 and mandate headroom.",
      details: {
        intent_id: "aapl-open-momentum-01",
        client_order_id: "mandate-8f2c41a09bd7e3554c1a99f2",
        order: { symbol: "AAPL", side: "buy", qty: "18", order_type: "limit", limit_price: "227.90", instrument: "equity" },
        order_fingerprint: "6b1d9f0c4a2e88f37bd5c0219ae4771f3c8d6e5a2b90f4417dc3e8a5b6027d94",
        mandate_fingerprint: "a41f77b2c9e80d6153ba4f2e7c08d9165be3247af80c5d1e93b6ca70f42d8e15",
      },
    },
    {
      at: minutesAgo(213),
      action: "submit_order",
      outcome: "submitted",
      rationale: "Momentum plus confirmed volume breakout on AAPL; sizing capped by ATR14 and mandate headroom.",
      details: {
        intent_id: "aapl-open-momentum-01",
        client_order_id: "mandate-8f2c41a09bd7e3554c1a99f2",
        order: { symbol: "AAPL", side: "buy", qty: "18", order_type: "limit", limit_price: "227.90", instrument: "equity" },
        mandate_fingerprint: "a41f77b2c9e80d6153ba4f2e7c08d9165be3247af80c5d1e93b6ca70f42d8e15",
      },
    },
    {
      at: minutesAgo(168),
      action: "submit_order",
      outcome: "denied",
      rationale: "Requested a concentrated NVDA add after the morning gap.",
      details: {
        intent_id: "nvda-gap-add-02",
        client_order_id: "mandate-3ce9017b4f2a6d8815ca07be",
        order: { symbol: "NVDA", side: "buy", qty: "74", order_type: "limit", limit_price: "183.40", instrument: "equity" },
        breaches: [
          { rule: "max_position_pct", limit: "10", projected: "13.4471", headroom: "-3.4471" },
        ],
        mandate_fingerprint: "a41f77b2c9e80d6153ba4f2e7c08d9165be3247af80c5d1e93b6ca70f42d8e15",
      },
    },
    {
      at: minutesAgo(166),
      action: "submit_order",
      outcome: "submitted",
      rationale: "Resized NVDA entry to fit the remaining position headroom after the denial.",
      details: {
        intent_id: "nvda-gap-add-03",
        client_order_id: "mandate-77b0e4c8195da2f36e0cb841",
        order: { symbol: "NVDA", side: "buy", qty: "28", order_type: "limit", limit_price: "183.10", instrument: "equity" },
        mandate_fingerprint: "a41f77b2c9e80d6153ba4f2e7c08d9165be3247af80c5d1e93b6ca70f42d8e15",
      },
    },
    {
      at: minutesAgo(97),
      action: "park",
      outcome: "parked",
      rationale: "BIDU headline is attributable but no second source confirms it, and relative volume is under the gate.",
      details: { intended_action: "buy 40 BIDU limit 92.30" },
    },
    {
      at: minutesAgo(64),
      action: "submit_order",
      outcome: "deduplicated",
      rationale: "Retry of the same AVGO intent after a transport error; the broker recovered the original client order ID.",
      details: {
        intent_id: "avgo-trend-04",
        client_order_id: "mandate-1a5b93cf60e2748d0fb35c19",
        mandate_fingerprint: "a41f77b2c9e80d6153ba4f2e7c08d9165be3247af80c5d1e93b6ca70f42d8e15",
      },
    },
    {
      at: minutesAgo(38),
      action: "submit_order",
      outcome: "conflict",
      rationale: "Same intent_id reused with different order terms after an operator edit.",
      details: {
        intent_id: "avgo-trend-04",
        client_order_id: "mandate-1a5b93cf60e2748d0fb35c19",
        order: { symbol: "AVGO", side: "buy", qty: "14", order_type: "limit", limit_price: "338.00", instrument: "equity" },
      },
    },
    {
      at: minutesAgo(21),
      action: "park",
      outcome: "parked",
      rationale: "Regular-hours gate passed but SPY sits below its 20-period average; risk-off scaling left no whole-share size.",
      details: { intended_action: "buy 5 ANET limit 141.20" },
    },
    ...state.decided,
  ];
}

function alerts() {
  const news = [
    {
      kind: "news",
      source: "alpaca",
      external_id: "alpaca-49128841",
      published_at: minutesAgo(9),
      headline: "Nvidia expands Blackwell supply agreements with two hyperscale customers",
      summary: "The company said additional capacity has been allocated for the next two quarters, with deliveries beginning in the current period.",
      symbols: ["NVDA"],
      url: "https://example.com/nvda-blackwell-supply",
    },
    {
      kind: "news",
      source: "apple-newsroom",
      external_id: "apple-2026-08-28-a",
      published_at: minutesAgo(34),
      headline: "Apple announces expanded on-device model availability for developers",
      summary: "A new framework lets applications run local inference without routing requests to Apple servers.",
      symbols: ["AAPL"],
      url: "https://example.com/apple-on-device",
    },
    {
      kind: "news",
      source: "sec-edgar",
      external_id: "edgar-0001045810-26-000117",
      published_at: minutesAgo(78),
      headline: "NVIDIA Corporation files Form 8-K",
      summary: "Item 2.02 Results of Operations and Financial Condition.",
      symbols: ["NVDA"],
      url: "https://example.com/edgar-nvda-8k",
    },
    {
      kind: "news",
      source: "federal-reserve",
      external_id: "fed-20260828-a",
      published_at: minutesAgo(122),
      headline: "Federal Reserve issues FOMC statement",
      summary: "The Committee decided to maintain the target range for the federal funds rate.",
      symbols: ["SPY"],
      url: "https://example.com/fomc-statement",
    },
    {
      kind: "news",
      source: "microsoft",
      external_id: "msft-2026-08-28-b",
      published_at: minutesAgo(151),
      headline: "Microsoft details next phase of datacenter capacity investment",
      summary: "The post outlines regional buildout plans and power procurement for the coming fiscal year.",
      symbols: ["MSFT"],
      url: "https://example.com/msft-datacenter",
    },
    {
      kind: "news",
      source: "alpaca",
      external_id: "alpaca-49128102",
      published_at: minutesAgo(198),
      headline: "Broadcom guidance points to sustained AI networking demand",
      summary: "Management reiterated its outlook while noting supply constraints in optical components.",
      symbols: ["AVGO"],
      url: "https://example.com/avgo-guidance",
    },
  ];
  return news.reverse();
}

function autonomyState() {
  return {
    trajectory: {
      version: state.trajectoryVersion,
      enabled: true,
      symbols: UNIVERSE,
      news_poll_seconds: 30,
      analysis_interval_minutes: state.analysisIntervalMinutes,
      monitoring_mode: "realtime",
      market_data_feed: "iex",
      discovery_enabled: true,
      discovery_top: 10,
      regular_hours_only: true,
      max_spread_bps: 35,
      min_relative_volume: 0.25,
      monitor_corporate_actions: true,
      options_confirmation: true,
      risk_posture: "opportunistic",
      thesis: "Rotate into the strongest liquid equity or defined-risk option setup, including admitted movers.",
      updated_by: "chat:narrow cadence to 15 minutes",
    },
    runtime: {
      status: "running",
      last_action: "PARK",
      last_analysis_at: minutesAgo(6),
      next_analysis_at: new Date(Date.now() + 9 * 60_000).toISOString(),
      quality_pass: 16,
      quality_total: 19,
      market_feed: "iex",
      outcomes_observed: 42,
      discovery_candidates: 5,
      ipo_candidates: 4,
      ipo_research_ready: 1,
      ipo_monitor_status: "monitoring",
      corporate_action_events: 1,
      stream: { news: "connected", market: "connected" },
      last_error: null,
    },
    alerts: alerts(),
    market: {
      checked_at: new Date().toISOString(),
      feed: "iex",
      market_is_open: true,
      benchmark: { symbol: "SPY", quality_pass: true, above_ma20: false },
      discovery: {
        movers: {
          gainers: [{ symbol: "SMCI" }, { symbol: "MU" }, { symbol: "COHR" }],
          losers: [{ symbol: "INTC" }, { symbol: "DELL" }],
        },
        most_active: [{ symbol: "TSLA" }, { symbol: "SOFI" }],
        ipos: {
          enabled: true,
          status: "ok",
          observation_only: true,
          candidates: [
            {
              symbol: "TP", company: "The Metals Company", listing_date: "2026-08-28",
              days_since_listing: 3, exchange: "NASDAQ", offer_price: "$18.00",
              research_ready: true, execution_ready: false,
              research_warnings: ["missing_spread", "stale"],
              alpaca: { tradable: true, fractionable: false, shortable: false, easy_to_borrow: false },
              quality: { last: "21.83", session_change_pct: "21.26", relative_volume: "5.823", spread_bps: null, freshest_seconds: 72 },
            },
            {
              symbol: "FBDT", company: "Fast Biodesign Technologies", listing_date: "2026-08-27",
              days_since_listing: 4, exchange: "NASDAQ", offer_price: "$10.00",
              research_ready: false, execution_ready: false,
              research_warnings: ["spread", "relative_volume"],
              alpaca: { tradable: true, fractionable: false, shortable: false, easy_to_borrow: false },
              quality: { last: "10.31", session_change_pct: "2.56", relative_volume: "0.284", spread_bps: "3002.04", freshest_seconds: 97 },
            },
            {
              symbol: "LTGO", company: "Lithium Growth Corp", listing_date: "2026-08-25",
              days_since_listing: 6, exchange: "NYSE", offer_price: "$14.00",
              research_ready: false, execution_ready: false,
              research_warnings: ["spread", "relative_volume"],
              alpaca: { tradable: true, fractionable: true, shortable: true, easy_to_borrow: true },
              quality: { last: "14.10", session_change_pct: "0.74", relative_volume: "0.101", spread_bps: "1779.82", freshest_seconds: 31 },
            },
          ],
        },
      },
      corporate_actions: [
        { symbol: "MSFT", type: "cash_dividend", ex_date: "2026-08-29" },
      ],
      options_confirmation: null,
    },
    outcomes: {
      scorecard: {
        momentum: { observations: 31, mean_signed_return_pct: "0.084", directional_accuracy_pct: "58.1", sharpe_like: "0.41", adaptive_multiplier: "1.12" },
        mean_reversion: { observations: 27, mean_signed_return_pct: "-0.031", directional_accuracy_pct: "44.4", sharpe_like: "-0.18", adaptive_multiplier: "0.88" },
        breakout_volume: { observations: 19, mean_signed_return_pct: "0.062", directional_accuracy_pct: "52.6", sharpe_like: "0.27", adaptive_multiplier: "1.05" },
        news_price_confirmed: { observations: 12, mean_signed_return_pct: "0.117", directional_accuracy_pct: "66.7", sharpe_like: "0.55", adaptive_multiplier: "1.20" },
        rsi_reversion: { observations: 24, mean_signed_return_pct: "0.009", directional_accuracy_pct: "50.0", sharpe_like: "0.05", adaptive_multiplier: "1.00" },
        macd_trend: { observations: 22, mean_signed_return_pct: "0.048", directional_accuracy_pct: "54.5", sharpe_like: "0.22", adaptive_multiplier: "1.03" },
        vol_adjusted_momentum: { observations: 18, mean_signed_return_pct: "0.071", directional_accuracy_pct: "55.6", sharpe_like: "0.33", adaptive_multiplier: "1.08" },
        regime_ensemble: { observations: 29, mean_signed_return_pct: "0.093", directional_accuracy_pct: "62.1", sharpe_like: "0.47", adaptive_multiplier: "1.15" },
      },
    },
  };
}

function approvals() {
  const items = [
    {
      tool_call_id: "call_7fd21ab9",
      session_id: "01m13p4d320fphtmwj6z4dcget",
      thread_id: "thread_5a0c19",
      session_title: "Autonomy cycle · NVDA supply headline",
      created_at: minutesAgo(3),
      tool_name: "append_trader_memory",
      arguments: {
        memory_key: "opening-gap-confirmation",
        hypothesis: "Require two price confirmations after an opening gap above 3%.",
        evidence_refs_json: "[\"operator:postmortem:42\"]",
        ttl_hours: 24,
      },
    },
  ];
  const open = items.filter((item) => !state.approvalsResolved.has(item.tool_call_id));
  return { count: open.length, items: open };
}

function applyDecision(item, approve) {
  const entry = {
    at: new Date().toISOString(),
    action: item.tool_name,
    outcome: approve ? "approved" : "denied",
    rationale: approve
      ? "Operator approved the bounded memory hypothesis."
      : "Operator kept the current trader memory unchanged.",
    details: { operator_decision: true },
  };
  state.decided.push(entry);
}

// --- Autonomous trader timeline (stateful, keeps growing while the mock runs) ---

const timelineState = { events: [], sequence: 0, startedAt: Date.now(), lastLiveCycleId: null };

function tradingDate() {
  return new Date().toISOString().slice(0, 10);
}

function event(kind, status, summary, details, atMs) {
  timelineState.sequence += 1;
  return {
    schema: "trader.timeline.v1",
    sequence: timelineState.sequence,
    at: new Date(atMs).toISOString(),
    trading_date: tradingDate(),
    kind,
    status,
    session_id: "mock-trader-session",
    summary,
    details,
  };
}

function executionRecord({ symbol, underlying, side, qty, limit, avg, kind, reason, candidate, filled = true, status = "filled" }) {
  return {
    accepted: true,
    filled,
    status,
    filled_qty: filled ? qty : "0",
    deduplicated: false,
    replacements: 0,
    kind,
    candidate: symbol,
    underlying: underlying ?? symbol,
    side,
    plan_cycle_id: "mock-cycle",
    plan_candidate_id: candidate,
    reason,
    exit_policy: kind.startsWith("option")
      ? { stop: "-25% unrealized P&L", target: "+40% unrealized P&L", time_stop: "180m in the dead band" }
      : null,
    order: { symbol, side, qty, type: "limit", limit_price: limit, time_in_force: "day" },
    result: {
      id: `mock-order-${Math.floor(Math.random() * 100000)}`,
      status,
      symbol,
      side,
      qty,
      filled_qty: filled ? qty : "0",
      filled_avg_price: filled ? avg : null,
      limit_price: limit,
      submitted_at: new Date().toISOString(),
      filled_at: filled ? new Date().toISOString() : null,
    },
  };
}

function seedCycle(cycleId, minutesBack, { executes = true, parkReason = null } = {}) {
  // The cycle spans ~1 minute ending at minutesBack ago, so a live cycle's
  // events never carry future timestamps.
  const base = Date.now() - (minutesBack + 1) * 60_000;
  const at = (offset) => base + offset * 1_000;
  const events = [
    event("trigger", "ok", `Scheduled analysis cycle ${cycleId}: news poll closed with 3 fresh signals.`, { cycle_id: cycleId, trigger: "scheduled_poll" }, at(0)),
    event("reasoning", "ok", "Momentum ensemble turned positive on NVDA after the Blackwell supply headline; spread and freshness gates pass.", { cycle_id: cycleId, source: "trader_model" }, at(6)),
    event("tool_call", "ok", "Research desk evaluating the NVDA setup.", {
      cycle_id: cycleId,
      tool: "research.evaluate_candidates",
      arguments: { symbols: ["NVDA", "AAPL"], depth: "full" },
    }, at(12)),
    event("tool_result", "ok", "Research desk returned 2 evaluated candidates.", {
      cycle_id: cycleId,
      tool: "research.evaluate_candidates",
      result: { candidates: 2, quality_pass: 2, feed: "iex" },
    }, at(20)),
    event("critics", "ok", "Risk, news and execution critics returned advisory verdicts.", {
      cycle_id: cycleId,
      items: [
        { critic: "risk", verdict: "pass", reason: "Sizing inside position and gross headroom." },
        { critic: "news", verdict: "pass", reason: "Headline confirmed by a second source." },
        { critic: "execution", verdict: "pass", reason: "Spread 4bps, relative volume 2.1x." },
      ],
    }, at(28)),
    event("plan", "ok", executes ? "Plan delegated one entry to the paper executor." : "Plan chose PARK; nothing was delegated to execution.", {
      cycle_id: cycleId,
      plan: {
        action: executes ? "EXECUTE_PLAN" : "PARK",
        reason: executes
          ? "News-confirmed momentum with volume confirmation on NVDA."
          : (parkReason ?? "No candidate cleared the combined signal and risk gates."),
        hypotheses: [
          {
            candidate_id: "nvda-momentum-01",
            confidence: "medium",
            thesis: "Supply expansion headline keeps the momentum regime intact for two more sessions.",
            invalidation: "Failure to hold above the opening range midpoint.",
            supports: ["alpaca-49128841", "sec-edgar-0001045810-26-000117"],
            contradicts: [],
          },
        ],
        steps: executes
          ? [{ candidate_id: "nvda-momentum-01", reason: "Buy the 190 call, defined risk, sizing capped by premium budget.", evidence_refs: ["alpaca-49128841"] }]
          : [],
        critic_resolutions: [
          { critic: "risk", resolution: "accepted", reason: "Premium exposure is 0.3% of equity." },
        ],
      },
    }, at(36)),
  ];
  if (executes) {
    events.push(
      event("execution", "submitted", "Paper executor submitted the delegated plan; both legs filled.", {
        cycle_id: cycleId,
        tool: "alpaca.execute_trade_plan",
        result: {
          submitted: true,
          action: "EXECUTE_PLAN",
          executions: [
            executionRecord({
              symbol: "NVDA260919C00190000", underlying: "NVDA", side: "buy", qty: "2",
              limit: "1.26", avg: "1.24", kind: "option_entry",
              reason: "News-confirmed momentum; defined-risk premium sized to 0.3% of equity.",
              candidate: "nvda-momentum-01",
            }),
            executionRecord({
              symbol: "NVDA", side: "buy", qty: "28", limit: "183.20", avg: "183.10", kind: "entry",
              reason: "Core equity leg sized by ATR14 inside position headroom.",
              candidate: "nvda-momentum-01",
            }),
          ],
          errors: [],
          risk_gate: { passed: true },
        },
      }, at(48)),
    );
  }
  events.push(
    event("session", "ok", "Cycle closed; runtime heartbeats and journals the decision trail.", { cycle_id: cycleId }, at(56)),
  );
  return events;
}

function riskExitEvent() {
  return event("risk_exit", "ok", "Time stop flattened a dead-band AAPL position at the session review.", {
    cycle_id: "cycle-043",
    tool: "risk.evaluate_open_positions",
    result: {
      submitted: true,
      executions: [
        executionRecord({
          symbol: "AAPL", side: "sell", qty: "10", limit: "227.80", avg: "227.85", kind: "exit",
          reason: "45 minutes inside the 0.25x ATR14 dead band; time stop fired.",
          candidate: "aapl-open-momentum-01",
        }),
      ],
      errors: [],
    },
  }, Date.now() - 20 * 60_000);
}

function seedTimeline() {
  if (timelineState.events.length > 0) return;
  timelineState.events = [
    ...seedCycle("cycle-041", 96, { executes: true }),
    ...seedCycle("cycle-042", 64, { executes: false, parkReason: "BIDU headline lacked a second source; relative volume under the gate." }),
    ...seedCycle("cycle-043", 28, { executes: true }),
    riskExitEvent(),
    ...seedCycle("cycle-044", 6, { executes: false, parkReason: "Market data gate failed: 16 of 19 symbols passed spread and freshness checks." }),
  ];
}

const LIVE_CYCLE_VARIANTS = [
  { executes: false, parkReason: "No candidate cleared the combined signal and risk gates." },
  { executes: true },
  { executes: false, parkReason: "Spread on the AVGO setup widened past the 35bps gate." },
];

function appendLiveCycle() {
  seedTimeline();
  const index = Math.floor((Date.now() - timelineState.startedAt) / 45_000) % LIVE_CYCLE_VARIANTS.length;
  const cycleId = `cycle-${450 + Math.floor((Date.now() - timelineState.startedAt) / 45_000)}`;
  if (cycleId === timelineState.lastLiveCycleId) return;
  timelineState.lastLiveCycleId = cycleId;
  timelineState.events.push(...seedCycle(cycleId, 0, LIVE_CYCLE_VARIANTS[index]));
}

function degradedSnapshot() {
  const mandate = mandateState();
  return {
    generated_at: new Date().toISOString(),
    source: "degraded",
    paper_only: true,
    agent_url: "http://localhost:8790",
    mandate: {
      mandate: mandate.mandate,
      as_of: null,
      market_is_open: false,
      usage: {},
      headroom: {},
      wake_triggers: [],
      active_predecisions: [],
    },
    session: {
      as_of: null,
      account: {},
      market: { is_open: false },
      positions: {},
      orders_today: 0,
      pending_orders: [],
      journal: journal(),
    },
    services: [
      { name: "alpaca", url: "http://127.0.0.1:8000/mcp", ok: false },
      { name: "research", url: "http://127.0.0.1:8020/mcp", ok: true },
      { name: "trueforge", url: "http://localhost:8790", ok: true },
    ],
    autonomy: autonomyState(),
    approvals: approvals(),
    errors: ["paper broker unavailable: ConnectionRefusedError"],
  };
}

function snapshot() {
  if (state.degraded) return degradedSnapshot();
  return {
    generated_at: new Date().toISOString(),
    source: "live",
    paper_only: true,
    agent_url: "http://localhost:8790",
    mandate: mandateState(),
    session: sessionState(),
    services: [
      { name: "alpaca", url: "http://127.0.0.1:8000/mcp", ok: true },
      { name: "research", url: "http://127.0.0.1:8020/mcp", ok: true },
      { name: "trueforge", url: "http://localhost:8790", ok: true },
    ],
    autonomy: autonomyState(),
    approvals: approvals(),
    errors: [],
  };
}

async function readBody(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  if (!chunks.length) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    return {};
  }
}

function send(response, status, payload) {
  const body = JSON.stringify(payload);
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type, Accept",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  });
  response.end(body);
}

const server = createServer(async (request, response) => {
  const url = new URL(request.url ?? "/", `http://${request.headers.host}`);
  if (request.method === "OPTIONS") return send(response, 204, {});
  if (url.pathname === "/api/snapshot") return send(response, 200, snapshot());
  if (url.pathname === "/api/trade-history/orders") {
    return send(response, 200, { schema: "trade.orders.v1", items: brokerOrders() });
  }
  if (url.pathname === "/api/trader/timeline") {
    seedTimeline();
    const after = Number(url.searchParams.get("after") ?? 0);
    const limit = Number(url.searchParams.get("limit") ?? 200);
    const latest = url.searchParams.has("latest") ? Number(url.searchParams.get("latest")) : null;
    let items = timelineState.events.filter((item) => item.sequence > after);
    if (latest !== null) items = items.slice(-latest);
    else items = items.slice(0, limit);
    return send(response, 200, {
      schema: "trader.timeline.page.v1",
      items,
      next_after: items.at(-1)?.sequence ?? after,
    });
  }
  if (url.pathname === "/api/trader/stream") {
    seedTimeline();
    const after = Number(url.searchParams.get("after") ?? 0);
    if (!Number.isInteger(after) || after < 0) {
      return send(response, 400, { error: "after must be a nonnegative integer" });
    }
    response.writeHead(200, {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      "Connection": "keep-alive",
      "Access-Control-Allow-Origin": "*",
    });
    let cursor = after;
    let keepaliveAt = Date.now();
    let streamTimer = null;
    const tick = () => {
      if (response.destroyed) return;
      if (Math.random() < 0.06) appendLiveCycle();
      const items = timelineState.events.filter((item) => item.sequence > cursor);
      for (const item of items) {
        cursor = item.sequence;
        response.write(`id: ${cursor}\nevent: trader_event\ndata: ${JSON.stringify(item)}\n\n`);
      }
      if (Date.now() - keepaliveAt >= 15_000) {
        response.write(": keepalive\n\n");
        keepaliveAt = Date.now();
      }
      streamTimer = setTimeout(tick, 1_000);
    };
    streamTimer = setTimeout(tick, 1_000);
    response.on("close", () => clearTimeout(streamTimer));
    return;
  }
  if (url.pathname === "/api/mock/degraded") {
    state.degraded = url.searchParams.get("on") === "true";
    return send(response, 200, { degraded: state.degraded });
  }
  if (url.pathname === "/api/trajectory" && request.method === "POST") {
    const body = await readBody(request);
    if (!body.confirmed) return send(response, 400, { error: "confirmation is required" });
    state.trajectoryVersion += 1;
    return send(response, 200, {
      trajectory: { ...autonomyState().trajectory },
      mandate_unchanged: true,
    });
  }
  if (url.pathname === "/api/approvals/respond" && request.method === "POST") {
    const body = await readBody(request);
    if (!body.confirmed) return send(response, 400, { error: "confirmation is required" });
    if (!body.tool_call_id) return send(response, 400, { error: "tool_call_id is required" });
    const toolCallId = String(body.tool_call_id);
    const pending = approvals().items.find((item) => item.tool_call_id === toolCallId);
    state.approvalsResolved.add(toolCallId);
    if (pending) applyDecision(pending, Boolean(body.approve));
    return send(response, 200, { delivered: true, approved: Boolean(body.approve) });
  }
  return send(response, 404, { error: "not found" });
});

server.listen(PORT, HOST, () => {
  console.log(`MANDATE mock dashboard API on http://${HOST}:${PORT}/api/snapshot`);
  console.log("Mock data only. No broker, no credentials, no live endpoint.");
});
