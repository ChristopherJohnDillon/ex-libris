// CSV import: preview first, then add.
(() => {
  const {esc, $, JSON_HDR, send} = XL;
  let text = "";
  const list = rows => rows.slice(0, 50).map(r => `<li>${esc(r.title)}${r.authors ? ` <span class="muted">· ${esc(r.authors)}</span>` : ""}</li>`).join("")
    + (rows.length > 50 ? `<li class="muted">…and ${rows.length - 50} more</li>` : "");
  $("#csvfile").addEventListener("change", async e => {
    const f = e.target.files[0]; if (!f) return;
    text = await f.text(); $("#import-err").textContent = "";
    try {
      const p = await send("/api/import", {method: "POST", headers: JSON_HDR, body: JSON.stringify({csv: text, commit: false})});
      $("#preview").innerHTML = `<div class="panel"><p><strong>${p.new.length}</strong> new book${p.new.length === 1 ? "" : "s"},
        ${p.duplicates.length} already on the shelf, ${p.errors.length} row${p.errors.length === 1 ? "" : "s"} skipped.</p>
        <ul>${list(p.new)}</ul>${p.new.length ? `<button class="btn primary" id="go">Add ${p.new.length} book${p.new.length === 1 ? "" : "s"}</button>` : ""}</div>`;
      const go = $("#go");
      if (go) go.addEventListener("click", async () => {
        go.disabled = true;
        const r = await send("/api/import", {method: "POST", headers: JSON_HDR, body: JSON.stringify({csv: text, commit: true})});
        $("#preview").innerHTML = `<p class="panel">Added ${r.new.length - r.errors.filter(x => x.line === null).length} books. <a href="/">Back to the library</a></p>`;
      });
    } catch (err) { $("#import-err").textContent = err.message; }
  });
})();
