import assert from "node:assert/strict";
import test from "node:test";

import { buildAgentSpec, parseOptionalBoolean } from "./agentSpec.js";


test("Git research skill is opt-in so sandbox startup does not depend on GitHub", () => {
  const defaultSpec = buildAgentSpec("instructions");
  assert.equal("skills" in defaultSpec, false);

  const enabledSpec = buildAgentSpec("instructions", true);
  assert.deepEqual(enabledSpec.skills, [{ name: "mandate-research" }]);
});

test("research skill environment flag fails closed", () => {
  assert.equal(parseOptionalBoolean(undefined, "FLAG"), false);
  assert.equal(parseOptionalBoolean("", "FLAG"), false);
  assert.equal(parseOptionalBoolean("false", "FLAG"), false);
  assert.equal(parseOptionalBoolean("true", "FLAG"), true);
  assert.throws(() => parseOptionalBoolean("yes", "FLAG"), /FLAG must be true or false/);
});

test("only the auto paper agent bypasses submit approval", () => {
  const manual = buildAgentSpec("instructions", false, true);
  const automatic = buildAgentSpec("instructions", false, false);
  const manualGuard = manual.mcpServers?.[0];
  const automaticGuard = automatic.mcpServers?.[0];
  assert.ok(manualGuard?.requireApprovalForTools?.includes("submit_order_under_mandate"));
  assert.equal(automaticGuard?.requireApprovalForTools?.includes("submit_order_under_mandate"), false);
  assert.ok(automaticGuard?.requireApprovalForTools?.includes("cancel_order"));
  assert.ok(automaticGuard?.requireApprovalForTools?.includes("close_position"));
});
