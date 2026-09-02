import assert from "node:assert/strict";
import test from "node:test";

import { buildAgentSpec } from "./agentSpec.js";


test("writes pause for approval and research is provided by MCP", () => {
  const spec = buildAgentSpec("instructions");
  const alpaca = spec.mcpServers?.[0];
  assert.equal("skills" in spec, false);
  assert.equal(alpaca?.name, "alpaca");
  assert.ok(alpaca?.enableTools?.includes("place_stock_order"));
  assert.ok(alpaca?.requireApprovalForTools?.includes("place_stock_order"));
  assert.deepEqual(spec.mcpServers?.map((server) => server.name), ["alpaca", "mandate-research"]);
});
