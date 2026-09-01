import { TrueForgeUI } from "@truefoundry/trueforge-ui";
import { MANDATE_CHAT_TOKENS } from "./chatTheme";

export function AgentWorkspace() {
  return (
    <section className="agent-workspace" aria-label="MANDATE agent workspace">
      <TrueForgeUI
        server={{ type: "trueforge", baseUrl: "/" }}
        layout="sidebar"
        agentConfig={{ mode: "SingleAgent", name: "mandate-paper-agent" }}
        theme={{
          preset: "trueforge",
          mode: "dark",
          brand: { name: "MANDATE", logo: "/agent-mark.svg" },
          tokens: MANDATE_CHAT_TOKENS,
        }}
      />
    </section>
  );
}
