import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    // TrueForgeUI is loaded in a lazy route and ships several React peer
    // consumers. Force every chunk through the host React instance; a second
    // dispatcher produces React #321 (invalid hook call) in production.
    dedupe: ["react", "react-dom", "react/jsx-runtime", "react/jsx-dev-runtime"],
  },
  optimizeDeps: {
    include: ["@truefoundry/trueforge-ui", "@assistant-ui/react", "@assistant-ui/core"],
  },
  server: {
    proxy: {
      "/api": process.env.MANDATE_API_PROXY ?? "http://127.0.0.1:8030",
    },
  },
});
