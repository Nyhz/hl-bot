const ACTIONS = new Set(["launch", "close", "kill", "limits"]);
export function controlAllowed(action: string): boolean {
  return ACTIONS.has(action);
}
