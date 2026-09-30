// The wishlist page: your list (or someone else's, or everyone's), notes saved as
// you type, Got it, and an Open Library lookup to add more.
(() => {
  const {esc, $, JSON_HDR, cover, send, debounce, store, rooms} = XL;
  const ME = document.body.dataset.me || "", PEOPLE = JSON.parse(document.body.dataset.people || "[]");
  let who = new URLSearchParams(location.search).get("who");
  if (!ME || !(who === "*" || PEOPLE.includes(who))) who = ME;
  let wishes = [], found = [], lseq = 0;
  const addTo = () => who === "*" ? ME : who;
  const meta = b => [b.year, b.format, b.publisher, b.isbn].filter(Boolean).map(esc).join(", ");

  function setWho(w) {
    who = w;
    document.querySelectorAll("[data-who]").forEach(b => b.setAttribute("aria-pressed", b.dataset.who === w));
    $("#h").textContent = !ME ? "Wishlist" : w === "*" ? "Everyone's wishlists" : w === ME ? "Your wishlist" : `${w}'s wishlist`;
    if (ME) history.replaceState(null, "", w === ME ? location.pathname : `?who=${encodeURIComponent(w)}`);
    load();
  }
  $("#people")?.addEventListener("click", e => { const b = e.target.closest("[data-who]"); if (b) setWho(b.dataset.who); });

  // ---- the list -------------------------------------------------------------
  function wishHtml(w) {
    const authors = (w.authors || "").split(",").map(a => a.trim()).filter(Boolean)
      .map(a => `<a href="/author?name=${encodeURIComponent(a)}">${esc(a)}</a>`).join(", ");
    const whose = who === "*" && w.owner ? ` <span class="tag wish-tag">${esc(w.owner === ME ? "You" : w.owner)}</span>` : "";
    return `<li data-id="${w.id}"><div class="row" style="cursor:default;align-items:start">${cover(w)}<div>
      <div class="t">${esc(w.title)}${whose}</div><div class="a">${authors}</div>
      <div class="m">${meta(w) || "Any edition"} · wished ${esc((w.added_at || "").slice(0, 10))}</div>
      <textarea data-notes aria-label="Notes on ${esc(w.title)}" placeholder="Notes: who recommended it, where you saw it, price, present idea…">${esc(w.notes)}</textarea>
      <div class="m" data-saved></div></div>
      <div class="acts"><button class="btn got" data-do="got" title="Move it onto the shelf">Got it</button>
        <button class="btn quiet" data-do="del" aria-label="Remove from the wishlist"><svg class="i"><use href="#i-close"/></svg></button></div></div></li>`;
  }
  function render() {
    const q = $("#q").value.trim().toLowerCase();
    const rows = q ? wishes.filter(w => [w.title, w.authors, w.isbn, w.notes].some(v => (v || "").toLowerCase().includes(q))) : wishes;
    $("#count").textContent = `${wishes.length} wished for`;
    $("#wishes").innerHTML = rows.length ? rows.map(wishHtml).join("")
      : `<li class="muted" style="border:0;padding:16px 0">${wishes.length ? "Nothing on the wishlist matches." : "Nothing wished for yet. Use Wish for a book, or scan a barcode in a shop."}</li>`;
  }
  async function load() {
    const w = who;
    const rows = await send(`/api/wishlist?who=${encodeURIComponent(w)}`);
    if (w !== who) return;
    wishes = rows; render();
  }
  const saveNotes = debounce(async (id, ta) => {
    const out = ta.closest("li").querySelector("[data-saved]");
    try {
      Object.assign(wishes.find(x => x.id === id) || {}, await send(`/api/wishlist/${id}`, {method: "PATCH", headers: JSON_HDR, body: JSON.stringify({notes: ta.value})}));
      out.textContent = "Saved";
    } catch (err) { out.textContent = err.message; }
  }, 600);
  $("#wishes").addEventListener("input", e => {
    if (!e.target.matches("[data-notes]")) return;
    const li = e.target.closest("li");
    li.querySelector("[data-saved]").textContent = "…";
    saveNotes(+li.dataset.id, e.target);
  });
  $("#wishes").addEventListener("click", async e => {
    const btn = e.target.closest("[data-do]");
    if (!btn) return;
    const li = btn.closest("li"), id = +li.dataset.id, w = wishes.find(x => x.id === id);
    try {
      if (btn.dataset.do === "del") {
        if (!confirm(`Take “${w.title}” off the wishlist?`)) return;
        await send(`/api/wishlist/${id}`, {method: "DELETE", headers: JSON_HDR});
        wishes = wishes.filter(x => x.id !== id); render();
      }
      if (btn.dataset.do === "got") {
        btn.disabled = true;
        const r = await send(`/api/wishlist/${id}/got`, {method: "POST", headers: JSON_HDR, body: JSON.stringify({location: $("#loc").value.trim()})});
        wishes = wishes.filter(x => x.id !== id); render();
        $("#count").innerHTML = `${esc(r.already ? `“${w.title}” was already on the shelf` : `“${w.title}” is on the shelf now`)} · <a href="/?book=${r.book.id}">open it</a>`;
      }
    } catch (err) { btn.disabled = false; li.querySelector("[data-saved]").textContent = err.message; }
  });
  $("#q").addEventListener("input", debounce(render, 60));

  // ---- lookup ---------------------------------------------------------------
  function state(b, i) {
    if (b.wished) return `<span class="wished">On wishlist</span>`;
    if (b.owned && b.isbn) return `<span class="owned">On shelf</span>`;
    return `<button class="btn" data-i="${i}">Wish</button>`;
  }
  const row = (b, note, action) => `<li><div class="row" style="cursor:default">${cover(b)}<div><div class="t">${esc(b.title)}</div><div class="a">${esc(b.authors)}</div><div class="m">${meta(b)}</div>${note}</div>${action}</div></li>`;
  async function lookup() {
    const my = ++lseq, q = $("#lq").value.trim();
    if (q.length < 2) { $("#lookup").innerHTML = ""; return; }
    $("#lookup").innerHTML = `<li class="muted" style="border:0">Searching Open Library…</li>`;
    try { found = await send(`/api/lookup?q=${encodeURIComponent(q)}`); }
    catch (e) { if (my === lseq) $("#lookup").innerHTML = `<li class="muted" style="border:0">${esc(e.message)}</li>`; return; }
    if (my !== lseq) return;
    const note = b => b.owned && !b.isbn ? `<div class="m wished">You have a copy of this already</div>` : b.other_edition ? `<div class="m wished">You have another edition</div>` : "";
    $("#lookup").innerHTML = found.map((b, i) => row(b, note(b), state(b, i))).join("")
      + row({title: q, authors: "Not listed? Wish for it with just this title"}, "", `<button class="btn" data-manual="1">Wish</button>`);
  }
  $("#lookup").addEventListener("click", async e => {
    const btn = e.target.closest("button");
    if (!btn) return;
    const b = btn.dataset.manual ? {title: $("#lq").value.trim()} : found[+btn.dataset.i];
    btn.disabled = true;
    try {
      const w = await send("/api/wishlist", {method: "POST", headers: JSON_HDR, body: JSON.stringify({...b, owner: addTo()})});
      btn.outerHTML = `<span class="wished">On wishlist</span>`;
      if (who === "*" || w.owner === who) { wishes.unshift(w); render(); $(`#wishes li[data-id="${w.id}"] textarea`)?.focus(); }
    } catch (err) { btn.outerHTML = `<span class="m">${esc(err.message)}</span>`; }
  });
  $("#toggle-add").addEventListener("click", () => {
    const panel = $("#add"), open = panel.hidden;
    panel.hidden = !open; $("#toggle-add").setAttribute("aria-expanded", open);
    if (open) $("#lq").focus();
  });
  $("#lq").addEventListener("input", debounce(lookup, 700));
  $("#lq").addEventListener("keydown", e => { if (e.key === "Enter") lookup(); });

  // the room a book goes in when you get it: shared with the library page and the scanner
  $("#loc").value = store.get("xl.room", "");
  $("#loc").addEventListener("input", e => store.set("xl.room", e.target.value.trim()));
  rooms($("#rooms"));
  setWho(who);
})();
