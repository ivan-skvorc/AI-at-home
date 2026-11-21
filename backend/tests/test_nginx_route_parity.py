"""The three nginx configs route every path the same way.

``docker/nginx/nginx.conf`` is the reference. The local-dev config and the Helm
ConfigMap must declare the same ``location`` blocks, in the same order (nginx
takes the first matching regex), with the same directives. The differences
that are known are listed below with their reasons. A difference that is not
listed fails, and so does a listed one that is gone, so the list cannot go
stale.

Two things differ by deployment and are left out of the comparison: the
upstream a block proxies to (``proxy_pass`` and the ``set $..._upstream``
that feeds it), and where ``proxy_buffering``/``proxy_cache`` are declared,
which is resolved through nginx's server-to-location inheritance.
"""

from __future__ import annotations

import re

import pytest
from support.nginx_conf import NGINX_CONFIGS, read_config

REFERENCE, LOCAL, HELM = NGINX_CONFIGS

# The same route under another path: (config, reference selector) -> selector.
RENAMED = {
    # Local dev serves the API docs under /api/, Docker and Helm at the root.
    # Unifying them changes a public URL.
    (LOCAL, "/docs"): "/api/docs",
    (LOCAL, "/redoc"): "/api/redoc",
}

# Routes only one side declares.
ONLY_IN_REFERENCE = {
    LOCAL: {"/api/sandboxes"},  # the provisioner runs only in the Docker and Kubernetes stacks
}
ONLY_IN_CONFIG = {
    HELM: {"= /nginx-health"},  # static Kubernetes liveness probe, independent of the Gateway
}

_FORWARDED_PROTO = "proxy_set_header X-Forwarded-Proto $forwarded_proto"

# Directive differences: (config, selector) -> (only in the reference, only in the config).
# "*" applies to every shared route of that config.
DIRECTIVE_DIFFERENCES = {
    # Drift: the local config has no $forwarded_proto map, so behind a
    # TLS-terminating proxy the Gateway sees http instead of https.
    (LOCAL, "*"): ({_FORWARDED_PROTO}, {"proxy_set_header X-Forwarded-Proto $scheme"}),
    # proxy_cache is off by nginx's default. Request buffering is off because a
    # local nginx runs as the developer, who may not own nginx's temp paths.
    (LOCAL, "/"): ({"proxy_cache off"}, {"proxy_request_buffering off"}),
    # nginx passes Set-Cookie by default; the directive is a no-op.
    (LOCAL, "/api/"): (set(), {"proxy_pass_header Set-Cookie"}),
    # Drift: Helm has no $connection_upgrade map and marks every frontend
    # request as an upgrade.
    (HELM, "/"): ({"proxy_set_header Connection $connection_upgrade"}, {"proxy_set_header Connection 'upgrade'"}),
    # Drift: Helm keeps the 600s read timeout on the Live browser stream but
    # not the connect and send timeouts.
    (HELM, "~ ^/api/threads/[^/]+/browser/stream"): ({"proxy_connect_timeout 600s", "proxy_send_timeout 600s"}, set()),
}

_LOCATION = re.compile(r"^[ \t]*location\s+(?:(=|~\*?|\^~)\s+)?(\S+)\s*\{", re.M)
_COMMENT = re.compile(r"#[^\n]*")
_DEPLOYMENT_UPSTREAM = re.compile(r"^(proxy_pass|set \$\w+_upstream) ")
_INHERITED = ("proxy_buffering", "proxy_cache")


def _block_end(text: str, open_brace: int) -> int:
    depth = 0
    for index in range(open_brace, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    raise AssertionError("unbalanced braces")


def _routes(path: str) -> list[tuple[str, frozenset[str]]]:
    """Each location's selector and its effective, deployment-neutral directives."""
    text = _COMMENT.sub("", read_config(path))
    blocks: list[tuple[str, str]] = []
    outside: list[str] = []
    last = 0
    for match in _LOCATION.finditer(text):
        modifier, path_pattern = match.groups()
        end = _block_end(text, match.end() - 1)
        body = text[match.end() : end]
        assert "{" not in body, f"{path}: nested block in location {path_pattern}"
        blocks.append((f"{modifier} {path_pattern}" if modifier else path_pattern, body))
        outside.append(text[last : match.start()])
        last = end + 1
    outside.append(text[last:])
    server_level = dict(re.findall(r"^\s*(" + "|".join(_INHERITED) + r")\s+([^;]+);", "".join(outside), re.M))

    routes = []
    for selector, body in blocks:
        directives = {" ".join(part.split()) for part in body.split(";") if part.strip()}
        directives = {directive for directive in directives if not _DEPLOYMENT_UPSTREAM.match(directive)}
        declared = {directive.split()[0] for directive in directives}
        directives |= {f"{name} {value.strip()}" for name, value in server_level.items() if name not in declared}
        routes.append((selector, frozenset(directives)))
    return routes


def _reference_selectors_as(config: str) -> list[str]:
    selectors = [selector for selector, _ in _routes(REFERENCE) if selector not in ONLY_IN_REFERENCE.get(config, set())]
    return [RENAMED.get((config, selector), selector) for selector in selectors]


def _shared_routes(config: str):
    """Yield (selector, reference directives, config directives) per shared route."""
    reference = dict(_routes(REFERENCE))
    renamed_back = {renamed: original for (cfg, original), renamed in RENAMED.items() if cfg == config}
    for selector, directives in _routes(config):
        original = renamed_back.get(selector, selector)
        if original in reference:
            yield selector, reference[original], directives


@pytest.mark.parametrize("config", [LOCAL, HELM])
def test_routes_appear_in_the_reference_order(config: str) -> None:
    selectors = [selector for selector, _ in _routes(config) if selector not in ONLY_IN_CONFIG.get(config, set())]
    assert selectors == _reference_selectors_as(config)


@pytest.mark.parametrize("config", [LOCAL, HELM])
def test_shared_routes_carry_the_same_directives(config: str) -> None:
    wide_reference, wide_config = DIRECTIVE_DIFFERENCES.get((config, "*"), (set(), set()))
    found = {}
    for selector, reference, directives in _shared_routes(config):
        only_reference = reference - directives - wide_reference
        only_config = directives - reference - wide_config
        if only_reference or only_config:
            found[selector] = (only_reference, only_config)

    expected = {selector: diff for (cfg, selector), diff in DIRECTIVE_DIFFERENCES.items() if cfg == config and selector != "*"}
    assert found == expected


@pytest.mark.parametrize("config", [LOCAL, HELM])
def test_config_wide_differences_hold_on_every_shared_route(config: str) -> None:
    # A "*" entry that no longer describes every route would hide a partial fix.
    wide_reference, wide_config = DIRECTIVE_DIFFERENCES.get((config, "*"), (set(), set()))
    for selector, reference, directives in _shared_routes(config):
        assert wide_reference <= reference - directives, selector
        assert wide_config <= directives - reference, selector
