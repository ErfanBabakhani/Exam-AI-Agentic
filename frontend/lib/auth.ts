const TOKEN_KEY = "zanista.access-token";
const AUTH_EVENT = "zanista-auth-changed";

function emitAuthChanged() {
  if (typeof window === "undefined") {
    return;
  }
  window.dispatchEvent(new CustomEvent(AUTH_EVENT));
}

export function persistAccessToken(token: string) {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(TOKEN_KEY, token);
  emitAuthChanged();
}

export function getAccessToken() {
  if (typeof window === "undefined") {
    return null;
  }
  return window.localStorage.getItem(TOKEN_KEY);
}

export function hasAccessToken() {
  return Boolean(getAccessToken());
}

export function clearAccessToken() {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.removeItem(TOKEN_KEY);
  emitAuthChanged();
}

export function getAuthChangedEventName() {
  return AUTH_EVENT;
}
