import { existsSync } from "node:fs";
import { resolve } from "node:path";

export function loadWorkspaceEnv(): void {
  const path = resolve(process.cwd(), "../../.env.local");
  if (existsSync(path)) process.loadEnvFile(path);
}
