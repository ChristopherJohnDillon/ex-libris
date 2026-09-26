// The public view: search + browse, read-only.
(() => {
  const {$, send, debounce} = XL;
  let seq = 0;
  Browse.init({href: b => `/book/${b.id}`, authorHref: n => `/author?name=${encodeURIComponent(n)}`});
  async function load() {
    const my = ++seq, q = $("#q").value.trim();
    const data = await send(`/api/books?q=${encodeURIComponent(q)}`);
    if (my !== seq) return;
    $("#count").textContent = `${data.total.toLocaleString()} book${data.total === 1 ? "" : "s"}`;
    if (!data.books.length) { $("#books").innerHTML = `<p class="muted">${data.total ? "Nothing matches that search." : "No books yet."}</p>`; return; }
    Browse.render(data.books);
  }
  $("#q").addEventListener("input", debounce(load, 100));
  load();
})();
