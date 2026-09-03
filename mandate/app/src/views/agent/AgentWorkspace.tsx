import { memo, useCallback, useEffect, useMemo, useState } from "react";
import type {
  AgentUIServer,
  ThreadComposerAreaShellProps,
  WelcomeScreenProps,
} from "@truefoundry/trueforge-ui";
import {
  defaultSlots,
  Thread,
  ThreadContainer,
  ThreadListContainer,
  TrueForgeUI,
  getErrorMessage,
} from "@truefoundry/trueforge-ui";
import { MANDATE_CHAT_TOKENS } from "./chatTheme";
import {
  createTraderChatServer,
  newYorkTradingDate,
  traderDaySessionId,
} from "./traderChatServer";
import type { Snapshot } from "../../lib/api";
import { TradingBookStrip } from "./TradingBookStrip";

/** No composer on a read-only stream: let the log run to the bottom edge. */
function StreamTail({ children, className }: ThreadComposerAreaShellProps) {
  return (
    <div className={`trader-stream-tail ${className ?? ""}`}>
      {children}
    </div>
  );
}

function QuietWelcome({ className }: WelcomeScreenProps) {
  return (
    <div className={`trader-quiet-welcome ${className ?? ""}`}>
      <p>The stream starts with the desk's next autonomous cycle.</p>
    </div>
  );
}

function ForkWelcome({ className }: WelcomeScreenProps) {
  return (
    <div className={`trader-quiet-welcome ${className ?? ""}`}>
      <p>Ask the trader — inspect context, request a memory change.</p>
    </div>
  );
}

function OperatorForkLayout({ className }: { className?: string }) {
  return (
    <div className={`operator-fork-runtime ${className ?? ""}`}>
      <Thread />
    </div>
  );
}

function TraderDayLayout({ className }: { className?: string }) {
  return (
    <div className={`trader-days-layout ${className ?? ""}`}>
      <aside aria-label="Trading days">
        <ThreadListContainer />
      </aside>
      <ThreadContainer composer={null} />
    </div>
  );
}

function HiddenTraderNewChat() {
  return <span hidden />;
}

const TRADER_AGENT_CONFIG = { mode: "SingleAgent", name: "mandate-paper-agent" } as const;
const OPERATOR_AGENT_CONFIG = { mode: "SingleAgent", name: "mandate-operator-agent" } as const;
const OPERATOR_SERVER = { type: "trueforge", baseUrl: import.meta.env.BASE_URL } as const;
const TRADER_OVERRIDES = {
  ThreadListNewButton: HiddenTraderNewChat,
  // The shell slot is typed as a forwardRef component from the SDK's own
  // React types; the trader tail never receives a ref, so a plain function
  // with a slot-type cast is enough.
  ThreadComposerAreaShell: StreamTail as unknown as typeof defaultSlots.ThreadComposerAreaShell,
  WelcomeScreen: QuietWelcome,
};
const OPERATOR_OVERRIDES = {
  WelcomeScreen: ForkWelcome,
};
const TRADER_THEME = {
  preset: "trueforge",
  mode: "dark",
  brand: { name: "Trader days", logo: `${import.meta.env.BASE_URL}agent-mark.svg` },
  tokens: MANDATE_CHAT_TOKENS,
} as const;
const OPERATOR_THEME = {
  preset: "trueforge",
  mode: "dark",
  brand: { name: "Operator fork", logo: `${import.meta.env.BASE_URL}agent-mark.svg` },
  tokens: MANDATE_CHAT_TOKENS,
} as const;
const IGNORE_UI_ERROR = () => undefined;

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function ActiveStrategy({ snapshot }: { snapshot: Snapshot | null }) {
  const strategy = record(snapshot?.autonomy.runtime.active_strategy);
  if (strategy.schema !== "trader.strategy.v1") return null;
  const actions = Array.isArray(strategy.actions)
    ? strategy.actions.map(record).slice(0, 5)
    : [];
  const phase = strategy.market_phase === "next_open" ? "NEXT OPEN" : "LIVE";
  const version = Number(strategy.version) || 1;
  const ready = actions.filter((action) => action.state === "READY").length;
  return (
    <section className="active-strategy" aria-label="Current trader strategy">
      <header>
        <strong>CURRENT STRATEGY · V{version}</strong>
        <span data-status={String(strategy.status ?? "watching")}>{phase} · {ready} READY · {actions.length - ready} WAIT</span>
      </header>
      {actions.length > 0 ? (
        <div className="active-strategy-table-wrap">
          <table>
            <thead><tr><th>State</th><th>Bet</th><th>Instrument</th><th>Size at open</th><th>Entry</th><th>Exit</th></tr></thead>
            <tbody>{actions.map((action, index) => {
              const quantity = Number(action.quantity);
              const notional = Number(action.notional);
              const detail = [
                String(action.thesis ?? ""),
                `Cancel: ${String(action.invalidation ?? "new evidence invalidates the setup")}`,
                Array.isArray(action.blockers) && action.blockers.length > 0
                  ? `Blocked by: ${action.blockers.map(String).join(", ")}`
                  : "",
              ].filter(Boolean).join("\n");
              return (
                <tr key={String(action.candidate_id ?? index)} title={detail}>
                  <td><b data-state={String(action.state)}>{String(action.state ?? "WAIT")}</b></td>
                  <td><strong>{String(action.symbol ?? "—")}</strong> <em data-side={String(action.side)}>{action.side === "NONE" ? "—" : String(action.side)}</em></td>
                  <td>{String(action.instrument ?? "—")}</td>
                  <td>{Number.isFinite(notional) && notional > 0 ? `$${Math.round(notional).toLocaleString()}` : "—"}{Number.isFinite(quantity) && quantity > 0 ? ` · ${quantity} sh eq.` : ""}</td>
                  <td>{String(action.entry ?? "ON GATES")}</td>
                  <td>{String(action.exit ?? "15:50 ET")}</td>
                </tr>
              );
            })}</tbody>
          </table>
        </div>
      ) : <p className="active-strategy-empty">Recalculating exact order sheet…</p>}
    </section>
  );
}

