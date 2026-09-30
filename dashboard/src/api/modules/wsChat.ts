import { getAuthToken } from "../request";

export function buildDashboardChatWsUrl(agentId: string): string {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  return `${protocol}://${window.location.host}/api/agents/${agentId}/chat/ws`;
}

export function createDashboardChatWebSocket(agentId: string): WebSocket {
  const token = getAuthToken();
  const protocols = token ? ["octop.chat", `octop.auth.${token}`] : undefined;
  return new WebSocket(buildDashboardChatWsUrl(agentId), protocols);
}
