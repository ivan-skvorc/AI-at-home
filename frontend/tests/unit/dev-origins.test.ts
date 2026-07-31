import { describe, expect, test } from "@rstest/core";
import { isCsrfOriginAllowed } from "next/dist/server/app-render/csrf-protection";

import {
  DEFAULT_DEV_ORIGIN_PATTERNS,
  getAllowedDevOrigins,
  parseAllowedDevOrigins,
} from "@/dev-origins";

describe("parseAllowedDevOrigins", () => {
  test("returns an empty list when unset or empty", () => {
    expect(parseAllowedDevOrigins(undefined)).toEqual([]);
    expect(parseAllowedDevOrigins("")).toEqual([]);
    expect(parseAllowedDevOrigins("   ")).toEqual([]);
  });

  test("splits a comma-separated list and trims each entry", () => {
    expect(parseAllowedDevOrigins(" 192.168.1.10 , dev.example.com ")).toEqual([
      "192.168.1.10",
      "dev.example.com",
    ]);
  });

  test("drops empty entries from trailing or doubled commas", () => {
    expect(parseAllowedDevOrigins("a.example,,b.example,")).toEqual([
      "a.example",
      "b.example",
    ]);
  });

  test("reduces a pasted URL to the bare host Next matches on", () => {
    expect(parseAllowedDevOrigins("http://192.168.1.10:2026")).toEqual([
      "192.168.1.10",
    ]);
    expect(parseAllowedDevOrigins("https://dev.example.com/")).toEqual([
      "dev.example.com",
    ]);
    expect(parseAllowedDevOrigins("http://dev.example.com/login?x=1")).toEqual([
      "dev.example.com",
    ]);
  });

  test("preserves wildcard patterns", () => {
    expect(parseAllowedDevOrigins("*.local, *.example.com")).toEqual([
      "*.local",
      "*.example.com",
    ]);
  });

  test("strips the port from a bracketed IPv6 host without mangling the address", () => {
    expect(parseAllowedDevOrigins("[::1]:2026")).toEqual(["::1"]);
    expect(parseAllowedDevOrigins("http://[fe80::1]:3000")).toEqual([
      "fe80::1",
    ]);
  });

  test("leaves a bare IPv6 literal intact", () => {
    // Several colons and no port to strip — treating the last group as a port
    // would corrupt the address.
    expect(parseAllowedDevOrigins("fe80::1")).toEqual(["fe80::1"]);
  });
});

describe("getAllowedDevOrigins", () => {
  test("ships the private-network + Tailscale defaults by default", () => {
    // The fork is meant to be reachable from a phone on the LAN / over Tailscale,
    // so a fresh env (no DEER_FLOW_DEV_ALLOWED_ORIGINS) still allows those hosts.
    expect(getAllowedDevOrigins({})).toEqual([...DEFAULT_DEV_ORIGIN_PATTERNS]);
  });

  test("merges explicit hosts first, then the defaults, de-duplicated", () => {
    const result = getAllowedDevOrigins({
      DEER_FLOW_DEV_ALLOWED_ORIGINS: "dev.example.com, 192.168.*.*",
    });
    // Explicit entries lead, defaults follow, and the "192.168.*.*" that appears
    // in both is kept once (first-seen wins).
    expect(result[0]).toBe("dev.example.com");
    expect(result[1]).toBe("192.168.*.*");
    for (const pattern of DEFAULT_DEV_ORIGIN_PATTERNS) {
      expect(result.filter((host) => host === pattern)).toHaveLength(1);
    }
    expect(result).toContain("100.*.*.*");
    expect(result).toContain("**.ts.net");
  });

  test("strict mode drops the defaults, allowing only explicit hosts", () => {
    expect(
      getAllowedDevOrigins({
        DEER_FLOW_DEV_ALLOWED_ORIGINS: "192.168.1.10",
        DEER_FLOW_DEV_ALLOWED_ORIGINS_STRICT: "1",
      }),
    ).toEqual(["192.168.1.10"]);
  });

  test("strict mode accepts the usual truthy spellings", () => {
    for (const flag of ["1", "true", "TRUE", "yes", "on"]) {
      expect(
        getAllowedDevOrigins({ DEER_FLOW_DEV_ALLOWED_ORIGINS_STRICT: flag }),
      ).toEqual([]);
    }
  });

  test("a non-truthy strict flag keeps the defaults on", () => {
    expect(
      getAllowedDevOrigins({ DEER_FLOW_DEV_ALLOWED_ORIGINS_STRICT: "0" }),
    ).toEqual([...DEFAULT_DEV_ORIGIN_PATTERNS]);
  });
});

describe("Next.js matcher accepts the fork defaults", () => {
  // Prove the patterns actually satisfy Next's own dev-origin matcher
  // (`matchWildcardDomain`), i.e. that these hosts stop getting a 403 on
  // `/_next/*` and the page hydrates. Uses the real matcher, not a copy.
  const allowed = getAllowedDevOrigins({});

  test.each([
    ["100.101.102.103", "Tailscale CGNAT IP"],
    ["192.168.1.50", "home LAN IP"],
    ["10.0.0.5", "private 10/8 IP"],
    ["172.16.4.2", "private 172.16/12 IP"],
    ["myhost.tailnet-name.ts.net", "Tailscale MagicDNS name"],
    ["myhost.ts.net", "short Tailscale MagicDNS name"],
    ["printer.local", "mDNS .local host"],
    ["nas.home.local", "nested mDNS host"],
  ])("allows %s (%s)", (host) => {
    expect(isCsrfOriginAllowed(host, allowed)).toBe(true);
  });

  test.each([
    ["8.8.8.8", "public IP"],
    ["203.0.113.10", "public IP"],
    ["evil.example.com", "arbitrary public host"],
  ])("still rejects %s (%s)", (host) => {
    expect(isCsrfOriginAllowed(host, allowed)).toBe(false);
  });
});