const TraderRuntime = memo(function TraderRuntime({
  server,
  tradingDate,
  onError,
}: {
  server: AgentUIServer;
  tradingDate: string;
  onError: () => void;
}) {
  return (
    <TrueForgeUI
      server={server}
      layout={TraderDayLayout}
      initialSessionId={traderDaySessionId(tradingDate)}
      agentConfig={TRADER_AGENT_CONFIG}
      overrides={TRADER_OVERRIDES}
      theme={TRADER_THEME}
      onError={onError}
    />
  );
});

const OperatorRuntime = memo(function OperatorRuntime({ onError }: { onError: (error: unknown) => void }) {
  return (
    <TrueForgeUI
      server={OPERATOR_SERVER}
      layout={OperatorForkLayout}
      agentConfig={OPERATOR_AGENT_CONFIG}
      overrides={OPERATOR_OVERRIDES}
      theme={OPERATOR_THEME}
      onError={onError}
    />
  );
});

export const AgentWorkspace = memo(function AgentWorkspace({
  snapshot,
  error,
}: {
  snapshot: Snapshot | null;
  error: string | null;
}) {
  const [tradingDate, setTradingDate] = useState(newYorkTradingDate);
  const [operatorError, setOperatorError] = useState<string | null>(null);
  const traderServer = useMemo(
    () => createTraderChatServer(),
    [],
  );

  useEffect(() => {
    const timer = window.setInterval(() => setTradingDate(newYorkTradingDate()), 30_000);
    return () => window.clearInterval(timer);
  }, []);

  const handleOperatorError = useCallback((failure: unknown) => {
    const message = getErrorMessage(failure, "Operator run failed before producing a response");
    setOperatorError(message.length > 320 ? `${message.slice(0, 319)}…` : message);
  }, []);

  return (
    <main id="main-content" className="agent-workspace" aria-label="Trader room" tabIndex={-1}>
      <TradingBookStrip
        snapshot={snapshot}
        live={snapshot?.source === "live" && !error}
        equity={Number(snapshot?.session.account.equity ?? 0) || 0}
      />

      <div className="trader-room-grid">
        <section className="trader-stream-pane" aria-label="Autonomous trader stream">
          <ActiveStrategy snapshot={snapshot} />
          <TraderRuntime
            key={tradingDate}
            server={traderServer}
            tradingDate={tradingDate}
            onError={IGNORE_UI_ERROR}
          />
        </section>

        <aside className="operator-fork-pane" aria-label="Operator context fork">
          <div className="operator-fork-chat">
            {operatorError && (
              <div className="operator-chat-error" role="alert">
                <div>
                  <strong>Operator run failed</strong>
                  <span>{operatorError}</span>
                </div>
                <button type="button" onClick={() => setOperatorError(null)} aria-label="Dismiss operator error">×</button>
              </div>
            )}
            <OperatorRuntime onError={handleOperatorError} />
          </div>
          <footer>
            Persistent changes call <code>append_trader_memory</code> and pause for approval.
          </footer>
        </aside>
      </div>
    </main>
  );
});
