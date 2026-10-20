// The Chart page's figure, drawn with Plotly, that tells the app about your lines (Emil,
// 20 Oct 2026). Each time you draw, move or erase a line it sends every line on the price
// panel back as two (trading day, price) points; the app works out what changed and saves it.
// Saved lines arrive as shapes named "mark:<id>".

const chart = document.getElementById("chart");
let lastFig = null;
let days = []; // the x-axis categories: the trading days shown, oldest first
let rendered = {}; // saved line id -> its points as drawn
let ticker = "";
let count = 0;
let listening = false;

function send(type, data) {
  window.parent.postMessage(Object.assign({ isStreamlitMessage: true, type }, data), "*");
}

function position(v) {
  // A shape's x on the category axis: a day label, or a (fractional) index once dragged.
  if (typeof v === "number") return v;
  const i = days.indexOf(String(v).slice(0, 10));
  return i >= 0 ? i : null;
}

function points(shape) {
  // Both ends snapped to the nearest trading day, keeping the line where it was drawn.
  let a = position(shape.x0);
  let b = position(shape.x1);
  let ya = Number(shape.y0);
  let yb = Number(shape.y1);
  if (a === null || b === null || !isFinite(ya) || !isFinite(yb) || !days.length) return null;
  if (a > b) [a, b, ya, yb] = [b, a, yb, ya];
  const last = days.length - 1;
  const slope = b === a ? 0 : (yb - ya) / (b - a);
  const at = (i) => Math.round((ya + slope * (i - a)) * 10000) / 10000;
  const i0 = Math.min(Math.max(Math.round(a), 0), last);
  const i1 = Math.min(Math.max(Math.round(b), 0), last);
  return { x0: days[i0], y0: at(i0), x1: days[i1], y1: at(i1), past_end: b > last + 0.5 };
}

function savedId(shape) {
  return typeof shape.name === "string" && shape.name.startsWith("mark:")
    ? shape.name.slice(5)
    : null;
}

function priceLines() {
  // Lines on the price panel only; the pivot and stop levels span the panel ("x domain").
  return (chart.layout.shapes || []).filter(
    (s) => s.type === "line" && s.xref === "x" && s.yref === "y"
  );
}

function report() {
  const shapes = [];
  for (const s of priceLines()) {
    const p = points(s);
    if (p) shapes.push(Object.assign({ id: savedId(s) }, p));
  }
  count += 1;
  send("streamlit:setComponentValue", {
    value: { seq: `${Date.now()}-${count}`, ticker, rendered, shapes },
    dataType: "json",
  });
}

function themed(layout, theme) {
  // Room for the axis labels, and the page's colours (Streamlit does both for st.plotly_chart).
  const axes = Object.keys(layout).filter((key) => /^[xy]axis\d*$/.test(key));
  for (const key of axes) layout[key] = Object.assign({ automargin: true }, layout[key]);
  if (!theme) return layout;
  const dark = theme.base === "dark";
  const grid = dark ? "rgba(255,255,255,0.12)" : "rgba(0,0,0,0.08)";
  layout.paper_bgcolor = theme.backgroundColor;
  layout.plot_bgcolor = theme.backgroundColor;
  layout.font = Object.assign({}, layout.font, { color: theme.textColor });
  for (const key of axes) {
    layout[key] = Object.assign({}, layout[key], { gridcolor: grid, zerolinecolor: grid });
  }
  return layout;
}

function draw(args, theme) {
  const fig = JSON.parse(args.fig);
  days = (fig.data[0] && fig.data[0].x) || [];
  ticker = args.ticker;
  const layout = themed(fig.layout, theme);
  const config = Object.assign({ responsive: true }, args.config);
  Plotly.react(chart, fig.data, layout, config).then(() => {
    rendered = {};
    for (const s of priceLines()) {
      const id = savedId(s);
      const p = id && points(s);
      if (p) rendered[id] = p;
    }
    if (!listening) {
      chart.on("plotly_relayout", (change) => {
        if (Object.keys(change).some((k) => k.startsWith("shapes"))) report();
      });
      listening = true;
    }
    send("streamlit:setFrameHeight", { height: (args.height || 640) + 10 });
  });
}

window.addEventListener("message", (event) => {
  if (!event.data || event.data.type !== "streamlit:render") return;
  const args = event.data.args;
  if (args.fig === lastFig) return; // the same figure: keep your zoom and tool as they are
  lastFig = args.fig;
  draw(args, event.data.theme);
});

send("streamlit:componentReady", { apiVersion: 1 });
send("streamlit:setFrameHeight", { height: 650 });
