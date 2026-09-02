import { memo, useCallback, useEffect, useMemo, useState } from "react";
import type {
  AgentStepsCardProps,
  AgentUIServer,
  ThreadComposerAreaShellProps,
  ToolCallCardProps,
  ToolGroupCardProps,
  WelcomeScreenProps,
} from "@truefoundry/trueforge-ui";
import {
  defaultSlots,
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
import type { Snapshot } from "../../lib/api";
import { TradingBookStrip } from "./TradingBookStrip";

const DefaultToolCallCard = defaultSlots.ToolCallCard;
const DefaultToolGroupCard = defaultSlots.ToolGroupCard;
const DefaultAgentStepsCard = defaultSlots.AgentStepsCard;

/**
 * The autonomous stream must show every subagent tool call by default — a
 * collapsed tool row hides the desk's work. The operator can still collapse a
 * card; the choice is local to this override and resets on remount.
 */
function OpenToolCallCard(props: ToolCallCardProps) {
  const [collapsed, setCollapsed] = useState(false);
  return (
    <DefaultToolCallCard
      {...props}
      expanded={props.expanded === true || !collapsed}
      onToggle={() => setCollapsed((value) => !value)}
    />
  );
}

function OpenToolGroupCard(props: ToolGroupCardProps) {
  const [collapsed, setCollapsed] = useState(false);
  return (
    <DefaultToolGroupCard
      {...props}
      expanded={props.expanded === true || !collapsed}
      onToggle={() => setCollapsed((value) => !value)}
    />
  );
}

/** Consecutive runs of tool calls also arrive as a collapsed "steps" group. */
function OpenAgentStepsCard(props: AgentStepsCardProps) {
  const [collapsed, setCollapsed] = useState(false);
  return (
    <DefaultAgentStepsCard
      {...props}
      expanded={props.expanded === true || !collapsed}
      onToggle={() => setCollapsed((value) => !value)}
    />
  );
}

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
  ToolCallCard: OpenToolCallCard,
  ToolGroupCard: OpenToolGroupCard,
  AgentStepsCard: OpenAgentStepsCard,
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
      <TradingBookStrip
        snapshot={snapshot}
        live={snapshot?.source === "live" && !error}
        equity={Number(snapshot?.session.account.equity ?? 0) || 0}
        contextState={contextState}
      />

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
