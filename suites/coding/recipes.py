"""Versioned reconstruction tasks over exact real source, not fabricated issues.

Only the host and evaluator read this file. It is NEVER copied into agent images.
Expected holdout observations are obtained from the pinned reference at qualification.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Recipe:
    task_id: str
    project_id: str
    package_root: str
    module: str
    symbol: str
    description: str
    cases: tuple[dict, ...]

    @property
    def relative_file(self):
        return self.module.replace(".", "/") + ".py"


def calls(*arguments):
    return tuple({"args": list(args)} for args in arguments)


RECIPES = (
    Recipe("httpx.primitive-string.v1", "httpx.pinned_001", "httpx", "httpx._utils", "primitive_value_to_str",
           "Restore primitive_value_to_str: booleans use lowercase JSON true/false, None becomes an empty string, "
           "and other primitive values retain their normal string representation. Preserve the module's other behavior.",
           calls((True,), (None,), (False,), (0,), (-7,), (2.5,), ("",), ("already a string",), ("текст",))),
    Recipe("httpx.ipv4-host.v1", "httpx.pinned_001", "httpx", "httpx._utils", "is_ipv4_hostname",
           "Restore IPv4 hostname recognition. Validate the address portion before an optional /suffix. "
           "Return False rather than raising on non-IPv4 values; do not accept IPv6 or domain names. Preserve other utilities.",
           calls(("127.0.0.1",), ("example.org",), ("0.0.0.0",), ("255.255.255.255",), ("256.1.2.3",),
                 ("192.168.1.1/24",), ("::1",), ("1.2.3",), ("01.2.3.4",), ("",))),
    Recipe("requests.unreserved-uri.v1", "requests.pinned_001", "src/requests", "requests.utils", "unquote_unreserved",
           "Restore URI unquoting of RFC 3986 unreserved characters only. Keep reserved/non-ASCII escapes encoded, "
           "reject invalid hexadecimal escapes with InvalidURL, and preserve all unrelated request utilities.",
           calls(("https://example.org/%7Euser",), ("a%2Fb",), ("%41%5a%30%2d%2E%5f%7e",),
                 ("%3f%23%26%3d",), ("%C3%A9",), ("%zz",), ("100%",), ("%",), ("",))),
    Recipe("requests.scheme.v1", "requests.pinned_001", "src/requests", "requests.utils", "prepend_scheme_if_needed",
           "Restore adding a requested URL scheme only when absent. Preserve an existing scheme, user info, "
           "host/port, path, query and fragment, including scheme-relative URLs. Preserve unrelated utilities.",
           calls(("example.org/path", "https"), ("http://example.org", "https"),
                 ("//example.org/p?q=1#f", "https"), ("user:pass@example.org:8080/x", "http"),
                 ("https://example.org:8443", "http"), ("localhost:8000", "http"))),
    Recipe("pluggy.hook-options.v1", "pluggy.pinned_001", "src/pluggy", "pluggy._hooks", "normalize_hookimpl_opts",
           "Restore in-place normalization of hook implementation options. Add missing tryfirst, trylast, wrapper, "
           "hookwrapper and optionalhook as False and specname as None. Preserve explicitly supplied and unrelated keys.",
           ({"mode": "mutate", "args": [{}]}, {"mode": "mutate", "args": [{"tryfirst": True}]},
            {"mode": "mutate", "args": [{"wrapper": True, "specname": "custom", "extra": 7}]},
            {"mode": "mutate", "args": [{"trylast": None, "optionalhook": True}]},
            {"mode": "mutate", "args": [{"tryfirst": False, "trylast": True, "wrapper": False,
                                          "hookwrapper": True, "optionalhook": False, "specname": "x"}]})),
    Recipe("pluggy.signature.v1", "pluggy.pinned_001", "src/pluggy", "pluggy._hooks", "varnames",
           "Restore varnames for functions, bound methods, classes and callable instances. Return required positional "
           "names and positional names with defaults as separate tuples. Ignore keyword-only and variadic arguments "
           "and exclude implicit self on methods. Preserve the surrounding hook implementation.",
           ({"mode": "signature", "signature": "a, b=2", "kind": "function"},
            {"mode": "signature", "signature": "a", "kind": "bound"},
            {"mode": "signature", "signature": "a, /, b=2, *, c=3", "kind": "function"},
            {"mode": "signature", "signature": "*args, **kwargs", "kind": "function"},
            {"mode": "signature", "signature": "a, b=2", "kind": "class"},
            {"mode": "signature", "signature": "x, y=1", "kind": "callable"},
            {"mode": "signature", "signature": "", "kind": "function"})),
)
