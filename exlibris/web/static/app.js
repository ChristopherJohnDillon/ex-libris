// Shared helpers. Everything user- or Open-Library-supplied goes through esc().
window.XL = (() => {
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const $ = (s, root = document) => root.querySelector(s);
  const JSON_HDR = {"Content-Type": "application/json"};
  function initials(title) {
    const words = (title || "").split(/\s+/).filter(w => w && !/^(the|a|an)$/i.test(w));
    return (words.slice(0, 2).map(w => w[0]).join("") || "?").toUpperCase();
  }
  function cover(b, cls = "cover") {
    return b.cover_url ? `<img class="${cls}" src="${esc(b.cover_url)}" data-title="${esc(b.title)}" alt="" loading="lazy">`
                       : `<div class="spine" aria-hidden="true">${esc(initials(b.title))}</div>`;
  }
  async function send(url, opts = {}) {
    const r = await fetch(url, opts);
    if (r.ok) return r.status === 204 ? null : r.json();
    let msg = `Something went wrong (${r.status})`;
    try { const j = await r.json(); if (j.detail) msg = typeof j.detail === "string" ? j.detail : j.detail.map(d => d.msg).join("; "); } catch (e) {}
    throw new Error(msg);
  }
  const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
  const store = {
    get(k, d = null) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} },
  };
  function today() {                                   // local date, not UTC
    const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
    return d.toISOString().slice(0, 10);
  }
  // a broken cover image turns into a spine with initials
  document.addEventListener("error", e => {
    const t = e.target;
    if (!t.classList || !t.classList.contains("cover")) return;
    const d = document.createElement("div"); d.className = "spine"; d.textContent = initials(t.dataset.title);
    t.replaceWith(d);
  }, true);
  async function rooms(datalist) {
    try { const rows = await send("/api/locations"); datalist.innerHTML = rows.map(r => `<option value="${esc(r.name)}">`).join(""); } catch (e) {}
  }
  return {esc, $, JSON_HDR, initials, cover, send, debounce, store, today, rooms};
})();
