"""Tool executor and built-in tools: URL fetch, web search, and file content access."""

from __future__ import annotations

import gzip
import ipaddress
import json
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING, Any, Callable

from baps.models.models import ToolDefinition

if TYPE_CHECKING:
    from baps.state.state import CodingArtifact

_FETCH_TIMEOUT = 10
_MAX_FETCH_BYTES = 50_000
_MAX_SEARCH_BYTES = 100_000


def _is_private_host(host: str) -> bool:
    """Return whether private host."""
    try:
        addr = ipaddress.ip_address(host)
        return addr.is_private or addr.is_loopback or addr.is_link_local
    except ValueError:
        return False  # hostname, not a bare IP — allow


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Represent the _SafeRedirectHandler type."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """Handle redirect request."""
        parsed = urllib.parse.urlparse(newurl)
        if parsed.scheme not in ("http", "https"):
            raise urllib.error.URLError(
                f"redirect to non-http scheme blocked: {newurl}"
            )
        if _is_private_host(parsed.hostname or ""):
            raise urllib.error.URLError(
                f"redirect to private address blocked: {newurl}"
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_SafeRedirectHandler)


def _raw_fetch(url: str, max_bytes: int) -> str:
    """Handle raw fetch."""
    req = urllib.request.Request(
        url, headers={"User-Agent": "baps-research/1.0"}, method="GET"
    )
    with _OPENER.open(req, timeout=_FETCH_TIMEOUT) as resp:
        raw = resp.read(max_bytes)
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return raw.decode("utf-8", errors="replace")


_JS_RENDER_MARKERS = re.compile(
    r'<div[^>]+id=["\'](?:root|app|__next|__nuxt|ember-application)["\']'
    r"|<div[^>]+data-reactroot"
    r"|window\.__INITIAL_STATE__"
    r"|window\.__REDUX_STATE__"
    r"|\bng-version="
    r'|data-server-rendered=["\']false["\']',
    re.IGNORECASE,
)

_MIN_MEANINGFUL_CHARS = 150


def _is_js_rendered(raw_html: str, stripped: str) -> bool:
    """Return True when the page is likely a client-side SPA with no useful server content."""
    if _JS_RENDER_MARKERS.search(raw_html):
        return True
    meaningful = len(stripped.split())
    return meaningful < _MIN_MEANINGFUL_CHARS and len(raw_html) > 2000


def _strip_html(text: str) -> str:
    """Handle strip html."""
    text = re.sub(
        r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE
    )
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


_INJECTION_PATTERNS = re.compile(
    r"(ignore|disregard|forget|override)\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|context|rules?)"
    r"|^[\t ]*system\s*:",
    re.IGNORECASE | re.MULTILINE,
)


def _sanitize_external_content(text: str) -> str:
    """Sanitize and return external content."""
    normalized = unicodedata.normalize("NFKC", text)
    return _INJECTION_PATTERNS.sub("[content removed]", normalized)


def fetch_url(url: str) -> str:
    """Fetch a public HTTP/HTTPS URL and return its text content (HTML stripped, max 50 KB)."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return "fetch_error: only http/https URLs are supported"
    if _is_private_host(parsed.hostname or ""):
        return "fetch_error: private/loopback addresses are not allowed"
    try:
        raw = _raw_fetch(url, max_bytes=_MAX_FETCH_BYTES)
    except urllib.error.URLError as exc:
        return f"fetch_error: {exc}"
    except Exception as exc:
        return f"fetch_error: {exc}"
    if "<html" in raw[:1000].lower() or "<!doctype" in raw[:500].lower():
        stripped = _strip_html(raw)
        if _is_js_rendered(raw, stripped):
            return (
                "fetch_error: page appears to be JavaScript-rendered — "
                "no readable content was returned by the server. "
                "Try a direct API endpoint, raw file URL, RSS feed, or cached version instead."
            )
        return _sanitize_external_content(stripped)
    return _sanitize_external_content(raw)


