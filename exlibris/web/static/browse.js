// Browse view shared by both apps: cover grid (default) or list, group-by, filter chips.
window.Browse = (() => {
  const {esc, $, cover, store} = XL;
  const PRIVATE = document.body.dataset.private === "1";
  const FACETS = [["genre", "Genre", b => b.genre || null], ["format", "Format", b => b.format || null]]
    .concat(PRIVATE ? [["location", "Room", b => (b.location || "").trim() || null], ["lent", "", b => b.lent_to ? "Lent out" : null]] : []);
  const LAST = ["Unknown author", "No genre yet", "Not in a series", "Year unknown", "Format unknown", "No room"];
  let cfg = {}, books = [];
  const st = Object.assign({view: "covers", group: "", filters: {}}, store.get("xl.browse", {}));
  if (!PRIVATE) { delete st.filters.location; delete st.filters.lent; if (st.group === "location") st.group = ""; }
  const save = () => store.set("xl.browse", st);
  const authorsOf = b => {
    const out = [];
    for (const part of (b.authors || "").split(",").map(s => s.trim()).filter(Boolean)) {
      if (/^(jr|sr)\.?$|^(ii|iii|iv)$/i.test(part) && out.length) out[out.length - 1] += `, ${part}`; else out.push(part);
    }
    return out;
  };
  const seriesNames = new Map();
  const seriesLabel = n => { const k = n.replace(/^(the|a|an)\s+/i, "").trim().toLowerCase(); if (!seriesNames.has(k)) seriesNames.set(k, n); return seriesNames.get(k); };
  function keys(b, by) {
    if (by === "author") { const a = authorsOf(b); return a.length ? a : ["Unknown author"]; }
    if (by === "genre") return [b.genre || "No genre yet"];
    if (by === "series") return [b.series ? seriesLabel(b.series) : "Not in a series"];
    if (by === "decade") return [b.year ? `${Math.floor(b.year / 10) * 10}s` : "Year unknown"];
    if (by === "format") return [b.format || "Format unknown"];
    if (by === "location") return [(b.location || "").trim() || "No room"];
    return [""];
  }
  function gaps(list) {
    const have = new Set(list.map(b => b.series_index).filter(n => Number.isInteger(n) && n > 0));
    if (!have.size) return [];
    const out = [];
    for (let i = 1; i <= Math.max(...have); i++) if (!have.has(i)) out.push(i);
    return out;
  }
  const passes = b => FACETS.every(([k, , get]) => !st.filters[k] || get(b) === st.filters[k]);
  function chips() {
    const parts = [];
    for (const [k, label, get] of FACETS) {
      const counts = new Map();
      books.forEach(b => { const v = get(b); if (v) counts.set(v, (counts.get(v) || 0) + 1); });
      const vals = [...counts.keys()].sort((a, b) => counts.get(b) - counts.get(a));
      if (!vals.length || (vals.length === 1 && !st.filters[k] && !["lent", "location"].includes(k))) continue;
      if (label) parts.push(`<span class="facet">${esc(label)}</span>`);
      vals.slice(0, 16).forEach(v => parts.push(`<button type="button" class="chip" data-f="${k}" data-v="${esc(v)}" aria-pressed="${st.filters[k] === v}">${esc(v)}<span class="n">${counts.get(v)}</span></button>`));
    }
    if (Object.values(st.filters).some(Boolean)) parts.push(`<button type="button" class="chip" data-clear="1">Clear filters</button>`);
    $("#chips").innerHTML = parts.join("");
  }
  function item(b) {
    const meta = [b.year, b.format, b.publisher].filter(Boolean).map(esc).join(", ");
    const tags = [b.genre, PRIVATE && b.lent_to ? `Lent to ${b.lent_to}` : ""].filter(Boolean).map(t => `<span class="tag">${esc(t)}</span>`).join("");
    const ser = b.series ? ` · ${esc(b.series)}${b.series_index != null ? " " + esc(b.series_index) : ""}` : "";
    const open = cfg.href ? `href="${esc(cfg.href(b))}"` : `href="#" data-id="${b.id}" role="button"`;
    if (st.view === "covers")
      return `<li><a class="tile" ${open} aria-label="${esc(b.title)}">${cover(b)}<div class="wt">${esc(b.title)}</div><div class="wa">${esc(b.authors)}</div></a></li>`;
    return `<li><a class="row" ${open}>${cover(b)}<div><div class="t">${esc(b.title)}${tags}</div><div class="a">${esc(b.authors)}${ser}</div><div class="m">${meta}</div></div><svg class="i muted"><use href="#i-chev"/></svg></a></li>`;
  }
  function draw() {
    document.querySelectorAll("[data-view]").forEach(x => x.setAttribute("aria-pressed", x.dataset.view === st.view));
    $("#groupby").value = st.group;
    chips();
    const shown = books.filter(passes);
    $("#shown").textContent = shown.length !== books.length ? `${shown.length} shown` : "";
    const list = xs => `<ul class="${st.view === "covers" ? "wall" : "books"}">${xs.map(item).join("")}</ul>`;
    if (!shown.length) { $("#books").innerHTML = `<p class="muted">Nothing matches.</p>`; return; }
    if (!st.group) { $("#books").innerHTML = list(shown); return; }
    const groups = new Map();
    shown.forEach(b => keys(b, st.group).forEach(k => { if (!groups.has(k)) groups.set(k, []); groups.get(k).push(b); }));
    const last = n => LAST.includes(n) ? 1 : 0;
    const names = [...groups.keys()].sort(st.group === "decade" || st.group === "series"
      ? (a, b) => last(a) - last(b) || a.localeCompare(b)
      : (a, b) => last(a) - last(b) || groups.get(b).length - groups.get(a).length || a.localeCompare(b));
    $("#books").innerHTML = names.map(name => {
      let xs = groups.get(name), extra = "";
      if (st.group === "series" && name !== "Not in a series") {
        xs = xs.slice().sort((a, b) => (a.series_index ?? 1e9) - (b.series_index ?? 1e9));
        const g = gaps(xs);
        if (g.length) extra = `<span class="gaps">missing ${g.slice(0, 12).join(", ")}</span>`;
      }
      const title = st.group === "author" && name !== "Unknown author" && cfg.authorHref ? `<a href="${esc(cfg.authorHref(name))}">${esc(name)}</a>` : esc(name);
      return `<h3 class="group-h">${title}<span class="n">${xs.length}</span>${extra}</h3>${list(xs)}`;
    }).join("");
  }
  function init(c) {
    cfg = c;
    $("#browse-controls").addEventListener("click", e => { const v = e.target.closest("[data-view]"); if (v) { st.view = v.dataset.view; save(); draw(); } });
    $("#groupby").addEventListener("change", e => { st.group = e.target.value; save(); draw(); });
    $("#chips").addEventListener("click", e => {
      const c = e.target.closest(".chip"); if (!c) return;
      if (c.dataset.clear) st.filters = {}; else st.filters[c.dataset.f] = st.filters[c.dataset.f] === c.dataset.v ? null : c.dataset.v;
      save(); draw();
    });
    if (cfg.onOpen) $("#books").addEventListener("click", e => {
      const a = e.target.closest("[data-id]"); if (!a) return;
      e.preventDefault(); cfg.onOpen(+a.dataset.id);
    });
  }
  return {init, render: xs => { books = xs; draw(); }, authorsOf};
})();
