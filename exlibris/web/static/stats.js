// Stats charts. One colour per chart (the theme's --bar), the biggest real bar in
// the theme's orange, unknown buckets muted; every label escaped before ECharts
// puts it in a tooltip (they come from Open Library, which anyone can edit).
(() => {
  const {esc, $} = XL;
  const fun = $("#fun");
  if (fun) fun.innerHTML = fun.dataset.md.split(/\n+/).filter(Boolean)
    .map(l => `<p>${esc(l).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/\*(.+?)\*/g, "<em>$1</em>")}</p>`).join("");
  if (!window.echarts) return;
  const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const UNKNOWN = ["No genre yet", "Format unknown"];
  const charts = [];
  function draw() {
    charts.forEach(c => c.dispose()); charts.length = 0;
    const BAR = css("--bar"), TOP = css("--flare"), MUTED = css("--muted"), INK = css("--ink"), LINE = css("--line"), UNK = css("--unknown");
    document.querySelectorAll(".chart[data-rows]").forEach(el => {
      const rows = JSON.parse(el.dataset.rows), horizontal = el.dataset.h === "1";
      if (!rows.length) { el.style.display = "none"; return; }
      let top = -1;
      rows.forEach((r, i) => { if (!UNKNOWN.includes(r[0]) && (top < 0 || r[1] > rows[top][1])) top = i; });
      const data = rows.map((r, i) => ({value: r[1], itemStyle: {color: i === top ? TOP : UNKNOWN.includes(r[0]) ? UNK : BAR}}));
      const labels = rows.map(r => r[0]);
      el.style.height = horizontal ? `${Math.max(140, rows.length * 30 + 30)}px` : "240px";
      const c = echarts.init(el, null, {renderer: "svg"});
      const cat = {type: "category", data: horizontal ? labels.slice().reverse() : labels, axisTick: {show: false},
                   axisLine: {lineStyle: {color: LINE}}, axisLabel: {color: MUTED, width: 150, overflow: "truncate"}};
      const val = {type: "value", minInterval: 1, splitLine: {lineStyle: {color: LINE}}, axisLabel: {color: MUTED}};
      c.setOption({
        animation: false, backgroundColor: "transparent", grid: {left: 8, right: 36, top: 8, bottom: 8, containLabel: true},
        tooltip: {trigger: "axis", axisPointer: {type: "shadow"}, backgroundColor: css("--panel"), borderWidth: 0, textStyle: {color: INK},
                  formatter: p => `${echarts.format.encodeHTML(p[0].name)}<br><b>${+p[0].value}</b> book${p[0].value === 1 ? "" : "s"}`},
        xAxis: horizontal ? val : cat, yAxis: horizontal ? cat : val,
        series: [{type: "bar", barMaxWidth: 18, data: horizontal ? data.slice().reverse() : data, emphasis: {disabled: true},
                  itemStyle: {borderRadius: horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]},
                  label: horizontal ? {show: true, position: "right", color: INK, fontSize: 12} : {show: false}}],
      });
      if (el.dataset.link) c.on("click", p => { location.href = el.dataset.link + encodeURIComponent(p.name); });
      charts.push(c);
    });
  }
  draw();
  addEventListener("resize", () => charts.forEach(c => c.resize()));
  matchMedia("(prefers-color-scheme: light)").addEventListener("change", draw);
})();