def web_search(query: str) -> str:
    """Search the web via DuckDuckGo instant answers. Best for CVEs, packages, standards."""
    encoded = urllib.parse.quote_plus(query)
    url = (
        f"https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1&skip_disambig=1"
    )
    try:
        raw = _raw_fetch(url, max_bytes=_MAX_SEARCH_BYTES)
    except Exception as exc:
        return f"search_error: {exc}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return f"search_error: invalid JSON response: {exc}"
    if not isinstance(data, dict):
        return "search_error: unexpected response format"
    parts: list[str] = []
    abstract = data.get("AbstractText")
    if isinstance(abstract, str) and abstract.strip():
        parts.append(f"Summary: {abstract}")
        source = data.get("AbstractURL")
        if isinstance(source, str) and source.startswith("http"):
            parts.append(f"Source: {source}")
    for topic in data.get("RelatedTopics", [])[:5]:
        if not isinstance(topic, dict):
            continue
        text = topic.get("Text")
        if not isinstance(text, str) or not text.strip():
            continue
        line = f"- {text}"
        url = topic.get("FirstURL")
        if isinstance(url, str) and url.startswith("http"):
            line += f"\n  URL: {url}"
        parts.append(line)
    if not parts:
        return (
            "(no results — try fetch_url with a direct URL if you know where to look)"
        )
    return _sanitize_external_content("\n".join(parts))


def fetch_file(path: str, artifact: CodingArtifact) -> str:
    """Return full content of a file in the artifact, or an error listing available paths."""
    files_by_path = {f.path: f for f in artifact.files}
    if path not in files_by_path:
        available = sorted(files_by_path.keys())
        available_str = (
            ", ".join(f"'{p}'" for p in available) if available else "(none)"
        )
        return f"File '{path}' not found in artifact. Available files: {available_str}"
    return files_by_path[path].content


FETCH_FILE_DEFINITION = ToolDefinition(
    name="fetch_file",
    description=(
        "Fetch the full content of a file in the current coding artifact. "
        "Use this when the API surface summary is insufficient for confident gap analysis."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative file path within the artifact",
            },
        },
        "required": ["path"],
    },
)


def build_fetch_file_tool(artifact: CodingArtifact) -> ToolDefinition:
    """Return the fetch_file tool definition (artifact-independent schema)."""
    del artifact
    return FETCH_FILE_DEFINITION


FETCH_URL_DEFINITION = ToolDefinition(
    name="fetch_url",
    description=(
        "Fetch the text content of a public HTTP/HTTPS URL. "
        "HTML is stripped. Max 50 KB. Private/loopback addresses are blocked."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch (http or https only)",
            },
        },
        "required": ["url"],
    },
)

WEB_SEARCH_DEFINITION = ToolDefinition(
    name="web_search",
    description=(
        "Search the web for factual information: CVEs, package details, standards, documentation. "
        "Returns summaries and related URLs. "
        "Follow up with fetch_url to retrieve full page content."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
        },
        "required": ["query"],
    },
)

_DEFAULT_TOOLS: dict[str, tuple[ToolDefinition, Callable[..., str]]] = {
    "fetch_url": (FETCH_URL_DEFINITION, fetch_url),
    "web_search": (WEB_SEARCH_DEFINITION, web_search),
}


class ToolExecutor:
    """Maps tool names to callable implementations and executes them safely."""

    def __init__(
        self,
        adapter_tools: dict[str, Callable[..., str]] | None = None,
    ) -> None:
        """Initialize the instance."""
        self._registry: dict[str, tuple[ToolDefinition, Callable[..., str]]] = {}
        self._adapter_tools: dict[str, Callable[..., str]] = (
            dict(adapter_tools) if adapter_tools else {}
        )

    def register(self, defn: ToolDefinition, fn: Callable[..., str]) -> "ToolExecutor":
        """Handle register."""
        self._registry[defn.name] = (defn, fn)
        return self

    def definitions(self) -> list[ToolDefinition]:
        """Handle definitions."""
        return [defn for defn, _ in self._registry.values()]

    def execute(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Handle execute."""
        entry = self._registry.get(tool_name)
        if entry is not None:
            _, fn = entry
            try:
                return str(fn(**arguments))
            except TypeError as exc:
                return f"tool_error: bad arguments for {tool_name!r}: {exc}"
            except Exception as exc:
                return f"tool_error: {exc}"
        adapter_fn = self._adapter_tools.get(tool_name)
        if adapter_fn is not None:
            try:
                return str(adapter_fn(arguments))
            except Exception as exc:
                return f"tool_error: {exc}"
        return f"tool_error: unknown tool {tool_name!r}"

    def __contains__(self, tool_name: str) -> bool:
        """Return whether the collection contains the given item."""
        return tool_name in self._registry or tool_name in self._adapter_tools


def build_default_tool_executor() -> ToolExecutor:
    """Build and return default tool executor."""
    executor = ToolExecutor()
    for defn, fn in _DEFAULT_TOOLS.values():
        executor.register(defn, fn)
    return executor
