/**
 * Hosts allowed to load Next.js dev-server resources (`/_next/*`,
 * `/__nextjs_font/*`, HMR) from an origin other than the one `pnpm dev` was
 * started on.
 *
 * Next.js answers those requests with 403 unless the host is listed, so a dev
 * stack opened on a LAN address or a proxied hostname serves the SSR HTML but
 * never hydrates: the page renders and nothing on it responds.
 *
 * Fork default (matches the passwordless-for-LAN default): this fork is built
 * to be reached from other devices on your own network — a phone on the LAN, or
 * over Tailscale — so `getAllowedDevOrigins()` ships a set of private-network
 * and Tailscale host patterns ON by default, in addition to whatever
 * `DEER_FLOW_DEV_ALLOWED_ORIGINS` adds. Without this, `make dev` opened from a
 * phone shows the shell but no input box and dead buttons (no hydration).
 * Set `DEER_FLOW_DEV_ALLOWED_ORIGINS_STRICT=1` to drop the built-in patterns and
 * allow only the hosts you list explicitly.
 *
 * Dev-only — Next ignores `allowedDevOrigins` in production builds, so this
 * broadening has no effect on `make start` / `make up`.
 */

/**
 * Built-in dev-origin patterns, on by default.
 *
 * Next matches these with `matchWildcardDomain` (see
 * `next/dist/server/app-render/csrf-protection`), which splits both the host
 * and the pattern on `.` and matches segment-by-segment from the right, where
 * `*` is exactly one segment and `**` is one-or-more trailing segments. IPv4
 * literals are dotted, so `*` matches a single octet.
 *
 * Covered:
 *   - RFC 1918 private LAN IPv4 (`10.*`, `172.*`, `192.168.*`) — the addresses a
 *     router hands out, so the server's own LAN IP is allowed.
 *   - Tailscale CGNAT `100.64.0.0/10` via `100.*.*.*` (a superset — harmless for
 *     a dev allowlist) and Tailscale MagicDNS names via `**.ts.net`.
 *   - mDNS `*.local` / `**.local` hostnames.
 *
 * IPv6 (including Tailscale's `fd7a:…` ULA) is colon-delimited and cannot be
 * expressed with these dot-segment patterns; list such a host explicitly in
 * `DEER_FLOW_DEV_ALLOWED_ORIGINS` if you use it.
 *
 * @type {readonly string[]}
 */
export const DEFAULT_DEV_ORIGIN_PATTERNS = Object.freeze([
  "10.*.*.*",
  "172.*.*.*",
  "192.168.*.*",
  "100.*.*.*",
  "**.ts.net",
  "*.local",
  "**.local",
]);

/**
 * Env var that, when truthy, drops {@link DEFAULT_DEV_ORIGIN_PATTERNS} and
 * allows only the explicitly listed hosts.
 */
export const STRICT_DEV_ORIGINS_ENV = "DEER_FLOW_DEV_ALLOWED_ORIGINS_STRICT";

const TRUTHY = new Set(["1", "true", "yes", "on"]);

/**
 * @param {string | undefined} value
 * @returns {boolean}
 */
function isTruthy(value) {
  return TRUTHY.has((value ?? "").trim().toLowerCase());
}

/**
 * Reduce one entry to the bare host `allowedDevOrigins` matches against.
 *
 * Next matches on host alone, so an entry that still carries a scheme, port, or
 * path matches nothing and leaves the caller with the same 403 they were trying
 * to fix. Accept the URL people naturally copy out of the address bar.
 *
 * @param {string} value
 * @returns {string} bare host, or `""` if the entry was empty
 */
function normalizeHost(value) {
  let host = value.trim();
  if (!host) return "";

  host = host.replace(/^[a-z][a-z0-9+.-]*:\/\//i, "");
  host = host.replace(/[/?#].*$/, "");

  const bracketedIpv6 = /^\[([^\]]+)\](?::\d+)?$/.exec(host);
  if (bracketedIpv6) return bracketedIpv6[1];

  // A bare IPv6 literal has several colons and no port to strip; only a single
  // colon can be a `host:port` separator.
  if ((host.match(/:/g) ?? []).length === 1) {
    host = host.replace(/:\d+$/, "");
  }
  return host;
}

/**
 * Parse a comma-separated host list into the shape `allowedDevOrigins` expects.
 *
 * @param {string | undefined} raw
 * @returns {string[]}
 */
export function parseAllowedDevOrigins(raw) {
  return (raw ?? "").split(",").map(normalizeHost).filter(Boolean);
}

/**
 * Read the configured hosts from the environment, merged with the built-in
 * private-network / Tailscale defaults (unless strict mode is set).
 *
 * Explicit `DEER_FLOW_DEV_ALLOWED_ORIGINS` entries come first, then the
 * defaults; duplicates are removed while preserving first-seen order.
 *
 * @param {Record<string, string | undefined>} [env]
 * @returns {string[]}
 */
export function getAllowedDevOrigins(env = process.env) {
  const explicit = parseAllowedDevOrigins(env.DEER_FLOW_DEV_ALLOWED_ORIGINS);
  if (isTruthy(env[STRICT_DEV_ORIGINS_ENV])) {
    return explicit;
  }
  return Array.from(new Set([...explicit, ...DEFAULT_DEV_ORIGIN_PATTERNS]));
}
