import { getAuthToken } from "../request";

export function createAuthenticatedWebSocket(url: string): WebSocket {
  const token = getAuthToken();
  const protocols = token ? ["octop.chat", `octop.auth.${token}`] : undefined;
  return new WebSocket(url, protocols);
}
