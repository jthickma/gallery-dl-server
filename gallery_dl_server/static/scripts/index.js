// Theme
const root = document.documentElement;
const themeToggle = document.getElementById("theme-toggle");

function applyTheme(theme) {
  if (theme === "light") {
    root.classList.add("theme-light");
    themeToggle.innerHTML = `<i class="bi bi-sun-fill"></i>`;
  } else {
    root.classList.remove("theme-light");
    themeToggle.innerHTML = `<i class="bi bi-moon-fill"></i>`;
  }
}

applyTheme(localStorage.getItem("theme") || "dark");

themeToggle.onclick = () => {
  const next = root.classList.contains("theme-light") ? "dark" : "light";
  localStorage.setItem("theme", next);
  applyTheme(next);
};

// Reveal body once theme applied (avoids FOUC)
document.body.classList.remove("preload");

// Utils
function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatBytes(size) {
  if (size < 1024) return `${size} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = size;
  let unitIndex = -1;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[unitIndex]}`;
}

function formatTimestamp(unixTimestamp) {
  const date = new Date(unixTimestamp * 1000);
  return date.toLocaleString();
}

function pathToParam(path) {
  return encodeURIComponent(path || "");
}

const IMAGE_EXT = new Set(["png", "jpg", "jpeg", "gif", "webp", "avif", "bmp", "svg", "apng", "jfif"]);
const VIDEO_EXT = new Set(["mp4", "webm", "mov", "m4v", "mkv", "ogv"]);
const AUDIO_EXT = new Set(["mp3", "m4a", "ogg", "opus", "wav", "flac", "aac"]);
const TEXT_EXT = new Set(["txt", "log", "json", "md", "csv", "html", "xml", "yml", "yaml", "js", "css", "py", "ini", "conf"]);
const PDF_EXT = new Set(["pdf"]);

function fileExt(name) {
  const dot = name.lastIndexOf(".");
  if (dot < 0) return "";
  return name.slice(dot + 1).toLowerCase();
}

function mediaKind(name) {
  const ext = fileExt(name);
  if (IMAGE_EXT.has(ext)) return "image";
  if (VIDEO_EXT.has(ext)) return "video";
  if (AUDIO_EXT.has(ext)) return "audio";
  if (TEXT_EXT.has(ext)) return "text";
  if (PDF_EXT.has(ext)) return "pdf";
  return "other";
}

function iconForEntry(entry) {
  if (entry.is_dir) return "bi-folder-fill";
  switch (mediaKind(entry.name)) {
    case "image":
      return "bi-file-earmark-image";
    case "video":
      return "bi-file-earmark-play";
    case "audio":
      return "bi-file-earmark-music";
    case "text":
      return "bi-file-earmark-text";
    case "pdf":
      return "bi-file-earmark-pdf";
    default:
      return "bi-file-earmark";
  }
}

// State
const state = {
  path: "",
  parent: "",
  root: "",
  entries: [],
  view: localStorage.getItem("filesView") || "grid",
  sort: localStorage.getItem("filesSort") || "name-asc",
};

// Elements
const downloadsRoot = document.getElementById("downloads-root");
const breadcrumbs = document.getElementById("downloads-breadcrumbs");
const viewEl = document.getElementById("downloads-view");
const refreshBtn = document.getElementById("refresh-downloads");
const viewGridBtn = document.getElementById("view-grid");
const viewListBtn = document.getElementById("view-list");
const sortSelect = document.getElementById("sort-select");
const form = document.getElementById("form");
const videoOpts = form.querySelector("select[name='video-opts']");
const urlInput = form.querySelector("input[name='url']");
const box = document.getElementById("box");
const logsPanel = document.getElementById("container-logs");
const toggleLogsBtn = document.getElementById("toggle-logs");
const closeLogsBtn = document.getElementById("close-logs");

// Restore saved state
sortSelect.value = state.sort;
applyViewButton();

if (localStorage.getItem("selectedValue")) {
  videoOpts.value = localStorage.getItem("selectedValue");
}
videoOpts.onchange = () => localStorage.setItem("selectedValue", videoOpts.value);

function applyViewButton() {
  viewGridBtn.classList.toggle("active", state.view === "grid");
  viewListBtn.classList.toggle("active", state.view === "list");
}

viewGridBtn.onclick = () => {
  state.view = "grid";
  localStorage.setItem("filesView", "grid");
  applyViewButton();
  renderView();
};

