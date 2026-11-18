"use strict";
const byId = id => document.getElementById(id);
const data = JSON.parse(byId("project-data").textContent);
const pretty = name => ({
  Scene_Tuned_CLAHE: "Scene-tuned CLAHE", Fixed_Luminance_CLAHE: "Fixed luminance CLAHE",
  scene_tuned: "Scene-tuned CLAHE", stabilized: "Stabilized CLAHE", fixed: "Fixed CLAHE",
  night_bridge_20s: "Golden Gate Bridge · 20 seconds",
})[name] || name.replaceAll("_", " ");
const num = (value, digits = 2) => value === "" || value == null ? "—" :
  value === "inf" ? "∞" : Number(value).toFixed(digits);
const element = (tag, text, className) => {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (className) node.className = className;
  return node;
};
const options = (select, labels) => select.replaceChildren(
  ...labels.map((label, index) => new Option(label, index)),
);

function navigate() {
  const requested = location.hash.slice(1);
  const page = ["images", "video", "scores", "files"].includes(requested) ? requested : "images";
  document.querySelectorAll(".page").forEach(section => { section.hidden = section.id !== page; });
  document.querySelectorAll("[data-page]").forEach(link => {
    if (link.dataset.page === page) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  if (page === "video") { drawTimeline(); drawLocalChart(); }
  else pauseVideo();
}
window.addEventListener("hashchange", navigate);

const imageMethod = byId("image-method");
let currentImage = 0;
const imageButtons = data.images.map((item, index) => {
  const button = element("button");
  button.type = "button";
  button.setAttribute("aria-label", item.name);
  button.title = item.name;
  const img = element("img");
  img.src = item.thumb;
  img.alt = "";
  button.append(img);
  button.onclick = () => showImage(index);
  return button;
});
byId("image-gallery").replaceChildren(...imageButtons);
const imageMetrics = {
  Entropy_bits: "Entropy (bits)", Mean_brightness: "Mean brightness",
  Std_contrast: "Contrast (std. dev.)", AMBE_vs_input: "Brightness error",
  PSNR_vs_input_dB: "PSNR vs input (dB)", SSIM_vs_input: "SSIM vs input",
};

function showImage(index) {
  const prior = data.images[currentImage]?.methods[Number(imageMethod.value)]?.label;
  currentImage = index;
  const item = data.images[index];
  imageButtons.forEach((button, i) => button.setAttribute("aria-pressed", String(i === index)));
  byId("image-name").textContent = item.name.replace(/\.[^.]+$/, "");
  byId("image-before").src = item.methods[0].path;
  const { clip, tiles, strength } = item.settings;
  byId("image-settings").textContent = Number(strength)
    ? `Scene tuning · clip ${clip} · ${tiles} × ${tiles} tiles · ${Math.round(strength * 100)}% strength`
    : "Scene tuning selected the original";
  options(imageMethod, item.methods.map(method => pretty(method.label)));
  const target = item.methods.findIndex(method => method.label === (prior || "Scene_Tuned_CLAHE"));
  imageMethod.selectedIndex = target >= 0 ? target : Math.min(1, item.methods.length - 1);
  showImageMethod();
}
function showImageMethod() {
  const item = data.images[currentImage];
  const method = item.methods[Number(imageMethod.value)];
  byId("image-after").src = method.path;
  byId("image-after").alt = pretty(method.label);
  byId("output-image").href = method.path;
  byId("metric-method").textContent = pretty(method.label);
  const metrics = item.metrics.find(row => row.method === method.label);
  byId("image-metrics").replaceChildren(...(metrics
    ? Object.entries(imageMetrics).map(([key, label]) => {
      const row = element("div", null, "metric-row");
      row.append(element("span", label), element("strong", num(metrics[key], key.startsWith("SSIM") ? 3 : 2)));
      return row;
    }) : [element("p", "Measurements are available for enhanced images.")]));
}
imageMethod.onchange = showImageMethod;
byId("image-split").oninput = ({ target }) => byId("compare").style.setProperty("--split", `${target.value}%`);
if (data.images.length) showImage(0);
else {
  document.querySelector(".image-layout").hidden = true;
  byId("image-empty").hidden = false;
}

const original = byId("video-original");
const enhanced = byId("video-output");
const clipSelect = byId("video-clip");
const methodSelect = byId("video-method");
const seekbar = byId("video-seek");
const timeline = byId("timeline");
const measure = byId("timeline-metric");
const media = () => original.getAttribute("src") ? [original, enhanced] : [enhanced];
const clip = () => data.videos[Number(clipSelect.value)];
const selectedVideo = () => clip()?.methods[Number(methodSelect.value)];
const duration = () => (Number.isFinite(enhanced.duration) && enhanced.duration) ||
  Number(selectedVideo()?.summary.frames) / Number(selectedVideo()?.summary.fps) || 0;
const frameMeasurements = {
  1: ["Input brightness", "levels"], 2: ["Brightness lift", "levels"],
  3: ["Flicker", "levels"], 4: ["Processing time", "ms"],
};

const clock = seconds => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
function pauseVideo() {
  media().forEach(player => player.pause());
  byId("video-play").textContent = "▶ Play";
}
function seekTo(time) {
  const target = Math.min(duration(), Math.max(0, time));
  media().forEach(player => { if (player.readyState) player.currentTime = target; });
  syncTimeline(target);
}
function syncTimeline(time = enhanced.currentTime) {
  seekbar.max = duration() || 1;
  seekbar.value = time;
  byId("video-clock").textContent = `${clock(time)} / ${clock(duration())}`;
  drawTimeline(time);
}
function showClip() {
  const entry = clip();
  pauseVideo();
  original.hidden = !entry.source;
  byId("video-no-source").hidden = !!entry.source;
  if (entry.source) original.src = entry.source;
  else { original.removeAttribute("src"); original.load(); }
  options(methodSelect, entry.methods.map(method => pretty(method.summary.method)));
  const preferred = entry.methods.findIndex(method => method.summary.method === "scene_tuned");
  methodSelect.selectedIndex = Math.max(0, preferred);
  byId("video-csv").href = entry.csv;
  showVideo(0);
  showAudioLabel();
}
function showVideo(position = enhanced.currentTime) {
  const method = selectedVideo();
  if (!method) return;
  pauseVideo();
  byId("video-status").textContent = "";
  enhanced.src = method.path;
  enhanced.addEventListener("loadedmetadata", () => seekTo(position), {once: true});
  const row = method.summary;
  const stats = [
    ["Frames processed", row.frames], ["Mean brightness lift", `${num(row.mean_lift)} levels`],
    ["Mean flicker", num(row.mean_flicker, 3)], ["Mean processing time", `${num(row.mean_ms)} ms`],
  ];
  byId("video-metrics").replaceChildren(...stats.map(([name, value]) => {
    const card = element("article", null, "panel stat");
    card.append(element("span", name), element("strong", value));
    return card;
  }));
  const settings = clip().settings;
  byId("video-settings").replaceChildren(element("p", `${row.width} × ${row.height} · ${row.fps} fps · ${row.scenes} scene(s) · ${row.analyzed_transitions} measured frame transitions`));
  if (row.method !== "fixed" && settings.length) {
    const first = settings[0];
    const start = Number(first.strength)
      ? `clip ${first.clip}, ${first.tiles} × ${first.tiles} tiles, ${Math.round(first.strength * 100)}% strength`
      : "original selected";
    byId("video-settings").append(element("p", `First scene setting · ${start}`));
  }
  syncTimeline(position);
}
function showAudioLabel() {
  const audioTrack = media()[0];
  enhanced.muted = original !== audioTrack || audioTrack.muted;
  if (audioTrack === enhanced) enhanced.muted = !audioEnabled;
  byId("video-audio").setAttribute("aria-pressed", String(audioEnabled));
  byId("video-audio").textContent = audioEnabled ? "Sound on" : "Sound off";
}
let audioEnabled = false;
byId("video-audio").onclick = () => {
  audioEnabled = !audioEnabled;
  original.muted = !audioEnabled;
  showAudioLabel();
};
byId("video-play").onclick = async () => {
  if (!enhanced.paused) { pauseVideo(); return; }
  if (enhanced.ended || enhanced.currentTime >= duration() - .01) seekTo(0);
  try {
    await Promise.all(media().map(player => player.play()));
    byId("video-play").textContent = "❚❚ Pause";
  } catch {
    pauseVideo();
    byId("video-status").textContent = "Playback could not start. Check the clip or try opening the file directly from Result files.";
  }
};
enhanced.ontimeupdate = () => {
  if (media().length === 2 && !enhanced.paused && !enhanced.seeking &&
      Math.abs(original.currentTime - enhanced.currentTime) > .2) original.currentTime = enhanced.currentTime;
  if (!byId("video").hidden) syncTimeline();
};
enhanced.onended = pauseVideo;
seekbar.oninput = () => seekTo(Number(seekbar.value));
clipSelect.onchange = showClip;
methodSelect.onchange = () => showVideo();
measure.onchange = () => drawTimeline();
timeline.onclick = event => {
  const bounds = timeline.getBoundingClientRect();
  seekTo((event.clientX - bounds.left - 48) / Math.max(1, bounds.width - 63) * duration());
};

function drawGraph(canvas, points, span, cursor = null, scenes = []) {
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  if (w < 66 || h < 40 || !points.length || !span) return;
  const scale = window.devicePixelRatio || 1;
  if (canvas.width !== Math.round(w * scale) || canvas.height !== Math.round(h * scale)) {
    canvas.width = Math.round(w * scale);
    canvas.height = Math.round(h * scale);
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(scale, 0, 0, scale, 0, 0);
  ctx.clearRect(0, 0, w, h);
  const left = 48, top = 15, width = w - 63, height = h - 43;
  const values = points.map(point => point[1]).filter(Number.isFinite);
  if (!values.length) return;
  let min = 0, max = 0;
  for (const value of values) { min = Math.min(min, value); max = Math.max(max, value); }
  if (max === min) max += 1;
  const x = time => left + time / span * width;
  const y = value => top + height * (max - value) / (max - min);
  ctx.font = "11px system-ui";
  ctx.fillStyle = "#a1b2b5";
  ctx.strokeStyle = "#2b363b";
  for (let step = 0; step <= 4; step++) {
    const value = min + step * (max - min) / 4;
    ctx.beginPath(); ctx.moveTo(left, y(value)); ctx.lineTo(w - 15, y(value)); ctx.stroke();
    ctx.fillText(num(value, max - min < 1 ? 3 : 1), 4, y(value) + 4);
    ctx.textAlign = step === 4 ? "right" : "center";
    ctx.fillText(`${num(step * span / 4, 1)}s`, x(step * span / 4), h - 9);
    ctx.textAlign = "left";
  }
  ctx.strokeStyle = "#65777d";
  ctx.setLineDash([3, 4]);
  for (const cut of scenes) {
    ctx.beginPath(); ctx.moveTo(x(cut), top); ctx.lineTo(x(cut), top + height); ctx.stroke();
  }
  ctx.setLineDash([]);
  ctx.strokeStyle = "#a8edbf";
  ctx.lineWidth = 1.6;
  ctx.beginPath();
  let open = false;
  for (const [time, value] of points) {
    if (!Number.isFinite(value)) { open = false; continue; }
    if (open) ctx.lineTo(x(time), y(value));
    else ctx.moveTo(x(time), y(value));
    open = true;
  }
  ctx.stroke();
  if (cursor !== null) {
    ctx.strokeStyle = "#f0f5f4";
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x(cursor), top); ctx.lineTo(x(cursor), top + height); ctx.stroke();
  }
}
function drawTimeline(time = enhanced.currentTime) {
  const method = selectedVideo();
  if (!method || byId("video").hidden) return;
  const frames = method.frames;
  if (!frames.length) {
    byId("frame-detail").textContent = "No per-frame CSV was found for this method.";
    return;
  }
  const column = Number(measure.value);
  const [name, unit] = frameMeasurements[column];
  const frame = frames[Math.min(frames.length - 1, Math.floor(time * Number(method.summary.fps)))];
  drawGraph(timeline, frames.map(row => [row[0], row[column]]), duration(), time,
            frames.filter(row => row[5] && row[0] > 0).map(row => row[0]));
  byId("frame-detail").textContent = `${num(frame[0])} s · ${name} · ${num(frame[column], 3)} ${unit}`;
}
if (data.videos.length) {
  options(clipSelect, data.videos.map(run => pretty(run.name)));
  const requestedRun = new URLSearchParams(location.search).get("run");
  const openedRun = data.videos.findIndex(run => run.name === requestedRun);
  clipSelect.selectedIndex = Math.max(0, openedRun);
  showClip();
} else {
  byId("video-panel").hidden = true;
  byId("video-results").hidden = true;
  byId("video-empty").hidden = false;
}

const localInput = byId("local-video");
const localButton = byId("local-analyze");
const localExport = byId("local-export");
const localStatus = byId("local-status");
const localChart = byId("local-chart");
const localMeasure = byId("local-measure");
const localMeasureLabel = byId("local-measure-label");
let sampled = [];
let sampledDuration = 0;
let exportUrl;
function drawLocalChart() {
  drawGraph(localChart, sampled.map(row => [row[0], row[Number(localMeasure.value)]]), sampledDuration);
}
localMeasure.onchange = drawLocalChart;
localInput.onchange = () => {
  localButton.disabled = !localInput.files.length;
  localExport.hidden = true;
  localChart.hidden = localMeasureLabel.hidden = true;
  if (exportUrl) { URL.revokeObjectURL(exportUrl); exportUrl = null; }
  localStatus.textContent = localInput.files[0]?.name || "Choose a video file to begin.";
};
function onVideoEvent(video, name) {
  return new Promise((resolve, reject) => {
    const cleanup = () => { clearTimeout(timeout); video.removeEventListener(name, ready); video.removeEventListener("error", fail); };
    const ready = () => { cleanup(); resolve(); };
    const fail = () => { cleanup(); reject(new Error("The browser could not decode or seek this video.")); };
    const timeout = setTimeout(fail, 8000);
    video.addEventListener(name, ready);
    video.addEventListener("error", fail);
  });
}
localButton.onclick = async () => {
  const file = localInput.files[0];
  if (!file) return;
  localInput.disabled = localButton.disabled = true;
  localExport.hidden = localChart.hidden = localMeasureLabel.hidden = true;
  const video = element("video");
  video.muted = true;
  video.preload = "auto";
  const url = URL.createObjectURL(file);
  try {
    localStatus.textContent = "Reading video…";
    const ready = onVideoEvent(video, "loadeddata");
    video.src = url;
    await ready;
    const span = video.duration;
    if (!Number.isFinite(span) || span <= 0) throw new Error("A clip with a finite duration is required.");
    const pixels = element("canvas");
    pixels.width = 160;
    pixels.height = Math.max(1, Math.round(160 * video.videoHeight / video.videoWidth));
    const ctx = pixels.getContext("2d", {willReadFrequently: true});
    const count = Math.min(72, Math.max(1, Math.ceil(span * 2)));
    const result = [];
    for (let index = 0; index < count; index++) {
      const time = index * span / count;
      if (Math.abs(time - video.currentTime) > .001) {
        const seeked = onVideoEvent(video, "seeked");
        video.currentTime = time;
        await seeked;
      }
      ctx.drawImage(video, 0, 0, pixels.width, pixels.height);
      const rgba = ctx.getImageData(0, 0, pixels.width, pixels.height).data;
      let sum = 0, shadow = 0, highlight = 0;
      for (let pixel = 0; pixel < rgba.length; pixel += 4) {
        const luma = .299 * rgba[pixel] + .587 * rgba[pixel + 1] + .114 * rgba[pixel + 2];
        sum += luma;
        shadow += luma < 55;
        highlight += luma >= 235;
      }
      const total = pixels.width * pixels.height;
      result.push([time, sum / total, 100 * shadow / total, 100 * highlight / total]);
      localStatus.textContent = `Analyzing sample ${index + 1} of ${count}…`;
    }
    sampled = result;
    sampledDuration = span;
    const average = column => result.reduce((sum, row) => sum + row[column], 0) / result.length;
    localStatus.textContent = `${count} sampled frames · ${num(span, 1)} s · Mean luma ${num(average(1), 1)} / 255 · Shadows ${num(average(2), 1)}% · Highlights ${num(average(3), 1)}%`;
    const lines = ["time_s,mean_luma,shadow_percent,highlight_percent",
                   ...result.map(row => row.map(value => value.toFixed(4)).join(","))];
    if (exportUrl) URL.revokeObjectURL(exportUrl);
    exportUrl = URL.createObjectURL(new Blob([lines.join("\n") + "\n"], {type: "text/csv"}));
    localExport.href = exportUrl;
    localExport.hidden = localChart.hidden = localMeasureLabel.hidden = false;
    drawLocalChart();
  } catch (error) {
    localStatus.textContent = error.message;
  } finally {
    video.removeAttribute("src");
    video.load();
    URL.revokeObjectURL(url);
    localInput.disabled = localButton.disabled = false;
  }
};

const fileSearch = byId("file-search");
const fileType = byId("file-type");
const list = byId("file-list");
let currentFolder = "";
let activePath = "";
const fileIcons = {image: "▧", video: "▷", table: "▤", document: "▣", text: "≡", pdf: "▣"};
const bytes = size => size >= 1048576 ? `${num(size / 1048576, 1)} MB` :
  size >= 1024 ? `${num(size / 1024, 1)} KB` : `${size} B`;
function folderTo(path) {
  currentFolder = path;
  fileSearch.value = "";
  renderFiles();
  list.scrollTop = 0;
}
function renderFiles() {
  const terms = fileSearch.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const searching = terms.length > 0;
  const prefix = currentFolder ? currentFolder + "/" : "";
  const candidates = data.files.filter(file => (!fileType.value || file.kind === fileType.value) &&
    (searching ? terms.every(term => file.name.toLowerCase().includes(term)) : file.name.startsWith(prefix)));
  const crumbs = byId("breadcrumbs");
  const parts = currentFolder ? currentFolder.split("/") : [];
  crumbs.replaceChildren(...["All files", ...parts].map((name, index) => {
    const button = element("button", (index ? "› " : "") + name);
    button.onclick = () => folderTo(parts.slice(0, index).join("/"));
    return button;
  }));
  const folders = new Map();
  const files = [];
  for (const file of candidates) {
    const relative = searching ? file.name : file.name.slice(prefix.length);
    if (!searching && relative.includes("/")) {
      const folder = relative.split("/")[0];
      folders.set(folder, (folders.get(folder) || 0) + 1);
    } else files.push([file, relative]);
  }
  function row(icon, label, size, action, pressed) {
    const button = element("button", null, "file-row");
    const symbol = element("span", icon);
    symbol.setAttribute("aria-hidden", "true");
    button.append(symbol, element("span", label), element("span", size));
    button.onclick = action;
    if (pressed !== undefined) button.setAttribute("aria-pressed", String(pressed));
    return button;
  }
  list.replaceChildren(...[...folders].sort(([a], [b]) => a.localeCompare(b)).map(([folder, count]) =>
    row("▰", folder, `${count} files`, () => folderTo(prefix + folder))),
  ...files.map(([file, label]) => row(fileIcons[file.kind], label, bytes(file.size),
    event => {
      activePath = file.path;
      list.querySelector('[aria-pressed="true"]')?.setAttribute("aria-pressed", "false");
      event.currentTarget.setAttribute("aria-pressed", "true");
      previewFile(file);
    }, file.path === activePath)));
  if (!list.childElementCount) list.append(element("p", "No files match these filters.", "empty"));
}
function previewFile(file) {
  byId("file-heading").textContent = file.name.split("/").at(-1);
  const download = byId("file-download");
  download.href = file.path;
  download.hidden = false;
  let view;
  if (file.kind === "image") {
    view = element("img");
    view.src = file.path;
    view.alt = file.name;
  } else if (file.kind === "video") {
    view = element("video");
    view.src = file.path;
    view.controls = true;
    view.preload = "metadata";
  } else if (file.kind === "pdf" || file.kind === "document") {
    const pdf = file.kind === "pdf" ? file : data.files.find(candidate =>
      candidate.name === file.name.replace(/\.docx$/i, ".pdf"));
    if (pdf) {
      view = element("iframe");
      view.src = pdf.path;
      view.title = file.name;
    } else view = element("p", "Download the Word document to view it in your editor.", "empty");
  } else if (file.kind === "table") {
    const rows = data.tables[file.path];
    if (!rows?.length) view = element("p", "This CSV has no data rows.", "empty");
    else {
      view = element("div", null, "table-wrap");
      view.tabIndex = 0;
      view.setAttribute("aria-label", "Scrollable data table");
      const table = element("table");
      const keys = Object.keys(rows[0]);
      const head = table.createTHead().insertRow();
      keys.forEach(key => head.append(element("th", pretty(key))));
      const body = table.createTBody();
      rows.forEach(row => {
        const tr = body.insertRow();
        keys.forEach(key => tr.append(element("td", row[key])));
      });
      view.append(table);
    }
  } else view = element("pre", data.tables[file.path]);
  byId("file-preview").replaceChildren(view);
}
fileSearch.oninput = renderFiles;
fileType.onchange = renderFiles;
renderFiles();
window.addEventListener("resize", () => { drawTimeline(); drawLocalChart(); });
navigate();

const scoreSelect = byId("score-dataset");
const scoreFilter = byId("score-filter");
const scoreSources = data.files.filter(file => file.kind === "table").map(file => {
  const name = file.name.split("/").at(-1).replace(/\.csv$/, "");
  const labels = {
    metrics: "Image quality scores", scene_tuning: "Image tuning candidates",
    he_verification: "Image equalization verification", image_run_log: "Image run log",
    skipped_images: "Skipped images", video_summary: "Video benchmark",
    video_scene_tuning: "Video scene tuning",
  };
  const run = file.name.startsWith("Results/video/") ? pretty(file.name.split("/")[2]) : "";
  return {...file, label: [run, labels[name] || pretty(name)].filter(Boolean).join(" · ")};
}).sort((a, b) => {
  const rank = source => source.label === "Image quality scores" ? 0 : source.label.endsWith("Video benchmark") ? 1 : 2;
  return rank(a) - rank(b) || a.label.localeCompare(b.label);
});
options(scoreSelect, scoreSources.map(file => file.label));
const scoreSize = 40;
let scorePage = 0;
let scoreSort = {column: null, direction: 1};

function renderScores() {
  const target = byId("score-table");
  const source = scoreSources[Number(scoreSelect.value)];
  if (!source) {
    byId("score-download").hidden = true;
    byId("score-prev").disabled = byId("score-next").disabled = true;
    target.replaceChildren(element("p", "No score files have been generated.", "empty"));
    return;
  }
  byId("score-download").href = source.path;
  const records = data.tables[source.path] || [];
  const search = scoreFilter.value.trim().toLowerCase();
  const filtered = records.filter(row => !search || Object.values(row).some(value => String(value).toLowerCase().includes(search)));
  if (scoreSort.column) {
    const {column, direction} = scoreSort;
    const sortNumber = value => value === "inf" ? Infinity : Number(value);
    filtered.sort((a, b) => {
      const first = a[column] ?? "", second = b[column] ?? "";
      if (!first || !second) return Number(!first) - Number(!second);
      const x = sortNumber(first), y = sortNumber(second);
      const order = Number.isNaN(x) || Number.isNaN(y) ? first.localeCompare(second) : Number(x > y) - Number(x < y);
      return direction * order;
    });
  }
  const pages = Math.ceil(filtered.length / scoreSize);
  scorePage = Math.max(0, Math.min(scorePage, pages - 1));
  const start = scorePage * scoreSize;
  const end = Math.min(start + scoreSize, filtered.length);
  byId("score-info").textContent = `${filtered.length} matching / ${records.length} total rows · Select a column to sort`;
  byId("score-page").textContent = pages ? `${start + 1}–${end} of ${filtered.length}` : "0 rows";
  byId("score-prev").disabled = scorePage === 0;
  byId("score-next").disabled = scorePage + 1 >= pages;
  if (!filtered.length) {
    target.replaceChildren(element("p", records.length ? "No rows match the filter." : "This CSV has no data rows.", "empty"));
    return;
  }
  const columns = Object.keys(records[0]);
  const table = element("table");
  const header = table.createTHead().insertRow();
  for (const key of columns) {
    const cell = element("th");
    cell.scope = "col";
    const active = scoreSort.column === key;
    cell.setAttribute("aria-sort", active ? (scoreSort.direction === 1 ? "ascending" : "descending") : "none");
    const button = element("button", (imageMetrics[key] || pretty(key)) + (active ? (scoreSort.direction === 1 ? " ↑" : " ↓") : ""), "score-sort");
    button.dataset.key = key;
    button.onclick = () => {
      scoreSort = {column: key, direction: active ? -scoreSort.direction : 1};
      scorePage = 0;
      renderScores();
      [...target.querySelectorAll(".score-sort")].find(item => item.dataset.key === key)?.focus();
    };
    cell.append(button);
    header.append(cell);
  }
  const body = table.createTBody();
  for (const row of filtered.slice(start, end)) {
    const tr = body.insertRow();
    for (const key of columns) tr.append(element("td", row[key]));
  }
  target.replaceChildren(table);
  target.scrollTop = 0;
}
scoreSelect.onchange = () => { scoreSort.column = null; scorePage = 0; renderScores(); };
scoreFilter.oninput = () => { scorePage = 0; renderScores(); };
byId("score-prev").onclick = () => { scorePage--; renderScores(); };
byId("score-next").onclick = () => { scorePage++; renderScores(); };
renderScores();
