// Explicit allow/deny lists from alpaca-mcp-server's live tools/list response.
// Never replace these with @all or a broad tag: most generated tools lack annotations.
export const ALPACA_READ_TOOLS = [
  "get_account_info",
  "get_all_positions",
  "get_orders",
  "get_calendar",
  "get_clock",
  "get_stock_bars",
  "get_stock_latest_bar",
  "get_stock_latest_quote",
  "get_stock_latest_trade",
  "get_stock_quotes",
  "get_stock_snapshot",
  "get_stock_trades",
] as const;

export const ALPACA_WRITE_TOOLS = [
  "add_asset_to_watchlist_by_id",
  "cancel_all_orders",
  "cancel_order_by_id",
  "close_all_positions",
  "close_position",
  "create_locate",
  "create_watchlist",
  "delete_watchlist_by_id",
  "do_not_exercise_options_position",
  "exercise_options_position",
  "place_crypto_order",
  "place_option_order",
  "place_stock_order",
  "remove_asset_from_watchlist_by_id",
  "replace_order_by_id",
  "update_account_config",
  "update_watchlist_by_id",
] as const;
