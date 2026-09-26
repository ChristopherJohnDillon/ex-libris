// Phone barcode scanner. Native BarcodeDetector where the browser has it
// (Android Chrome), otherwise ZXing (iPhone Safari). Book barcodes only (ISBN-13).
(() => {
  const {esc, $, JSON_HDR, cover, send, store, rooms} = XL;
  const video = $("#video"), cam = $("#cam"), card = $("#card"), verdict = $("#verdict");
  let stream = null, detector = null, reader = null, busy = false, running = false, last = {code: "", at: 0};
  const say = t => { $("#msg").textContent = t; };
  const room = () => $("#loc").value.trim();
  const added = t => `Added${room() ? ` to ${room()}` : ""}: ${t}`;

  // ---- mode + settings ------------------------------------------------------
  const params = new URLSearchParams(location.search);
  let mode = params.get("mode") || store.get("xl.mode", "add");
  if (!["check", "add"].includes(mode)) mode = "add";
  function setMode(m) {
    mode = m; document.body.classList.toggle("check", m === "check");
    document.querySelectorAll("[data-mode]").forEach(b => b.setAttribute("aria-pressed", b.dataset.mode === m));
    store.set("xl.mode", m); verdict.hidden = true;
  }
  document.querySelector(".seg").addEventListener("click", e => { const b = e.target.closest("[data-mode]"); if (b) { setMode(b.dataset.mode); resume(); } });
  $("#auto").checked = store.get("xl.auto", false);
  $("#auto").addEventListener("change", e => store.set("xl.auto", e.target.checked));
  $("#loc").value = store.get("xl.room", "");
  $("#loc").addEventListener("input", () => store.set("xl.room", room()));
  $("#locclear").addEventListener("click", () => { $("#loc").value = ""; store.set("xl.room", ""); });
  rooms($("#rooms"));

  // ---- ISBN checks ----------------------------------------------------------
  function isIsbn13(s) {
    if (!/^97[89]\d{10}$/.test(s)) return false;
    let sum = 0; for (let i = 0; i < 13; i++) sum += +s[i] * (i % 2 ? 3 : 1);
    return sum % 10 === 0;
  }
  function normalise(raw) {
    const s = String(raw || "").replace(/[\s-]/g, "").toUpperCase();
    if (isIsbn13(s)) return s;
    if (/^\d{9}[\dX]$/.test(s)) {
      let sum = 0; for (let i = 0; i < 10; i++) sum += (s[i] === "X" ? 10 : +s[i]) * (10 - i);
      if (sum % 11) return null;
      const b = "978" + s.slice(0, 9); let t = 0; for (let i = 0; i < 12; i++) t += +b[i] * (i % 2 ? 3 : 1);
      return b + ((10 - t % 10) % 10);
    }
    return null;
  }

  // ---- camera ---------------------------------------------------------------
  async function makeDecoder() {
    if ("BarcodeDetector" in window) {
      try { if ((await BarcodeDetector.getSupportedFormats()).includes("ean_13")) { detector = new BarcodeDetector({formats: ["ean_13"]}); return; } } catch (e) {}
    }
    if (!window.ZXing) throw new Error("scanner library didn't load");
    const hints = new Map();
    hints.set(ZXing.DecodeHintType.POSSIBLE_FORMATS, [ZXing.BarcodeFormat.EAN_13]);
    hints.set(ZXing.DecodeHintType.TRY_HARDER, true);
    reader = new ZXing.MultiFormatReader(); reader.setHints(hints);
  }
  const canvas = document.createElement("canvas"), ctx = canvas.getContext("2d", {willReadFrequently: true});
  async function decodeFrame() {
    if (detector) { const f = await detector.detect(video); return f.length ? f[0].rawValue : null; }
    const vw = video.videoWidth, vh = video.videoHeight; if (!vw) return null;
    const sy = Math.round(vh * .25), sh = Math.round(vh * .5), scale = Math.min(1, 1000 / vw);
    canvas.width = Math.round(vw * scale); canvas.height = Math.round(sh * scale);
    ctx.drawImage(video, 0, sy, vw, sh, 0, 0, canvas.width, canvas.height);
    try { return reader.decodeWithState(new ZXing.BinaryBitmap(new ZXing.HybridBinarizer(new ZXing.HTMLCanvasElementLuminanceSource(canvas)))).getText(); }
    catch (e) { return null; } finally { reader.reset(); }
  }
  async function loop() {
    if (!running) return;
    if (!busy && video.readyState >= 2) { let code = null; try { code = await decodeFrame(); } catch (e) {} if (code) onCode(code); }
    setTimeout(loop, detector ? 80 : 150);
  }
  async function start() {
    $("#start").hidden = true; say("Starting camera…");
    try {
      if (!detector && !reader) await makeDecoder();
      stream = await navigator.mediaDevices.getUserMedia({audio: false, video: {facingMode: {ideal: "environment"}, width: {ideal: 1920}, height: {ideal: 1080}}});
      video.srcObject = stream; await video.play();
      try { await stream.getVideoTracks()[0].applyConstraints({advanced: [{focusMode: "continuous"}]}); } catch (e) {}
      running = true; say("Point at the barcode on the back of a book"); loop();
    } catch (e) {
      stop(); $("#start").hidden = false;
      say(e && e.name === "NotAllowedError" ? "Camera blocked — allow it in the browser's settings, or type the ISBN below." : "Couldn't start the camera. Type the ISBN below instead.");
    }
  }
  function stop() { running = false; if (stream) stream.getTracks().forEach(t => t.stop()); stream = null; }
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) { if (running) { stop(); cam.dataset.resume = "1"; } }
    else if (cam.dataset.resume) { delete cam.dataset.resume; start(); }
  });
  $("#startbtn").addEventListener("click", start);

  // ---- a scanned (or typed) ISBN ----------------------------------------------
  function onCode(raw) {
    const now = Date.now();
    if (raw === last.code && now - last.at < 4000) return;
    last = {code: raw, at: now};
    const isbn = normalise(raw);
    if (!isbn) { say("That barcode isn't a book ISBN"); return; }
    cam.classList.add("hit"); setTimeout(() => cam.classList.remove("hit"), 400);
    if (navigator.vibrate) navigator.vibrate(60);
    handle(isbn);
  }
  function resume(text) { card.hidden = true; card.innerHTML = ""; verdict.hidden = true; busy = false; say(text || "Point at the barcode on the back of a book"); }
  async function add(book) {
    if (room() && !book.location) book = {...book, location: room()};
    try {
      const b = await send("/api/books", {method: "POST", headers: JSON_HDR, body: JSON.stringify(book)});
      $("#loghead").hidden = false;
      $("#log").insertAdjacentHTML("afterbegin", `<li><div class="row" style="cursor:default">${cover(b)}<div><div class="t">${esc(b.title)}</div><div class="a">${esc(b.authors)}</div></div><span></span></div></li>`);
      return "added";
    } catch (e) { return /Already/.test(e.message) ? "owned" : "failed"; }
  }
  // an edition is told apart by its printing, so show that year (the work's first year is elsewhere)
  const line = b => [b.format, b.edition_year || b.year, b.publisher].filter(Boolean).map(esc).join(", ") + (b.location ? ` · ${esc(b.location)}` : "");
  async function check(isbn) {
    busy = true; say(`ISBN ${isbn} — checking…`);
    let r; try { r = await send(`/api/own/${encodeURIComponent(isbn)}`); } catch (e) { resume("Couldn't check that one. Try again."); return; }
    const next = `<button class="btn" data-do="next">Scan next</button>`;
    if (r.answer === "yes") {
      verdict.className = "verdict yes";
      verdict.innerHTML = `<div class="big">Yes, you have this edition</div><div class="t" style="margin-top:6px">${esc(r.this[0].title)}</div><div class="m">${line(r.this[0])}</div><div class="bar" style="margin-top:12px">${next}</div>`;
    } else if (r.answer === "other") {
      verdict.className = "verdict other";
      verdict.innerHTML = `<div class="big">You have a different edition</div><div class="t" style="margin-top:6px">${esc(r.found.title)}</div>
        <div class="m">This one: ${line(r.found) || "edition details unknown"}</div><ul>${r.others.map(o => `<li>You have: ${line(o) || esc(o.title)}</li>`).join("")}</ul>
        <div class="bar" style="margin-top:12px"><button class="btn" data-do="add">Add this edition too</button>${next}</div>`;
    } else {
      verdict.className = "verdict";
      const f = r.found;
      verdict.innerHTML = `<div class="big">Not on your shelf</div>${f ? `<div class="t" style="margin-top:6px">${esc(f.title)}</div><div class="m">${line(f)}</div>` : ""}
        ${r.unsure ? `<p class="m">Open Library didn't answer, so other editions weren't checked.</p>` : ""}
        <div class="bar" style="margin-top:12px">${f ? `<button class="btn primary" data-do="add">Add it</button>` : ""}${next}</div>`;
    }
    verdict.hidden = false;
    say(r.answer === "yes" ? "On your shelf" : r.answer === "other" ? "Another edition is on your shelf" : "Not on your shelf");
    verdict.onclick = async e => {
      const act = e.target.closest("[data-do]")?.dataset.do;
      if (act === "next") resume();
      if (act === "add") { e.target.disabled = true; const res = await add({...r.found, isbn}); resume(res === "added" ? added(r.found.title) : res === "owned" ? "Already on the shelf" : "Couldn't add that one."); }
    };
  }
  function showCard(html, onclick) { card.innerHTML = html; card.hidden = false; card.onclick = onclick; }
  async function handle(isbn) {
    if (mode === "check") return check(isbn);
    busy = true; say(`ISBN ${isbn} — looking it up…`);
    let rows;
    try { rows = await send(`/api/lookup?q=${encodeURIComponent(isbn)}`); } catch (e) { resume(e.message); return; }
    const b = rows[0];
    if (!b) {
      showCard(`<div class="t">Not on Open Library</div><div class="m">ISBN ${esc(isbn)}</div><input id="mtitle" placeholder="Title" style="width:100%;margin-top:8px">
        <div class="bar" style="margin-top:10px"><button class="btn primary" data-do="add">Add with this title</button><button class="btn" data-do="skip">Skip</button></div>`,
        async e => { const act = e.target.closest("[data-do]")?.dataset.do; if (act === "skip") resume();
          if (act === "add") { const title = $("#mtitle").value.trim(); if (!title) return $("#mtitle").focus(); const res = await add({title, isbn}); resume(res === "added" ? added(title) : "Couldn't add that one."); } });
      say("Not found — add it by title, or skip"); return;
    }
    b.isbn = isbn;
    if (b.owned) { if ($("#auto").checked) return resume(`This edition is already on the shelf: ${b.title}`); }
    else if ($("#auto").checked) { const res = await add(b); return resume(res === "added" ? added(b.title) : res === "owned" ? "Already on the shelf" : "Couldn't add that one."); }
    showCard(`<div class="bar" style="align-items:flex-start;flex-wrap:nowrap">${cover(b)}<div><div class="t">${esc(b.title)}</div><div class="a">${esc(b.authors)}</div><div class="m">${line(b)}</div>
      ${b.other_edition ? `<div class="m" style="color:var(--warn)">You have another edition of this.</div>` : ""}
      <div class="bar" style="margin-top:10px">${b.owned ? `<span class="owned">This edition is already on the shelf</span><button class="btn" data-do="skip">Scan next</button>`
        : `<button class="btn primary" data-do="add">${b.other_edition ? "Add this edition" : "Add to shelf"}</button><button class="btn" data-do="skip">Skip</button>`}</div></div></div>`,
      async e => { const act = e.target.closest("[data-do]")?.dataset.do; if (act === "skip") resume();
        if (act === "add") { e.target.disabled = true; const res = await add(b); resume(res === "added" ? added(b.title) : res === "owned" ? "Already on the shelf" : "Couldn't add that one."); } });
    say("Found it");
  }
  $("#manual").addEventListener("submit", e => {
    e.preventDefault();
    const isbn = normalise($("#isbn").value);
    if (!isbn) return say("That isn't a valid ISBN");
    $("#isbn").value = ""; handle(isbn);
  });

  setMode(mode);
  // /scan?mode=check&isbn=978... looks that ISBN up straight away (links, phone shortcuts)
  const linked = normalise(params.get("isbn"));
  if (linked) handle(linked);
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) { $("#insecure").hidden = false; say("Camera unavailable here — type the ISBN below."); }
  else start();
})();
