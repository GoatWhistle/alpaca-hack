import { useCallback, useState } from "react";
import { Thread, TrueForgeUI } from "@truefoundry/trueforge-ui";
import { MANDATE_CHAT_TOKENS } from "./chatTheme";
import { TraderTimeline } from "./TraderTimeline";

function OperatorForkLayout({ className }: { className?: string }) {
  return (
    <div className={`operator-fork-runtime ${className ?? ""}`}>
      <Thread />
    </div>
  );
}

export function AgentWorkspace() {
  const [timelineState, setTimelineState] = useState<"connecting" | "live" | "degraded">("connecting");
  const [chatDegraded, setChatDegraded] = useState(false);
  const contextState = chatDegraded ? "degraded" : timelineState;
  const handleContextHealth = useCallback((healthy: boolean) => {
    setTimelineState(healthy ? "live" : "degraded");
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
          <TraderTimeline onHealthChange={handleContextHealth} />
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
