// Runs before the pinned SDK compression worker's message handler.
// The addEvent protocol is pinned/tested with @sentry/replay 11.2.0.
// A failure replaces the recording item; raw input is never logged or compressed.
globalThis.addEventListener("message", event => {
  if (event.data?.method !== "addEvent") return;
  try {
    const recording = JSON.parse(event.data.arg);
    const route = value => {
      try {
        const path = new globalThis.URL(value, "https://sso.invalid").pathname;
        return ["/", "/login", "/register", "/verify-email", "/admin"].includes(path) ? path : "unmatched";
      } catch { return "unmatched"; }
    };
    const numbers = new Set(["type", "source", "timestamp", "id", "parentId", "nextId", "rootId", "x", "y", "top", "left", "width", "height", "timeOffset"]);
    const booleans = new Set(["isSVG", "isShadow", "isShadowHost", "isChecked"]);
    const containers = new Set(["data", "node", "childNodes", "initialOffset", "adds", "removes", "texts", "positions"]);
    const tags = new Set(["html", "head", "body", "div", "span", "main", "header", "nav", "section", "p", "button", "input", "label", "form"]);
    const project = (value, depth = 0) => {
      if (depth > 100 || !value || typeof value !== "object") return {};
      if (Array.isArray(value)) return value.slice(0, 10000).map(item => project(item, depth + 1));
      const clean = {};
      for (const [key, item] of Object.entries(value)) {
        if (numbers.has(key) && typeof item === "number" && Number.isFinite(item)) clean[key] = item;
        else if (booleans.has(key) && typeof item === "boolean") clean[key] = item;
        else if (containers.has(key)) clean[key] = project(item, depth + 1);
        else if (["href", "url", "initialUrl"].includes(key) && typeof item === "string") clean[key] = route(item);
        else if (["textContent", "text", "value"].includes(key) && typeof item === "string") clean[key] = "[Masked]";
        else if (key === "tagName") clean.tagName = tags.has(item) ? item : "div";
        else if (key === "name") clean.name = "html"; // DocumentType only.
        else if (key === "attributes") {
          clean.attributes = {};
          // Block placeholders keep numeric dimensions and the fixed app root.
          for (const dimension of ["rr_width", "rr_height"]) {
            if (/^\d+(?:\.\d+)?px$/.test(String(item?.[dimension]))) clean.attributes[dimension] = item[dimension];
          }
          if (item?.id === "root") clean.attributes.id = "root";
        }
      }
      return clean;
    };
    event.data.arg = JSON.stringify({ ...project(recording), _sso_sanitized: 1 });
  } catch {
    event.data.arg = JSON.stringify({ _sso_sanitized: 1, type: 4, timestamp: Date.now(), data: { href: "unmatched", width: 0, height: 0 } });
  }
});
