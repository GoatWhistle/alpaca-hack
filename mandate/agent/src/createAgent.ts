import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import { TrueForge } from "@truefoundry/trueforge-sdk";

import { buildAgentSpec } from "./agentSpec.js";

const AGENT_NAME = "mandate-paper-agent";
const baseUrl = process.env.TRUEFORGE_BASE_URL ?? "http://localhost:8790";
const guardUrl = process.env.MANDATE_GUARD_URL ?? "http://127.0.0.1:8010/mcp";
const researchUrl = process.env.MANDATE_RESEARCH_URL ?? "http://127.0.0.1:8020/mcp";
const skillRef = process.env.MANDATE_GIT_REF ?? "feat/mandate-integration";
const enableResearchSkill = process.env.MANDATE_ENABLE_RESEARCH_SKILL !== "false";
const parsedGuardUrl = new URL(guardUrl);
const parsedResearchUrl = new URL(researchUrl);
for (const [name, url] of [
  ["MANDATE_GUARD_URL", parsedGuardUrl],
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
    name: "mandate-guard",
    url: parsedGuardUrl.toString(),
    description: "Deterministic paper-only mandate enforcement and auditable execution boundary.",
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

const manifest = buildAgentSpec(instructions, enableResearchSkill);
const existing = (await client.agents.list()).data.find((agent) => agent.name === AGENT_NAME);
const result = existing
  ? await client.agents.update(existing.id, { manifest })
  : await client.agents.create({ name: AGENT_NAME, manifest });

console.log(JSON.stringify({ id: result.data.id, name: result.data.name }, null, 2));