viewListBtn.onclick = () => {
  state.view = "list";
  localStorage.setItem("filesView", "list");
  applyViewButton();
  renderView();
};

sortSelect.onchange = () => {
  state.sort = sortSelect.value;
  localStorage.setItem("filesSort", state.sort);
  renderView();
};

// Breadcrumbs
function renderBreadcrumbs() {
  const segments = state.path ? state.path.split("/").filter(Boolean) : [];
  const parts = [
    `<button type="button" class="crumb" data-path="">root</button>`,
  ];

  let acc = "";
  segments.forEach((seg, i) => {
    acc = acc ? `${acc}/${seg}` : seg;
    const isLast = i === segments.length - 1;
    parts.push(`<span class="sep">/</span>`);
    parts.push(
      isLast
        ? `<span class="crumb current">${escapeHtml(seg)}</span>`
        : `<button type="button" class="crumb" data-path="${escapeHtml(acc)}">${escapeHtml(seg)}</button>`
    );
  });

  breadcrumbs.innerHTML = parts.join("");
  breadcrumbs.querySelectorAll("button.crumb").forEach((b) => {
    b.onclick = () => loadDownloads(b.getAttribute("data-path") || "");
  });
}

// Sort
function sortedEntries() {
  const [key, dir] = state.sort.split("-");
  const mult = dir === "asc" ? 1 : -1;
  const copy = state.entries.slice();
  copy.sort((a, b) => {
    if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1;
    if (key === "name") return a.name.localeCompare(b.name, undefined, { numeric: true }) * mult;
    if (key === "modified") return (a.modified - b.modified) * mult;
    if (key === "size") return (a.size - b.size) * mult;
    return 0;
  });
  return copy;
}

// Media list for viewer (files only, in sorted order)
function mediaList() {
  return sortedEntries().filter((e) => !e.is_dir && ["image", "video", "audio"].includes(mediaKind(e.name)));
}

// Render main view
function renderView() {
  viewEl.className = `downloads-view ${state.view === "grid" ? "grid-view" : "list-view"}`;

  if (!state.entries.length && !state.path) {
    viewEl.innerHTML = `<div class="state-msg"><i class="bi bi-inbox"></i>No downloads yet. Paste a URL above.</div>`;
    return;
  }

  const entries = sortedEntries();

  if (!entries.length) {
    viewEl.innerHTML = `<div class="state-msg"><i class="bi bi-folder"></i>Empty folder.</div>`;
    return;
  }

  if (state.view === "grid") {
    renderGrid(entries);
  } else {
    renderList(entries);
  }
}

function renderGrid(entries) {
  const cards = [];

  if (state.path) {
    cards.push(`
      <div class="card up" data-up="1" data-path="${escapeHtml(state.parent || "")}">
        <div class="card-thumb"><i class="bi bi-arrow-up-circle icon-fallback"></i></div>
        <div class="card-body">
          <span class="card-name">..</span>
          <span class="card-meta">Up one level</span>
        </div>
      </div>
    `);
  }

  for (const entry of entries) {
    const name = escapeHtml(entry.name);
    const path = escapeHtml(entry.path);
    const modified = formatTimestamp(entry.modified);

    if (entry.is_dir) {
      cards.push(`
        <div class="card dir" data-dir="1" data-path="${path}">
          <div class="card-thumb"><i class="bi bi-folder-fill icon-fallback"></i></div>
          <div class="card-body">
            <span class="card-name" title="${name}">${name}</span>
            <span class="card-meta">${modified}</span>
          </div>
        </div>
      `);
      continue;
    }

    const kind = mediaKind(entry.name);
    let thumb = "";
    if (kind === "image") {
      thumb = `<img loading="lazy" decoding="async" src="/gallery-dl/files/content?path=${pathToParam(entry.path)}" alt="" onerror="this.replaceWith(Object.assign(document.createElement('i'),{className:'bi ${iconForEntry(entry)} icon-fallback'}))" />`;
    } else if (kind === "video") {
      thumb = `<video muted preload="metadata" src="/gallery-dl/files/content?path=${pathToParam(entry.path)}#t=0.1"></video><span class="badge">video</span>`;
    } else if (kind === "audio") {
      thumb = `<i class="bi bi-music-note-beamed icon-fallback"></i><span class="badge">audio</span>`;
    } else {
      thumb = `<i class="bi ${iconForEntry(entry)} icon-fallback"></i>`;
    }

    cards.push(`
      <div class="card file" data-file="1" data-path="${path}" data-name="${name}">
        <div class="card-thumb">${thumb}</div>
        <div class="card-body">
          <span class="card-name" title="${name}">${name}</span>
          <span class="card-meta">${formatBytes(entry.size)} · ${modified}</span>
        </div>
      </div>
    `);
  }

  viewEl.innerHTML = cards.join("");
  bindEntryClicks();
}

