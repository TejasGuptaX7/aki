"""Run a Google search and return the first organic result.

Example skill — exec'd via the `run_skill` MCP tool. The handler is given
sync wrappers around the harness primitives plus an `args` dict and an
optional `result` to assign.

Args:
    query (str): the search query (required)
    timeout (float): max seconds to wait for the SERP to render (default 10)

Returns (via `result`):
    {"title": str, "url": str, "snippet": str | None}
"""

q = args.get("query")
if not q:
    raise ValueError("missing 'query' arg")
timeout = float(args.get("timeout", 10))

navigate("https://www.google.com/search?q=" + q.replace(" ", "+"))
wait_for_load(timeout=timeout)
# Defer to JS to find the first organic-result block — selector-fragile by
# design (Google rewrites its SERP frequently). Skills are the right place
# to track these — that's the point of per-agent skills.
js_extract = """
(() => {
  const r = document.querySelector('div#search div[data-hveid] a h3');
  if (!r) return null;
  const a = r.closest('a');
  const card = a && a.closest('[data-hveid]');
  const snippetEl = card && card.querySelector('[data-sncf="1"], .VwiC3b');
  return {
    title: r.innerText || null,
    url: a ? a.href : null,
    snippet: snippetEl ? snippetEl.innerText : null,
  };
})()
"""
first = js(js_extract)
if not first or not first.get("url"):
    raise RuntimeError("no organic result found on the SERP")
result = first
