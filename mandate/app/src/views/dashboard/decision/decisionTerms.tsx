export function decisionSummary(
  toolName: string,
  _args: Record<string, unknown>,
): string {
  return toolName.replaceAll("_", " ");
}