function renderList(entries) {
  const rows = [];
  rows.push(`
    <div class="row header">
      <span></span>
      <span>Name</span>
      <span class="rcol">Size</span>
      <span class="rcol">Type</span>
      <span class="rcol rmod">Modified</span>
      <span class="ractions"></span>
    </div>
  `);

  if (state.path) {
    rows.push(`
      <div class="row dir" data-up="1" data-path="${escapeHtml(state.parent || "")}">
        <i class="bi bi-arrow-up-circle ri"></i>
        <span class="rname">..</span>
        <span class="rcol">-</span>
        <span class="rcol">Up</span>
        <span class="rcol rmod">-</span>
        <span class="ractions"></span>
      </div>
    `);
  }

  for (const entry of entries) {
    const name = escapeHtml(entry.name);
    const path = escapeHtml(entry.path);
    const iconCls = iconForEntry(entry);

    if (entry.is_dir) {
      rows.push(`
        <div class="row dir" data-dir="1" data-path="${path}">
          <i class="bi ${iconCls} ri"></i>
          <span class="rname" title="${name}">${name}</span>
          <span class="rcol">-</span>
          <span class="rcol">Folder</span>
          <span class="rcol rmod">${formatTimestamp(entry.modified)}</span>
          <span class="ractions">
            <a class="icon-btn" href="/gallery-dl/files/archive?path=${pathToParam(entry.path)}" title="Download folder as ZIP" onclick="event.stopPropagation()"><i class="bi bi-file-earmark-zip"></i></a>
          </span>
        </div>
      `);
      continue;
    }

    const kind = mediaKind(entry.name);
    rows.push(`
      <div class="row file" data-file="1" data-path="${path}" data-name="${name}">
        <i class="bi ${iconCls} ri"></i>
        <span class="rname" title="${name}">${name}</span>
        <span class="rcol">${formatBytes(entry.size)}</span>
        <span class="rcol">${kind}</span>
        <span class="rcol rmod">${formatTimestamp(entry.modified)}</span>
        <span class="ractions">
          <a class="icon-btn" href="/gallery-dl/files/download?path=${pathToParam(entry.path)}" title="Download" onclick="event.stopPropagation()"><i class="bi bi-download"></i></a>
        </span>
      </div>
    `);
  }

  viewEl.innerHTML = rows.join("");
  bindEntryClicks();
}

function bindEntryClicks() {
  viewEl.querySelectorAll("[data-up], [data-dir]").forEach((el) => {
    el.onclick = (e) => {
      if (e.target.closest(".ractions")) return;
      loadDownloads(el.getAttribute("data-path") || "");
    };
  });
  viewEl.querySelectorAll("[data-file]").forEach((el) => {
    el.onclick = (e) => {
      if (e.target.closest(".ractions")) return;
      openViewer(el.getAttribute("data-path"));
    };
  });
}

