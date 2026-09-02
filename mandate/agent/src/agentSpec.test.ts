import assert from "node:assert/strict";
import test from "node:test";

import {
  ALPACA_MCP_READ_TOOLS,
  ALPACA_MCP_WRITE_TOOLS,
  buildCriticSpec,
  buildOperatorSpec,
  buildTraderSpec,
} from "./agentSpec.js";


test("the automatic trader has planning authority but no tools", () => {
  const spec = buildTraderSpec("instructions", "zai/trader-model");
  assert.equal("skills" in spec, false);
  assert.equal(spec.model.name, "zai/trader-model");
  assert.equal(spec.model.params?.maxTokens, 4_096);
  assert.deepEqual(spec.model.params?.thinking, { type: "disabled" });
  assert.deepEqual(spec.mcpServers, []);
  assert.equal(spec.config?.sandbox?.enabled, false);
  assert.equal(spec.config?.dynamicSubAgents?.enabled, false);
});

test("critics use their configured model and have no execution authority", () => {
  const spec = buildCriticSpec("risk only", "zai/risk-model");
  assert.equal(spec.model.name, "zai/risk-model");
  assert.equal(spec.model.params?.maxTokens, 512);
  assert.deepEqual(spec.model.params?.thinking, { type: "disabled" });
  assert.deepEqual(spec.mcpServers, []);
  assert.equal(spec.config?.iterationLimit, 2);
  assert.equal(spec.config?.sandbox?.enabled, false);
});

test("operator can only read or approval-gate trader memory", () => {
  const spec = buildOperatorSpec("operator", "zai/operator-model");
  assert.equal(spec.model.name, "zai/operator-model");
  assert.deepEqual(spec.mcpServers?.[0]?.enableTools, [
    "get_trader_context", "list_trader_memory", "append_trader_memory",
  ]);
  assert.deepEqual(spec.mcpServers?.[0]?.requireApprovalForTools, ["append_trader_memory"]);
  assert.equal(spec.config?.dynamicSubAgents?.enabled, false);
  assert.equal(spec.config?.sandbox?.enabled, false);
});

test("operator receives only read-only Alpaca MCP tools when the server is configured", () => {
  const withoutAlpaca = buildOperatorSpec("operator", "zai/operator-model");
  assert.equal(withoutAlpaca.mcpServers?.length, 1);
  const spec = buildOperatorSpec("operator", "zai/operator-model", { alpacaMcp: true });
  const alpaca = spec.mcpServers?.find((server) => server.name === "alpaca");
  assert.ok(alpaca);
  assert.deepEqual(alpaca.enableTools, [...ALPACA_MCP_READ_TOOLS]);
  assert.deepEqual(alpaca.disableTools, [...ALPACA_MCP_WRITE_TOOLS]);
  for (const tool of ALPACA_MCP_WRITE_TOOLS) {
    assert.equal((alpaca.enableTools as readonly string[] | undefined)?.includes(tool), false);
  }
  assert.deepEqual(alpaca.requireApprovalForTools, []);
  assert.deepEqual(spec.mcpServers?.[0]?.enableTools, [
    "get_trader_context", "list_trader_memory", "append_trader_memory",
  ]);
});
