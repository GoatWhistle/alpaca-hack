import type { TrueForgeApi } from "@truefoundry/trueforge-sdk";

import { ALPACA_READ_TOOLS, ALPACA_WRITE_TOOLS } from "./alpacaTools.js";

export function buildAgentSpec(
  instructions: string,
  enableSandbox = true,
): TrueForgeApi.AgentSpec {
  return {
    model: { name: "zai/glm-5-3-flash" },
    instructions,
    mcpServers: [
      {
        name: "alpaca",
        enableTools: [...ALPACA_READ_TOOLS, ...ALPACA_WRITE_TOOLS],
        disableTools: [],
        preloadTools: ["get_account_info", "get_all_positions", "get_clock", "get_stock_bars", "get_stock_latest_quote"],
        preload: false,
        requireApprovalForTools: [...ALPACA_WRITE_TOOLS],
      },
      {
        name: "mandate-research",
        enableTools: ["probe_news_sources", "score_news_llm", "compare_live_signals", "get_market_monitoring", "evaluate_trajectory", "evaluate_position_exits"],
        disableTools: [],
        preloadTools: ["evaluate_trajectory", "compare_live_signals", "get_market_monitoring"],
        preload: false,
        requireApprovalForTools: [],
      },
    ],
    config: {
      iterationLimit: 100,
      sandbox: { enabled: enableSandbox, fileDownloads: enableSandbox },
      dynamicSubAgents: { enabled: true },
      generativeUi: { enabled: true },
      askUserQuestions: { enabled: true },
      contextManagement: {
        compaction: { enabled: true },
        largeToolResponse: { enabled: true },
      },
    },
  };
}
