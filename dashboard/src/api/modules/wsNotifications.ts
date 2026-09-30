import { getAuthToken } from "../request";
import { getWsUrl } from "../config";

export function buildDashboardNotifyWsUrl(): string {
  return getWsUrl("/notifications/ws");
}

export function createDashboardNotifyWebSocket(): WebSocket {
  const token = getAuthToken();
  const protocols = token ? ["octop.chat", `octop.auth.${token}`] : undefined;
  return new WebSocket(buildDashboardNotifyWsUrl(), protocols);
}
