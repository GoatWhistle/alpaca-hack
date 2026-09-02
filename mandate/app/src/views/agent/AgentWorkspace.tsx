import { useState } from "react";
import { TrueForgeUI } from "@truefoundry/trueforge-ui";
import { MANDATE_CHAT_TOKENS } from "./chatTheme";
import { TraderTimeline } from "./TraderTimeline";

export function AgentWorkspace() {
  const [channel, setChannel] = useState<"trader" | "operator">("trader");
  return (
    <section className="agent-workspace" aria-label="MANDATE agent workspace">
      <nav className="agent-channels" aria-label="Agent channels">
        <button className={channel === "trader" ? "active" : ""} onClick={() => setChannel("trader")}>Trader</button>
        <button className={channel === "operator" ? "active" : ""} onClick={() => setChannel("operator")}>Operator</button>
      </nav>
      <div className="agent-channel-body">
        {channel === "trader" ? <TraderTimeline /> : (
          <TrueForgeUI
            server={{ type: "trueforge", baseUrl: import.meta.env.BASE_URL }}
            layout="sidebar"
            agentConfig={{ mode: "SingleAgent", name: "mandate-operator-agent" }}
            theme={{
              preset: "trueforge",
              mode: "dark",
              brand: { name: "MANDATE Operator", logo: `${import.meta.env.BASE_URL}agent-mark.svg` },
              tokens: MANDATE_CHAT_TOKENS,
            }}
          />
        )}
      </div>
    </section>
  );
}
