import type { TrueForgeApi } from "@truefoundry/trueforge-sdk";

/**
 * Read-only tools of the official Alpaca MCP server (alpacahq/alpaca-mcp-server v2)
 * that the operator assistant may call. Every order, cancel, close, exercise or
 * configuration tool is listed in the deny list so a prompt can never trade.
 */
export const ALPACA_MCP_READ_TOOLS = [
  "get_account_info", "get_account_config", "get_portfolio_history", "get_account_activities",
  "get_all_positions", "get_open_position", "get_orders", "get_order_by_id",
  "get_clock", "get_calendar", "get_asset", "get_option_contracts", "get_option_contract",
  "get_corporate_action_announcements", "get_stock_snapshot", "get_stock_latest_quote",
  "get_stock_latest_trade", "get_stock_bars", "get_market_movers", "get_most_active_stocks",
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
    model: { name: model },
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
      preloadTools: ["get_account_info"],
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
