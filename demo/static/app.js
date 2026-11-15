"use strict";
const COLORS = {
  "aria:button": [230, 25, 75], "aria:link": [0, 90, 220], "aria:menuitem": [245, 130, 48],
  "aria:tab": [145, 30, 180], "aria:checkbox": [60, 180, 75], "aria:radio": [0, 190, 160],
  "aria:textbox": [170, 110, 40], "aria:combobox": [240, 50, 230], "aria:slider": [128, 128, 0],
  "aria:progressbar": [0, 0, 128], "aria:gridcell": [100, 100, 100], "aria:listitem": [0, 170, 220],
  "aria:heading": [200, 160, 0], "aria:img": [120, 60, 160], "vax:visibleText": [125, 125, 125],
  "other:visible": [30, 30, 30],
};
const MAX_BYTES = 8 * 1024 * 1024;
const $ = (id) => document.getElementById(id);
const rgb = (role) => "rgb(" + (COLORS[role] || [30, 30, 30]).join(",") + ")";
let busy = false;
let objectUrl = null;

function setStatus(text, isError) {
  const el = $("status");
  el.textContent = text;
  el.className = isError ? "error" : "";
}

function setBusy(on) {
  busy = on;
  $("example").disabled = on;
  $("file").disabled = on;
  document.querySelector("label.btn").classList.toggle("disabled", on);
}

function errorText(code, status, retry) {
  switch (code) {
    case "too_large": return "That file is too large (limit 8 MB).";
    case "too_many_pixels": return "That image has too many pixels (limit 4096 px per side, 12 megapixels).";
    case "unsupported_type": return "Unsupported file type. Please upload a PNG, JPEG or WebP image.";
    case "rate_limited": return "Too many requests from your network. Please try again in " + (retry || "a few") + " seconds.";
    case "busy": return "The demo is busy, try again in a moment.";
    case "timeout": return "The demo is busy or the parse took too long, try again in a moment.";
    case "empty": return "The upload was empty.";
    case "invalid_image": return "That image could not be decoded.";
    default: return "Something went wrong (HTTP " + status + "). Please try again later.";
  }
}

async function parse(file) {
  if (busy) return;
  if (file.size > MAX_BYTES) { setStatus(errorText("too_large"), true); return; }
  setBusy(true);
  setStatus("Parsing… this takes about 10 seconds on our small CPU server.", false);
  let resp, data = null;
  try {
    resp = await fetch("/api/parse", {
      method: "POST",
      headers: { "Content-Type": file.type || "application/octet-stream" },
      body: file,
    });
    try { data = await resp.json(); } catch (e) { data = null; }
  } catch (e) {
    setStatus("Could not reach the server. Please try again.", true);
    setBusy(false);
    return;
  }
  setBusy(false);
  if (!resp.ok || !data) {
    const code = data && data.error;
    setStatus(errorText(code, resp.status, resp.headers.get("Retry-After")), true);
    return;
  }
  setStatus("", false);
  show(file, data);
}

function show(file, d) {
  if (objectUrl) URL.revokeObjectURL(objectUrl);
  objectUrl = URL.createObjectURL(file);
  $("shot").src = objectUrl;
  const [W, H] = d.image_size;
  const t = d.timings || {};
  let s = d.elements.length + " elements · parsed in " + d.elapsed_s.toFixed(1) + " s (detector " +
    (t.detect_s || 0).toFixed(1) + " s, OCR " + (t.ocr_s || 0).toFixed(1) + " s)";
  if (d.scaled) s += " · scaled from " + d.original_size[0] + "×" + d.original_size[1] + " to " + W + "×" + H;
  $("summary").textContent = s;
  $("tree").textContent = d.tree_text;

  const overlay = $("overlay");
  overlay.replaceChildren();
  const roles = new Set();
  const tip = $("tip");
  for (const e of d.elements) {
    roles.add(e.role);
    const [x, y, w, h] = e.box;
    const b = document.createElement("div");
    b.className = "box";
    b.style.left = (100 * x / W) + "%";
    b.style.top = (100 * y / H) + "%";
    b.style.width = (100 * w / W) + "%";
    b.style.height = (100 * h / H) + "%";
    b.style.borderColor = rgb(e.role);
    b.title = e.role + " · " + (e.name || "(no name)");
    b.addEventListener("mouseenter", () => { tip.hidden = false; tip.textContent = b.title; });
    b.addEventListener("mouseleave", () => { tip.textContent = ""; });
    overlay.appendChild(b);
  }
  tip.hidden = false;
  tip.textContent = "Hover a box to see its role and name.";
  const legend = $("legend");
  legend.replaceChildren();
  for (const r of Object.keys(COLORS).filter((k) => roles.has(k)).concat([...roles].filter((k) => !(k in COLORS)))) {
    const li = document.createElement("li");
    const sw = document.createElement("span");
    sw.className = "sw";
    sw.style.borderColor = rgb(r);
    li.appendChild(sw);
    li.appendChild(document.createTextNode(r));
    legend.appendChild(li);
  }
  overlay.classList.toggle("off", !$("show-boxes").checked);
  $("result").hidden = false;
}

$("file").addEventListener("change", (ev) => {
  const f = ev.target.files[0];
  ev.target.value = "";
  if (f) parse(f);
});
$("show-boxes").addEventListener("change", (ev) => $("overlay").classList.toggle("off", !ev.target.checked));
$("copy").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText($("tree").textContent); $("copy").textContent = "Copied"; }
  catch (e) { $("copy").textContent = "Copy failed"; }
  setTimeout(() => { $("copy").textContent = "Copy"; }, 1500);
});
$("example").addEventListener("click", async () => {
  if (busy) return;
  try {
    const r = await fetch("/example.png");
    const blob = await r.blob();
    parse(new File([blob], "example.png", { type: "image/png" }));
  } catch (e) {
    setStatus("Could not load the example.", true);
  }
});

let dragDepth = 0;
document.addEventListener("dragenter", (ev) => { ev.preventDefault(); dragDepth++; document.body.classList.add("dragging"); });
document.addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; document.body.classList.remove("dragging"); } });
document.addEventListener("dragover", (ev) => ev.preventDefault());
document.addEventListener("drop", (ev) => {
  ev.preventDefault();
  dragDepth = 0;
  document.body.classList.remove("dragging");
  const f = ev.dataTransfer && ev.dataTransfer.files[0];
  if (f) parse(f);
});
document.addEventListener("paste", (ev) => {
  for (const item of (ev.clipboardData && ev.clipboardData.items) || []) {
    if (item.kind === "file" && item.type.startsWith("image/")) { parse(item.getAsFile()); break; }
  }
});
