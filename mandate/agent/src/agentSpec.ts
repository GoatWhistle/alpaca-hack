import type { TrueForgeApi } from "@truefoundry/trueforge-sdk";

import { ALPACA_RESEARCH_TOOLS, ALPACA_WRITE_TOOLS } from "./alpacaTools.js";

export function parseOptionalBoolean(value: string | undefined, name: string): boolean {
  if (value === undefined || value === "") return false;
  if (value === "true") return true;
  if (value === "false") return false;
  throw new Error(`${name} must be true or false`);
}

export function buildAgentSpec(
  instructions: string,
  enableResearchSkill = false,
): TrueForgeApi.AgentSpec {
  return {
    model: { name: "zai/glm-5-3-flash" },
    instructions,
    ...(enableResearchSkill ? { skills: [{ name: "mandate-research" }] } : {}),
    mcpServers: [
      {
        name: "mandate-guard",
        enableTools: ["@all"],
        disableTools: [],
        preload: true,
        requireApprovalForTools: [
          "submit_order_under_mandate",
          "cancel_order",
          "close_position",
          "update_trajectory",
        ],
      },
      {
        name: "alpaca",
        enableTools: [...ALPACA_RESEARCH_TOOLS],
        disableTools: [...ALPACA_WRITE_TOOLS],
        preloadTools: ["get_clock", "get_stock_bars", "get_stock_latest_quote"],
        preload: false,
        requireApprovalForTools: [],
      },
      {
        name: "mandate-research",
        enableTools: ["probe_news_sources", "score_news_llm", "compare_live_signals", "get_market_monitoring", "evaluate_trajectory"],
        disableTools: [],
        preloadTools: ["evaluate_trajectory", "compare_live_signals", "get_market_monitoring"],
        preload: false,
        requireApprovalForTools: [],
      },
    ],
    config: {
      iterationLimit: 100,
      sandbox: { enabled: true, fileDownloads: true },
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
