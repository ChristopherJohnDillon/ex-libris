// The library page: search, add (Open Library lookup), the edit panel; and the
// author page's "More by this author".
(() => {
  const {esc, $, JSON_HDR, cover, send, debounce, store, today, rooms} = XL;
  const page = document.body.dataset.page;

  if (page === "author") {
    const name = document.body.dataset.author, el = $("#more");
    if (!name || !el) return;
    send(`/api/author_works?name=${encodeURIComponent(name)}`).then(works => {
      el.innerHTML = works.length ? works.map(w => `<li><div class="row" style="cursor:default">${cover(w)}<div><div class="t">${esc(w.title)}</div>
        <div class="m">${esc(w.year || "")} ${w.owned ? `<span class="owned">You have this</span>` : ""}</div></div><span></span></div></li>`).join("")
        : `<li class="muted" style="border:0">Open Library lists nothing else.</li>`;
    }).catch(() => { el.innerHTML = `<li class="muted" style="border:0">Couldn't reach Open Library. Try again later.</li>`; });
    return;
  }
  if (page !== "library") return;

  // ---- list ---------------------------------------------------------------
  let seq = 0;
  async function load() {
    const my = ++seq, q = $("#q").value.trim();
    const data = await send(`/api/books?q=${encodeURIComponent(q)}`);
    if (my !== seq) return;
    $("#count").textContent = `${data.total.toLocaleString()} book${data.total === 1 ? "" : "s"}`;
    if (!data.books.length) { $("#books").innerHTML = `<p class="muted">${data.total ? "Nothing matches that search." : ""}</p>`; return; }
    Browse.render(data.books);
  }
  Browse.init({onOpen: id => openEdit(id), authorHref: n => `/author?name=${encodeURIComponent(n)}`});
  $("#q").addEventListener("input", debounce(load, 80));
  document.addEventListener("keydown", e => {
    if (e.key === "/" && $("#edit").hidden && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) { e.preventDefault(); $("#q").focus(); }
  });
  rooms($("#rooms"));

  // ---- add ----------------------------------------------------------------
  let lseq = 0, found = [];
  const row = (b, action) => {
    const meta = [b.year, b.format, b.publisher, b.isbn].filter(Boolean).map(esc).join(", ");
    return `<li><div class="row" style="cursor:default">${cover(b)}<div><div class="t">${esc(b.title)}</div><div class="a">${esc(b.authors)}</div><div class="m">${meta}</div></div>${action}</div></li>`;
  };
  async function lookup() {
    const my = ++lseq, q = $("#lq").value.trim();
    if (q.length < 2) { $("#lookup").innerHTML = ""; return; }
    $("#lookup").innerHTML = `<li class="muted" style="border:0">Searching Open Library…</li>`;
    try {
      found = await send(`/api/lookup?q=${encodeURIComponent(q)}`);
    } catch (e) {
      if (my === lseq) $("#lookup").innerHTML = `<li class="muted" style="border:0">${esc(e.message)}</li>`;
      found = [];
    }
    if (my !== lseq) return;
    const manual = row({title: q, authors: "Not listed? Add it with just this title"}, `<button class="btn" data-manual="1">Add</button>`);
    $("#lookup").innerHTML = found.map((b, i) => row(b, b.owned ? `<span class="owned">On shelf</span>` : `<button class="btn primary" data-i="${i}">Add</button>`)).join("") + manual;
  }
  $("#addloc").value = store.get("xl.room", "");
  $("#addloc").addEventListener("input", e => store.set("xl.room", e.target.value.trim()));
  $("#lq").addEventListener("input", debounce(lookup, 700));
  $("#lq").addEventListener("keydown", e => { if (e.key === "Enter") lookup(); });
  $("#toggle-add").addEventListener("click", () => {
    const panel = $("#add"), open = panel.hidden;
    panel.hidden = !open;
    $("#toggle-add").setAttribute("aria-expanded", open);
    if (open) { if (!$("#lq").value && $("#q").value) { $("#lq").value = $("#q").value; lookup(); } $("#lq").focus(); }
  });
  $("#lookup").addEventListener("click", async e => {
    const btn = e.target.closest("button"); if (!btn) return;
    const book = btn.dataset.manual ? {title: $("#lq").value.trim()} : {...found[+btn.dataset.i]};
    const room = $("#addloc").value.trim();
    if (room) book.location = room;
    btn.disabled = true;
    try { await send("/api/books", {method: "POST", headers: JSON_HDR, body: JSON.stringify(book)}); btn.outerHTML = `<span class="owned">On shelf</span>`; }
    catch (err) { if (/Already/.test(err.message)) btn.outerHTML = `<span class="owned">On shelf</span>`; else { btn.disabled = false; alertErr(err); } }
    load();
  });
  const alertErr = err => { $("#lookup").insertAdjacentHTML("afterbegin", `<li class="err" style="border:0">${esc(err.message)}</li>`); };

  // ---- edit panel -----------------------------------------------------------
  const PANEL = $("#edit"), FORM = $("#editform");
  const FIELDS = ["title", "authors", "year", "edition_year", "pages", "isbn", "format", "publisher", "genre", "series", "series_index",
                  "location", "lent_to", "lent_on", "notes"];
  const NUM = {year: parseInt, edition_year: parseInt, pages: parseInt, series_index: parseFloat};
  let editing = null, opener = null;
  function fill(b) {
    editing = b;
    for (const f of FIELDS) FORM.elements[f].value = b[f] ?? "";
    $("#edit-cover").innerHTML = cover(b);
    $("#edit-err").textContent = "";
    $("#edit-meta").textContent = `Added ${(b.added_at || "").slice(0, 10)}${b.genre_source === "auto" ? " · genre filled automatically" : ""}`;
  }
  async function openEdit(id) {
    opener = document.activeElement;
    try { fill(await send(`/api/books/${id}`)); } catch (e) { return; }
    PANEL.hidden = false; document.body.style.overflow = "hidden"; FORM.elements.title.focus();
  }
  function closeEdit() { PANEL.hidden = true; editing = null; document.body.style.overflow = ""; if (opener && opener.focus) opener.focus(); }
  function changes() {
    const out = {};
    for (const f of FIELDS) {
      let v = FORM.elements[f].value.trim();
      v = v === "" ? null : NUM[f] ? NUM[f](v) : v;
      if (typeof v === "number" && Number.isNaN(v)) throw new Error(`${f.replace("_", " ")} should be a number`);
      if ((editing[f] ?? null) !== v) out[f] = v;
    }
    return out;
  }
  FORM.addEventListener("submit", async e => {
    e.preventDefault();
    try {
      const diff = changes();
      if (Object.keys(diff).length) await send(`/api/books/${editing.id}`, {method: "PATCH", headers: JSON_HDR, body: JSON.stringify(diff)});
      closeEdit(); load(); rooms($("#rooms"));
    } catch (err) { $("#edit-err").textContent = err.message; }
  });
  FORM.elements.lent_to.addEventListener("input", e => {
    if (e.target.value.trim() && !FORM.elements.lent_on.value) FORM.elements.lent_on.value = today();
    if (!e.target.value.trim()) FORM.elements.lent_on.value = "";
  });
  $("#refresh").addEventListener("click", async e => {
    e.target.disabled = true; $("#edit-err").textContent = "";
    try { const typed = changes(); fill(await send(`/api/books/${editing.id}/refresh`, {method: "POST", headers: JSON_HDR}));
          for (const [k, v] of Object.entries(typed)) FORM.elements[k].value = v ?? ""; load(); }
    catch (err) { $("#edit-err").textContent = err.message; }
    e.target.disabled = false;
  });
  $("#coverfile").addEventListener("change", async e => {
    const f = e.target.files[0]; if (!f) return;
    const body = new FormData(); body.append("file", f);
    $("#edit-cover").innerHTML = `<div class="spine">…</div>`;
    try {
      // HX-Request marks it as sent by this page (the server refuses plain cross-site form posts)
      const b = await send(`/api/books/${editing.id}/cover`, {method: "POST", headers: {"HX-Request": "true"}, body});
      editing.cover_url = b.cover_url; $("#edit-cover").innerHTML = cover(b); load();
    } catch (err) { $("#edit-cover").innerHTML = cover(editing); $("#edit-err").textContent = err.message; }
    e.target.value = "";
  });
  $("#remove").addEventListener("click", async () => {
    if (!confirm(`Remove “${editing.title}” from the shelf?`)) return;
    await send(`/api/books/${editing.id}`, {method: "DELETE", headers: JSON_HDR});
    closeEdit(); load();
  });
  PANEL.addEventListener("click", e => { if (e.target === PANEL || e.target.closest("[data-close]")) closeEdit(); });
  document.addEventListener("keydown", e => { if (e.key === "Escape" && !PANEL.hidden) closeEdit(); });

  load().then(() => { const id = +new URLSearchParams(location.search).get("book"); if (id) openEdit(id); });
})();
