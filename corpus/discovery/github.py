"""Read-only acquisition with request/byte limits, no automatic retries or redirects."""
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, HTTPRedirectHandler, build_opener

from benchmark_core.identity import canonical_json, Sha256Digest


class IntakeError(RuntimeError):
    pass


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        raise IntakeError("GITHUB_REDIRECT_REJECTED")


class GitHubReader:
    def __init__(self, token, cas, budgets, *, opener=None, clock=time.monotonic):
        if not isinstance(token, str) or not token.strip():
            raise IntakeError("GITHUB_TOKEN_MISSING")
        self._token, self.cas, self.budgets = token, cas, budgets
        self.opener = opener or build_opener(NoRedirects())
        self.clock, self.deadline = clock, clock() + budgets.api_seconds
        self.requests = 0
        self.receipts = []

    def query(self, document, variables):
        remaining = self.deadline - self.clock()
        if self.requests >= self.budgets.max_api_requests or remaining <= 0:
            raise IntakeError("ACQUISITION_BUDGET_EXHAUSTED")
        body = canonical_json({"query": document, "variables": variables}).encode("utf-8")
        request = Request("https://api.github.com/graphql", data=body, method="POST", headers={
            "Authorization": "Bearer " + self._token, "Content-Type": "application/json",
            "User-Agent": "autonomous-dev-bench-intake/1"})
        self.requests += 1
        try:
            with self.opener.open(request, timeout=min(30, remaining)) as response:
                raw = response.read(self.budgets.max_response_bytes + 1)
        except HTTPError as error:
            code = error.code
            error.close()
            raise IntakeError(f"GITHUB_HTTP_{code}") from None
        except (URLError, OSError, TimeoutError):
            raise IntakeError("GITHUB_TRANSPORT_ERROR") from None
        if len(raw) > self.budgets.max_response_bytes:
            raise IntakeError("GITHUB_RESPONSE_TOO_LARGE")
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError):
            raise IntakeError("GITHUB_INVALID_JSON") from None
        if not isinstance(result, dict) or result.get("errors") or not isinstance(result.get("data"), dict):
            raise IntakeError("GITHUB_GRAPHQL_ERROR")
        data = result["data"]
        if isinstance(data.get("repository"), dict) and data["repository"].get("isPrivate"):
            raise IntakeError("REPOSITORY_BECAME_PRIVATE")
        receipt = self.cas.put_text(canonical_json({"schema": "autobench.github_receipt/v1",
            "query_digest": str(Sha256Digest.of(document)), "variables": variables, "data": data}))
        self.receipts.append(receipt)
        return data, receipt

    def search(self, document, query, limit):
        cursor = None
        seen = set()
        count = 0
        while count < limit:
            data, receipt = self.query(document, {"query": query, "cursor": cursor})
            connection = data.get("search", {})
            nodes = connection.get("nodes")
            page = connection.get("pageInfo")
            if not isinstance(nodes, list) or not isinstance(page, dict):
                raise IntakeError("INVALID_SEARCH_PAGE")
            for node in nodes:
                if isinstance(node, dict) and node.get("id"):
                    yield node, receipt
                    count += 1
                    if count >= limit:
                        return
            if not page.get("hasNextPage"):
                return
            cursor = page.get("endCursor")
            if not cursor or cursor in seen:
                raise IntakeError("INVALID_PAGINATION")
            seen.add(cursor)
