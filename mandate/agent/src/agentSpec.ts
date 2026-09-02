import type { TrueForgeApi } from "@truefoundry/trueforge-sdk";

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
  model = "zai/glm-4-7-flashx",
): TrueForgeApi.AgentSpec {
  return {
    model: { name: model },
    instructions,
    mcpServers: [{
      name: "mandate-research",
      enableTools: ["list_trader_memory", "append_trader_memory"],
      disableTools: [],
      preloadTools: ["list_trader_memory"],
      preload: false,
      requireApprovalForTools: ["append_trader_memory"],
    }],
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
