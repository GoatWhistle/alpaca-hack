import type { TrueForgeApi } from "@truefoundry/trueforge-sdk";

import { ALPACA_RESEARCH_TOOLS, ALPACA_WRITE_TOOLS } from "./alpacaTools.js";

export function buildAgentSpec(instructions: string): TrueForgeApi.AgentSpec {
  return {
    model: { name: "zai/glm-5-3-flash" },
    instructions,
    skills: [{ name: "mandate-research" }],
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
