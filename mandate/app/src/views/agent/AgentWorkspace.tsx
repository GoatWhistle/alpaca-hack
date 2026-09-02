import { memo, useCallback, useEffect, useMemo, useState } from "react";
import type { AgentUIServer } from "@truefoundry/trueforge-ui";
import {
  Thread,
  ThreadContainer,
  ThreadListContainer,
  TrueForgeUI,
} from "@truefoundry/trueforge-ui";
import { MANDATE_CHAT_TOKENS } from "./chatTheme";
import {
  createTraderChatServer,
  newYorkTradingDate,
  traderDaySessionId,
} from "./traderChatServer";

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
      <aside>
        <span>Trading days</span>
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
const TRADER_OVERRIDES = { ThreadListNewButton: HiddenTraderNewChat };
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

const OperatorRuntime = memo(function OperatorRuntime({ onError }: { onError: () => void }) {
  return (
    <TrueForgeUI
      server={OPERATOR_SERVER}
      layout={OperatorForkLayout}
      agentConfig={OPERATOR_AGENT_CONFIG}
      theme={OPERATOR_THEME}
      onError={onError}
    />
  );
});

export const AgentWorkspace = memo(function AgentWorkspace() {
  const [tradingDate, setTradingDate] = useState(newYorkTradingDate);
  const [traderDegraded, setTraderDegraded] = useState(false);
  const [chatDegraded, setChatDegraded] = useState(false);
  const markTraderDegraded = useCallback(() => setTraderDegraded(true), []);
  const markChatDegraded = useCallback(() => setChatDegraded(true), []);
  const traderServer = useMemo(
    () => createTraderChatServer((healthy) => setTraderDegraded(!healthy)),
    [],
  );
  const contextState = traderDegraded || chatDegraded ? "degraded" : "live";

  useEffect(() => {
    const timer = window.setInterval(() => setTradingDate(newYorkTradingDate()), 30_000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <main id="main-content" className="agent-workspace" aria-label="Trader room" tabIndex={-1}>
      <header className="trader-room-header">
        <div>
          <span className="trader-room-eyebrow">Autonomous paper desk</span>
          <h1>Trader room</h1>
        </div>
        <div className="trader-room-contract" aria-label="Authority contract">
          <span data-state={contextState}><i className="live-dot" />{contextState} context</span>
          <span>advisory fork</span>
        </div>
      </header>

      <div className="trader-room-grid">
        <section className="trader-stream-pane" aria-label="Autonomous trader stream">
          <TraderRuntime
            key={tradingDate}
            server={traderServer}
            tradingDate={tradingDate}
            onError={markTraderDegraded}
          />
        </section>

        <aside className="operator-fork-pane" aria-label="Operator context fork">
          <header>
            <div>
              <span className="fork-label">Context fork</span>
              <strong>Ask the trader</strong>
            </div>
            <span className="fork-policy">inspect context · request memory change</span>
          </header>
          <div className="operator-fork-chat">
            <OperatorRuntime onError={markChatDegraded} />
          </div>
          <footer>
            Persistent changes call <code>append_trader_memory</code> and pause for approval.
          </footer>
        </aside>
      </div>
    </main>
  );
});
