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
