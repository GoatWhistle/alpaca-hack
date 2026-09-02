import { useEffect, useMemo, useState } from "react";
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

export function AgentWorkspace() {
  const [tradingDate, setTradingDate] = useState(newYorkTradingDate);
  const [traderDegraded, setTraderDegraded] = useState(false);
  const [chatDegraded, setChatDegraded] = useState(false);
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
          <TrueForgeUI
            key={tradingDate}
            server={traderServer}
            layout={TraderDayLayout}
            initialSessionId={traderDaySessionId(tradingDate)}
            agentConfig={{ mode: "SingleAgent", name: "mandate-paper-agent" }}
            overrides={{ ThreadListNewButton: HiddenTraderNewChat }}
            theme={{
              preset: "trueforge",
              mode: "dark",
              brand: { name: "Trader days", logo: `${import.meta.env.BASE_URL}agent-mark.svg` },
              tokens: MANDATE_CHAT_TOKENS,
            }}
            onError={() => setTraderDegraded(true)}
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
            <TrueForgeUI
              server={{ type: "trueforge", baseUrl: import.meta.env.BASE_URL }}
              layout={OperatorForkLayout}
              agentConfig={{ mode: "SingleAgent", name: "mandate-operator-agent" }}
              theme={{
                preset: "trueforge",
                mode: "dark",
                brand: { name: "Operator fork", logo: `${import.meta.env.BASE_URL}agent-mark.svg` },
                tokens: MANDATE_CHAT_TOKENS,
              }}
              onError={() => setChatDegraded(true)}
            />
          </div>
          <footer>
            Persistent changes call <code>append_trader_memory</code> and pause for approval.
          </footer>
        </aside>
      </div>
    </main>
  );
}
