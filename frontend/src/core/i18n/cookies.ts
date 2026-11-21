/**
 * Client-side cookie utilities for locale management
 */

const LOCALE_COOKIE_NAME = "locale";

/**
 * Get locale from cookie (client-side)
 */
export function getLocaleFromCookie(): string | null {
  if (typeof document === "undefined") {
    return null;
  }

  const cookies = document.cookie.split(";");
  for (const cookie of cookies) {
    // Split on the first "=" only: a cookie value may contain "=" itself.
    const separator = cookie.indexOf("=");
    if (separator < 0) {
      continue;
    }
    if (cookie.slice(0, separator).trim() !== LOCALE_COOKIE_NAME) {
      continue;
    }
    const value = cookie.slice(separator + 1).trim();
    try {
      return decodeURIComponent(value);
    } catch {
      // A malformed value must not crash locale bootstrap; hand the raw
      // value to normalizeLocale, which falls back to the default locale.
      return value;
    }
  }
  return null;
}

/**
 * Set locale in cookie (client-side)
 */
export function setLocaleInCookie(locale: string): void {
  if (typeof document === "undefined") {
    return;
  }

  // Set cookie with 1 year expiration
  const maxAge = 365 * 24 * 60 * 60; // 1 year in seconds
  document.cookie = `${LOCALE_COOKIE_NAME}=${encodeURIComponent(locale)}; max-age=${maxAge}; path=/; SameSite=Lax`;
}