async function loadDownloads(path = "") {
  viewEl.innerHTML = `<div class="state-msg"><i class="bi bi-hourglass-split"></i>Loading...</div>`;
  try {
    const response = await fetch(`/gallery-dl/files?path=${pathToParam(path)}`, {
      method: "GET",
      headers: { "Cache-Control": "no-cache" },
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (!data.success) throw new Error(data.error || "Failed to load");

    state.path = data.path || "";
    state.parent = data.parent || "";
    state.root = data.root || "";
    state.entries = data.entries || [];

    downloadsRoot.textContent = data.root ? `· ${data.root}` : "";
    renderBreadcrumbs();
    renderView();
  } catch (error) {
    viewEl.innerHTML = `<div class="state-msg"><i class="bi bi-exclamation-triangle"></i>${escapeHtml(error.message)}</div>`;
  }
}

refreshBtn.onclick = () => loadDownloads(state.path);

// Viewer
const viewer = document.getElementById("viewer");
const viewerStage = document.getElementById("viewer-stage");
const viewerTitle = document.getElementById("viewer-title");
const viewerMeta = document.getElementById("viewer-meta");
const viewerDownload = document.getElementById("viewer-download");
const viewerOpen = document.getElementById("viewer-open");
const viewerClose = document.getElementById("viewer-close");
const viewerPrev = document.getElementById("viewer-prev");
const viewerNext = document.getElementById("viewer-next");

let viewerList = [];
let viewerIndex = -1;

function openViewer(path) {
  const entry = state.entries.find((e) => e.path === path);
  if (!entry || entry.is_dir) return;

  const kind = mediaKind(entry.name);
  if (["image", "video", "audio"].includes(kind)) {
    viewerList = mediaList();
    viewerIndex = viewerList.findIndex((e) => e.path === entry.path);
    if (viewerIndex < 0) {
      viewerList = [entry];
      viewerIndex = 0;
    }
  } else {
    viewerList = [entry];
    viewerIndex = 0;
  }

  viewer.classList.remove("hidden");
  document.body.style.overflow = "hidden";
  showCurrent();
}

function closeViewer() {
  viewer.classList.add("hidden");
  document.body.style.overflow = "";
  viewerStage.innerHTML = "";
  viewerList = [];
  viewerIndex = -1;
}

function showCurrent() {
  const entry = viewerList[viewerIndex];
  if (!entry) return;

  const url = `/gallery-dl/files/content?path=${pathToParam(entry.path)}`;
  const dlUrl = `/gallery-dl/files/download?path=${pathToParam(entry.path)}`;
  const kind = mediaKind(entry.name);

  viewerTitle.textContent = entry.name;
  viewerMeta.textContent = `${formatBytes(entry.size)} · ${formatTimestamp(entry.modified)} · ${viewerIndex + 1} / ${viewerList.length}`;
  viewerDownload.href = dlUrl;
  viewerOpen.href = url;

  viewerPrev.disabled = viewerIndex <= 0;
  viewerNext.disabled = viewerIndex >= viewerList.length - 1;

  let node;
  if (kind === "image") {
    node = document.createElement("img");
    node.src = url;
    node.alt = entry.name;
  } else if (kind === "video") {
    node = document.createElement("video");
    node.src = url;
    node.controls = true;
    node.autoplay = true;
    node.playsInline = true;
  } else if (kind === "audio") {
    node = document.createElement("audio");
    node.src = url;
    node.controls = true;
    node.autoplay = true;
  } else if (kind === "pdf") {
    node = document.createElement("iframe");
    node.src = url;
    node.title = entry.name;
  } else if (kind === "text") {
    node = document.createElement("pre");
    node.textContent = "Loading...";
    fetch(url)
      .then((r) => r.text())
      .then((t) => {
        node.textContent = t.length > 500000 ? t.slice(0, 500000) + "\n\n... (truncated)" : t;
      })
      .catch((e) => (node.textContent = `Error loading file: ${e.message}`));
  } else {
    node = document.createElement("div");
    node.className = "viewer-unsupported";
    node.innerHTML = `
      <i class="bi bi-file-earmark"></i>
      <div>Preview not available for <strong>${escapeHtml(entry.name)}</strong>.</div>
      <div style="margin-top:12px"><a class="btn-ghost" href="${dlUrl}">Download file</a></div>
    `;
  }

  viewerStage.innerHTML = "";
  viewerStage.appendChild(node);
}

viewerClose.onclick = closeViewer;
viewer.addEventListener("click", (e) => {
  if (e.target === viewer || e.target === viewerStage) closeViewer();
});

viewerPrev.onclick = () => {
  if (viewerIndex > 0) {
    viewerIndex--;
    showCurrent();
  }
};

viewerNext.onclick = () => {
  if (viewerIndex < viewerList.length - 1) {
    viewerIndex++;
    showCurrent();
  }
};

document.addEventListener("keydown", (e) => {
  if (viewer.classList.contains("hidden")) return;
  if (e.key === "Escape") closeViewer();
  else if (e.key === "ArrowLeft") viewerPrev.click();
  else if (e.key === "ArrowRight") viewerNext.click();
});

// Submit form
const successAlert = Swal.mixin({
  animation: true,
  position: "top-end",
  icon: "success",
  iconColor: "#a855f7",
  showConfirmButton: false,
  target: "body",
  timer: 3000,
  timerProgressBar: true,
  toast: true,
  didOpen: (toast) => {
    toast.onmouseenter = Swal.stopTimer;
    toast.onmouseleave = Swal.resumeTimer;
  },
});

form.onsubmit = async (event) => {
  event.preventDefault();

  if (!ws || ws.readyState === WebSocket.CLOSED) connectWebSocket();

  const formData = new FormData(event.target);
  const url = formData.get("url");
  if (!url) return;

  try {
    const response = await fetch("/gallery-dl/q", { method: "POST", body: formData });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    await response.json();

    urlInput.value = "";
    successAlert.fire({
      title: "Queued",
      html: `<a href="${url}" target="_blank" rel="noopener noreferrer">Link</a> added to downloads.`,
    });
    setTimeout(() => loadDownloads(state.path), 1500);
  } catch (error) {
    console.error(error);
    Swal.fire({
      toast: true,
      position: "top-end",
      icon: "error",
      title: "Failed to queue",
      showConfirmButton: false,
      timer: 3000,
      target: "body",
    });
  }
};

// Logs panel
function showLogs() {
  logsPanel.classList.remove("hidden");
  localStorage.setItem("logs", "shown");
  if ("boxHeight" in sessionStorage && sessionStorage.getItem("boxHeight") !== "0") {
    box.style.height = sessionStorage.getItem("boxHeight") + "px";
  }
  box.scrollTop = box.scrollHeight;
}

function hideLogs() {
  const rect = box.getBoundingClientRect();
  sessionStorage.setItem("boxHeight", rect.height);
  sessionStorage.setItem("scrollPos", box.scrollTop);
  logsPanel.classList.add("hidden");
  localStorage.setItem("logs", "hidden");
}

toggleLogsBtn.onclick = () => {
  if (logsPanel.classList.contains("hidden")) showLogs();
  else hideLogs();
};

closeLogsBtn.onclick = hideLogs;

if (localStorage.getItem("logs") === "shown") showLogs();

// Log stream + WS
let ws;
let isConnected = false;
let isPageAlive = true;

async function fetchLogs() {
  try {
    const response = await fetch("/stream/logs", {
      method: "GET",
      headers: {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
      },
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const logs = await response.text();
    if (box.textContent !== logs) {
      box.textContent = logs;
      box.scrollTop = box.scrollHeight;
    }
    if (!isConnected) connectWebSocket();
  } catch (error) {
    console.error(error.message);
  }
}

function connectWebSocket(allowReconnect = true) {
  const protocol = window.location.protocol === "https:" ? "wss://" : "ws://";
  const url = `${protocol}${window.location.host}/ws/logs`;

  let lastLine = "";
  let lastPos = localStorage.getItem("lastPos") ? parseInt(localStorage.getItem("lastPos")) : 0;

  ws = new WebSocket(url);

  ws.onopen = () => {
    isConnected = true;
  };

  ws.onmessage = (event) => {
    const newLines = event.data.split("\n").filter(Boolean);
    if (!newLines.length) return;

    const lines = box.textContent.split("\n").filter(Boolean);
    lastLine = lastPos ? lines[lastPos] : lines[lines.length - 1] || null;

    const isLastLineProgress = lastLine?.includes("B/s");
    const isNewLineProgress = newLines[0].includes("B/s");

    if (newLines.length > 1 && isNewLineProgress && newLines[1].includes("B/s")) newLines.pop();

    let progressUpdate = false;
    if (isLastLineProgress && isNewLineProgress) {
      progressUpdate = true;
      lastPos = lastPos || lines.length - 1;
      lines[lastPos] = newLines[0];
    } else if (isLastLineProgress && !isNewLineProgress) {
      lastPos = 0;
    }

    lines.push(...newLines.slice(progressUpdate ? 1 : 0));
    box.textContent = lines.join("\n") + "\n";
    localStorage.setItem("lastPos", lastPos);

    if (!progressUpdate || newLines.length > 1) box.scrollTop = box.scrollHeight;
  };

  ws.onerror = (event) => console.error("WebSocket error:", event);

  ws.onclose = () => {
    if (isConnected) {
      isConnected = false;
      if (isPageAlive && allowReconnect) {
        setTimeout(() => connectWebSocket(allowReconnect), 2000);
      }
    }
  };
}

fetchLogs();
loadDownloads();

window.onbeforeunload = () => {
  isPageAlive = false;
  if (ws) ws.close(1000, "leaving page");
  if (!logsPanel.classList.contains("hidden")) {
    const rect = box.getBoundingClientRect();
    sessionStorage.setItem("boxHeight", rect.height);
    sessionStorage.setItem("scrollPos", box.scrollTop);
  }
};
