import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import { TrueForge } from "@truefoundry/trueforge-sdk";

import { buildAgentSpec, parseOptionalBoolean } from "./agentSpec.js";
import { loadWorkspaceEnv } from "./workspaceEnv.js";

loadWorkspaceEnv();

const AGENT_NAME = "mandate-paper-agent";
const AUTO_AGENT_NAME = "mandate-paper-agent-auto";
const baseUrl = process.env.TRUEFORGE_BASE_URL ?? "http://localhost:8790";
const alpacaUrl = process.env.MANDATE_ALPACA_MCP_URL ?? "http://127.0.0.1:8000/mcp";
const researchUrl = process.env.MANDATE_RESEARCH_URL ?? "http://127.0.0.1:8020/mcp";
const skillRef = process.env.MANDATE_GIT_REF ?? "feat/mandate-integration";
const enableResearchSkill = parseOptionalBoolean(
  process.env.MANDATE_ENABLE_RESEARCH_SKILL,
  "MANDATE_ENABLE_RESEARCH_SKILL",
);
const sandboxSetting = process.env.MANDATE_ENABLE_SANDBOX;
if (sandboxSetting !== undefined && sandboxSetting !== "true" && sandboxSetting !== "false") {
  throw new Error("MANDATE_ENABLE_SANDBOX must be true or false");
}
const enableSandbox = sandboxSetting !== "false";
const parsedAlpacaUrl = new URL(alpacaUrl);
const parsedResearchUrl = new URL(researchUrl);
for (const [name, url] of [
  ["MANDATE_ALPACA_MCP_URL", parsedAlpacaUrl],
  ["MANDATE_RESEARCH_URL", parsedResearchUrl],
] as const) {
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) {
    throw new Error(`${name} must be an HTTP(S) URL without embedded credentials`);
  }
}
const promptPath = fileURLToPath(new URL("../prompt.md", import.meta.url));
const instructions = await readFile(promptPath, "utf8");
const client = new TrueForge({
  baseUrl,
  token: process.env.TRUEFORGE_API_KEY || undefined,
});

await client.settings.mcpServers.createOrUpdate({
  manifest: {
    type: "remote",
    name: "alpaca",
    url: parsedAlpacaUrl.toString(),
    description:
      "Official Alpaca MCP v2 with direct paper-account research and trading tools.",
  },
});

await client.settings.mcpServers.createOrUpdate({
  manifest: {
    type: "remote",
    name: "mandate-research",
    url: parsedResearchUrl.toString(),
    description: "Read-only multi-source news parsing and explainable live signal comparison.",
  },
});

if (enableResearchSkill) {
  await client.settings.skills.createOrUpdate({
    manifest: {
      type: "git",
      name: "mandate-research",
      url: "https://github.com/GoatWhistle/harness-hack",
      ref: skillRef,
      path: "mandate/research",
      description:
        "Compare point-in-time-safe news-confirmed, momentum, mean-reversion, and breakout signals in the sandbox.",
    },
  });
}

const agents = (await client.agents.list()).data;
const applyAgent = async (name: string, requireSubmitApproval: boolean) => {
  const manifest = buildAgentSpec(
    instructions,
    enableResearchSkill,
    requireSubmitApproval,
    enableSandbox,
  );
  const existing = agents.find((agent) => agent.name === name);
  return existing
    ? client.agents.update(existing.id, { manifest })
    : client.agents.create({ name, manifest });
};
const [manual, automatic] = await Promise.all([
  applyAgent(AGENT_NAME, true),
  applyAgent(AUTO_AGENT_NAME, false),
]);

console.log(JSON.stringify({
  manual: { id: manual.data.id, name: manual.data.name },
  automatic: { id: automatic.data.id, name: automatic.data.name },
}, null, 2));
