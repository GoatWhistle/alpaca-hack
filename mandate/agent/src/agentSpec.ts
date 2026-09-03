import type { TrueForgeApi } from "@truefoundry/trueforge-sdk";

/**
 * Public market/reference tools allowed from the official Alpaca MCP server.
 * Deployment also pins ALPACA_TOOLSETS=assets,stock-data; private account and
 * order tools remain absent from this defense-in-depth allowlist.
 */
export const ALPACA_MCP_READ_TOOLS = [
  "get_stock_bars", "get_stock_quotes", "get_stock_trades",
  "get_crypto_bars", "get_crypto_quotes", "get_crypto_trades",
  "search_alpaca_docs", "fetch_alpaca_doc", "search_alpaca_api_specs",
  "list_alpaca_api_endpoints", "get_alpaca_endpoint_docs",
  "get_all_assets", "get_asset", "get_calendar", "get_clock",
  "get_corporate_action_announcements", "get_corporate_action_announcement",
  "get_option_contracts", "get_option_contract", "get_market_movers",
  "get_most_active_stocks", "get_stock_latest_bar", "get_stock_latest_quote",
  "get_stock_snapshot", "get_stock_latest_trade",
] as const;

export const ALPACA_MCP_WRITE_TOOLS = [
  "place_stock_order", "place_crypto_order", "place_option_order",
  "cancel_all_orders", "cancel_order_by_id", "replace_order_by_id",
  "close_all_positions", "close_position",
  "exercise_options_position", "do_not_exercise_options_position",
  "update_account_config",
  "create_locate",
  "create_watchlist", "update_watchlist_by_id", "delete_watchlist_by_id",
  "add_asset_to_watchlist", "remove_asset_from_watchlist",
] as const;

export function buildTraderSpec(
  instructions: string,
  model = "zai/glm-5-3-flash",
): TrueForgeApi.AgentSpec {
  return {
    model: {
      name: model,
      params: { maxTokens: 4_096, temperature: 0.1, thinking: { type: "disabled" } },
    },
    instructions,
    // The trader emits a plan only. Broker execution remains in the local,
    // deterministic paper executor and is never delegated to TrueForge.
    mcpServers: [],
    config: {
      iterationLimit: 4,
      sandbox: { enabled: false, fileDownloads: false },
      dynamicSubAgents: { enabled: false },
      generativeUi: { enabled: false },
      askUserQuestions: { enabled: false },
      contextManagement: {
        compaction: { enabled: true },
        largeToolResponse: { enabled: true },
      },
    },
  };
}

export function buildCriticSpec(
  instructions: string,
  model: string,
): TrueForgeApi.AgentSpec {
  const base = buildTraderSpec(instructions, model);
  return {
    ...base,
    model: {
      name: model,
      params: { maxTokens: 512, temperature: 0, thinking: { type: "disabled" } },
    },
    config: {
      ...base.config,
      iterationLimit: 2,
      contextManagement: {
        compaction: { enabled: false },
        largeToolResponse: { enabled: false },
      },
    },
  };
}

export function buildPositionWatcherSpec(
  instructions: string,
  model: string,
): TrueForgeApi.AgentSpec {
  const base = buildCriticSpec(instructions, model);
  return {
    ...base,
    model: {
      name: model,
      params: { maxTokens: 1_200, temperature: 0, thinking: { type: "disabled" } },
    },
  };
}

export function buildOperatorSpec(
  instructions: string,
  model = "zai/glm-4-5-air",
  options: { alpacaMcp?: boolean } = {},
): TrueForgeApi.AgentSpec {
  const mcpServers: NonNullable<TrueForgeApi.AgentSpec["mcpServers"]> = [{
    name: "mandate-research",
    enableTools: ["get_trader_context", "list_trader_memory", "append_trader_memory"],
    disableTools: [],
    preloadTools: ["get_trader_context", "list_trader_memory"],
    preload: false,
    requireApprovalForTools: ["append_trader_memory"],
  }];
  if (options.alpacaMcp) {
    mcpServers.push({
      name: "alpaca",
      enableTools: [...ALPACA_MCP_READ_TOOLS],
      disableTools: [...ALPACA_MCP_WRITE_TOOLS],
      preloadTools: ["get_clock"],
      preload: false,
      requireApprovalForTools: [],
    });
  }
  return {
    model: { name: model },
    instructions,
    mcpServers,
    config: {
      iterationLimit: 8,
      sandbox: { enabled: false, fileDownloads: false },
      dynamicSubAgents: { enabled: false },
      generativeUi: { enabled: false },
      askUserQuestions: { enabled: true },
      contextManagement: {
        compaction: { enabled: true },
        largeToolResponse: { enabled: true },
      },
    },
  };
}
