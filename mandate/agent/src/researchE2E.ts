import { TrueForge } from "@truefoundry/trueforge-sdk";

const baseUrl = process.env.TRUEFORGE_BASE_URL ?? "http://localhost:8790";
const agentName = process.env.MANDATE_AGENT_NAME ?? "mandate-paper-agent";
const trajectorySymbols = ["AAPL", "MSFT", "NVDA", "SPY"];
const requiredTools = new Set(["evaluate_trajectory", "get_mandate"]);
const forbiddenTools = new Set([
  "exec",
  "compare_live_signals",
  "get_market_monitoring",
  "submit_order_under_mandate",
  "cancel_order",
  "close_position",
  "park",
]);
const bridgeTools = new Set(["call_tool", "get_tool_info", "list_tools"]);

function parseObject(content: string): Record<string, unknown> {
  const start = content.indexOf("{");
  const end = content.lastIndexOf("}");
  if (start < 0 || end < start) throw new Error("tool response contained no JSON object");
  const decoded = JSON.parse(content.slice(start, end + 1)) as unknown;
  if (typeof decoded !== "object" || decoded === null || Array.isArray(decoded)) {
    throw new Error("tool response was not a JSON object");
  }
  return decoded as Record<string, unknown>;
}

function object(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${label} was not an object`);
  }
  return value as Record<string, unknown>;
}

function messageText(content: string | { type: string; text?: string; refusal?: string }[]): string {
  if (typeof content === "string") return content;
  return content.map((part) => (part.type === "text" ? (part.text ?? "") : (part.refusal ?? ""))).join("\n");
}

const client = new TrueForge({ baseUrl });
const calls = new Map<string, string>();
const callArguments = new Map<string, string>();
const responses = new Map<string, string>();
let finalText = "";
const sessionId = (await client.sessions.create({ agent: { name: agentName } })).data.id;
const stream = await client.sessions.createTurnStream(sessionId, {
  input: [{
    type: "user.message",
    content:
      `Run one read-only trajectory evaluation for ${trajectorySymbols.join(",")}. Call get_mandate and ` +
      "call mandate-research evaluate_trajectory exactly once with fee_bps 1, research_limit 8, max_spread_bps 35, " +
      "min_relative_volume 0.25 and single_symbol_move_pct 5. Pass account.equity plus both position " +
      "and gross-exposure percentage headrooms from get_mandate so sizing is ready. Use the returned arithmetic directly. " +
      "Do not create subagents. Do not call exec, compare_live_signals, get_market_monitoring, or write calculation code. " +
      "Do not call any broker-write tool. End with exactly one line ACTION: PARK or ACTION: PROPOSE. " +
      "PROPOSE means research discussion only and never execution.",
  }],
});
for await (const event of stream) {
  if (event.type === "model.message") {
    for (const call of event.toolCalls ?? []) {
      calls.set(call.id, call.function.name);
      callArguments.set(call.id, call.function.arguments);
    }
    if (event.content !== undefined && event.content !== null) finalText = messageText(event.content);
  } else if (event.type === "tool.response") {
    responses.set(event.toolCallId, event.content);
  } else if (event.type === "tool.approval_required") {
    throw new Error("read-only research unexpectedly requested human approval");
  }
}

const persistedEvents = await client.sessions.listEvents(sessionId, { limit: 100 });
for (const item of persistedEvents.data) {
  const event = item.event;
  if (event.type === "model.message") {
    for (const call of event.toolCalls ?? []) {
      calls.set(call.id, call.function.name);
      callArguments.set(call.id, call.function.arguments);
    }
    if (finalText === "" && event.content !== undefined && event.content !== null) {
      finalText = messageText(event.content);
    }
  } else if (event.type === "tool.response") responses.set(event.toolCallId, event.content);
}

const calledNames = new Set(calls.values());
const logicalCalls = new Map<string, string>();
for (const [callId, name] of calls) {
  if (requiredTools.has(name)) logicalCalls.set(name, callId);
  if (name === "call_tool") {
    const args = callArguments.get(callId) ?? "";
    for (const nested of [...requiredTools, ...forbiddenTools]) {
      if (!args.includes(nested)) continue;
      if (forbiddenTools.has(nested)) throw new Error(`forbidden tool requested through bridge: ${nested}`);
      logicalCalls.set(nested, callId);
    }
  }
}
for (const name of requiredTools) {
  if (!logicalCalls.has(name)) {
    throw new Error(
      `required tool was not called: ${name}; session=${sessionId}; ` +
      `observed=${[...calledNames].sort().join(",")}; final=${JSON.stringify(finalText.slice(-300))}`,
    );
  }
}
for (const name of calledNames) {
  if (forbiddenTools.has(name) || (!requiredTools.has(name) && !bridgeTools.has(name))) {
    throw new Error(`unexpected tool in read-only evaluation: ${name}`);
  }
}

const evaluationCallId = logicalCalls.get("evaluate_trajectory");
if (!evaluationCallId) throw new Error("evaluate_trajectory response was not observed");
const evaluationResponse = responses.get(evaluationCallId);
if (!evaluationResponse) throw new Error("evaluate_trajectory returned no response");
const evaluation = parseObject(evaluationResponse);
if (evaluation.execution_authority !== false) {
  throw new Error(
    `decision math exposed no explicit false authority; session=${sessionId}; ` +
    `response=${JSON.stringify(evaluationResponse.slice(0, 500))}`,
  );
}
const symbols = object(evaluation.symbols, "evaluation.symbols");
for (const symbol of trajectorySymbols) {
  const result = object(symbols[symbol], `evaluation.symbols.${symbol}`);
  const strategies = object(result.strategies, `${symbol}.strategies`);
  const blockedBy = result.blocked_by;
  if (!Array.isArray(blockedBy)) throw new Error(`${symbol}.blocked_by was not an array`);
  for (const strategy of [
    "momentum", "mean_reversion", "breakout_volume", "news_price_confirmation",
    "rsi_reversion", "macd_trend", "volatility_adjusted_momentum", "regime_ensemble",
  ]) {
    if (!(strategy in strategies)) throw new Error(`${symbol} omitted strategy ${strategy}`);
  }
  object(result.direction_counts, `${symbol}.direction_counts`);
  const newsScoring = object(result.news_scoring, `${symbol}.news_scoring`);
  if (Number(newsScoring.events ?? 0) > 0 && Number(newsScoring.llm_scored ?? 0) < 1) {
    throw new Error(`${symbol} had news but no successful structured LLM score`);
  }
  const sizing = object(result.sizing, `${symbol}.sizing`);
  if (sizing.available !== true || !Number.isInteger(sizing.qty)) {
    throw new Error(`${symbol} did not return a mandate-bounded whole-share quantity`);
  }
}
if (!/(^|\n)ACTION: (PARK|PROPOSE)\s*$/u.test(finalText.trim())) {
  throw new Error(`agent did not emit the bounded ACTION line; tail=${JSON.stringify(finalText.slice(-240))}`);
}

console.log(JSON.stringify({
  passed: true,
  sessionId,
  tools: [...calledNames].sort(),
  symbols: Object.keys(symbols).sort(),
  decision: evaluation.decision,
  researchCandidates: evaluation.research_candidates,
  action: finalText.trim().split("\n").at(-1),
  sandboxCodeUsed: false,
  brokerWriteAttempted: false,
}, null, 2));
