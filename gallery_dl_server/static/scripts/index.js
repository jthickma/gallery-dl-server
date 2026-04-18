const darkModeStyle = document.getElementById("dark-mode");
const darkModeToggle = document.getElementById("dark-mode-toggle");

function enableDarkMode() {
  darkModeStyle.disabled = false;
  darkModeToggle.innerHTML = `<i class="bi bi-sun-fill"></i>`;
}

function disableDarkMode() {
  darkModeStyle.disabled = true;
  darkModeToggle.innerHTML = `<i class="bi bi-moon-fill"></i>`;
}

if (localStorage.getItem("theme") !== "light") {
  enableDarkMode();
}

darkModeToggle.onclick = () => {
  if (darkModeStyle.disabled) {
    enableDarkMode();
    localStorage.setItem("theme", "dark");
  } else {
    disableDarkMode();
    localStorage.setItem("theme", "light");
  }
};

const selectElement = document.querySelector("select[name='video-opts']");

function setSelectedValue() {
  const selectedValue = localStorage.getItem("selectedValue");
  if (selectedValue) {
    selectElement.value = selectedValue;
  }
}

setSelectedValue();

selectElement.onchange = () => {
  localStorage.setItem("selectedValue", selectElement.value);
};

const box = document.getElementById("box");
const btn = document.getElementById("button-logs");

function toggleLogs() {
  if (btn.innerText == "Show Logs") {
    btn.innerText = "Hide Logs";
    box.classList.remove("d-none");
    loadBox();
    localStorage.setItem("logs", "shown");
  }
  else {
    saveBox();
    btn.innerText = "Show Logs";
    box.classList.add("d-none");
    localStorage.setItem("logs", "hidden");
  }
}

function loadBox() {
  if ("boxHeight" in sessionStorage && sessionStorage.getItem("boxHeight") != "0") {
    box.style.height = sessionStorage.getItem("boxHeight") + "px";
  }
  else {
    box.style.height = "";
  }

  if ("scrollPos" in sessionStorage) {
    box.scrollTop = sessionStorage.getItem("scrollPos");
  }
  else {
    box.scrollTop = box.scrollHeight;
  }
}

function saveBox() {
  const boxPos = box.getBoundingClientRect();
  sessionStorage.setItem("boxHeight", boxPos.height);
  sessionStorage.setItem("scrollPos", box.scrollTop);
}

if (localStorage.getItem("logs") == "shown") {
  toggleLogs();
}

btn.onclick = () => toggleLogs();

function scrollOnResize() {
  let lastHeight = box.offsetHeight;

  const observer = new ResizeObserver(entries => {
    for (let entry of entries) {
      if (entry.contentRect.height > lastHeight) {
        window.scrollTo({
          top: entry.target.getBoundingClientRect().bottom + window.scrollY,
          behavior: "smooth"
        });
      }
      lastHeight = entry.contentRect.height;
    }
  });

  observer.observe(box);
}

scrollOnResize();

document.querySelector("body").classList.remove("d-none");

const form = document.getElementById("form");
const downloadsBody = document.getElementById("downloads-body");
const downloadsRoot = document.getElementById("downloads-root");
const downloadsBreadcrumbs = document.getElementById("downloads-breadcrumbs");
const refreshDownloadsButton = document.getElementById("refresh-downloads");

let currentDownloadsPath = "";

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatBytes(size) {
  if (size < 1024) {
    return `${size} B`;
  }

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

/* ── Media type detection ── */

const IMAGE_EXTS = new Set([
  "jpg", "jpeg", "png", "gif", "webp", "bmp", "svg", "avif", "ico", "jfif"
]);
const VIDEO_EXTS = new Set([
  "mp4", "webm", "mkv", "mov", "avi", "m4v", "ogv"
]);
const AUDIO_EXTS = new Set([
  "mp3", "ogg", "wav", "flac", "aac", "m4a", "opus", "wma"
]);

function getFileExt(name) {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot + 1).toLowerCase() : "";
}

function getMediaType(name) {
  const ext = getFileExt(name);
  if (IMAGE_EXTS.has(ext)) return "image";
  if (VIDEO_EXTS.has(ext)) return "video";
  if (AUDIO_EXTS.has(ext)) return "audio";
  return null;
}

function getFileIcon(name) {
  const type = getMediaType(name);
  if (type === "image") return `<i class="bi bi-file-earmark-image file-icon-image"></i>`;
  if (type === "video") return `<i class="bi bi-file-earmark-play file-icon-video"></i>`;
  if (type === "audio") return `<i class="bi bi-file-earmark-music file-icon-audio"></i>`;
  return `<i class="bi bi-file-earmark"></i>`;
}

/* ── Media modal ── */

const mediaModal = document.getElementById("media-modal");
const mediaModalBody = document.getElementById("media-modal-body");
const mediaModalTitle = document.getElementById("media-modal-title");
const mediaModalDownload = document.getElementById("media-modal-download");
const mediaModalClose = document.getElementById("media-modal-close");

function openMediaModal(name, path) {
  const type = getMediaType(name);
  const contentUrl = `/gallery-dl/files/content?path=${pathToParam(path)}`;
  const downloadUrl = `/gallery-dl/files/download?path=${pathToParam(path)}`;

  mediaModalTitle.textContent = name;
  mediaModalDownload.href = downloadUrl;

  if (type === "image") {
    mediaModalBody.innerHTML = `<img src="${escapeHtml(contentUrl)}" alt="${escapeHtml(name)}" />`;
  } else if (type === "video") {
    mediaModalBody.innerHTML = `<video src="${escapeHtml(contentUrl)}" controls autoplay></video>`;
  } else if (type === "audio") {
    mediaModalBody.innerHTML = `<audio src="${escapeHtml(contentUrl)}" controls autoplay></audio>`;
  } else {
    return;
  }

  mediaModal.classList.remove("d-none");
  document.body.style.overflow = "hidden";
}

function closeMediaModal() {
  mediaModal.classList.add("d-none");
  document.body.style.overflow = "";

  const video = mediaModalBody.querySelector("video");
  const audio = mediaModalBody.querySelector("audio");
  if (video) video.pause();
  if (audio) audio.pause();

  mediaModalBody.innerHTML = "";
}

mediaModalClose.onclick = closeMediaModal;

mediaModal.querySelector(".media-modal-backdrop").onclick = closeMediaModal;

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !mediaModal.classList.contains("d-none")) {
    closeMediaModal();
  }
});

/* ── Downloads browser ── */

function renderBreadcrumbs(path) {
  const segments = path ? path.split("/").filter(Boolean) : [];
  const crumbs = [
    `<button type="button" class="btn btn-link p-0 breadcrumb-btn" data-path="">root</button>`
  ];

  let accumulatedPath = "";
  for (const segment of segments) {
    accumulatedPath = accumulatedPath ? `${accumulatedPath}/${segment}` : segment;
    crumbs.push(
      `<span class="px-1">/</span><button type="button" class="btn btn-link p-0 breadcrumb-btn" data-path="${escapeHtml(accumulatedPath)}">${escapeHtml(segment)}</button>`
    );
  }

  downloadsBreadcrumbs.innerHTML = crumbs.join("");

  downloadsBreadcrumbs.querySelectorAll(".breadcrumb-btn").forEach((button) => {
    button.onclick = () => {
      loadDownloads(button.getAttribute("data-path") || "");
    };
  });
}

function renderDownloadsTable(data) {
  currentDownloadsPath = data.path || "";
  downloadsRoot.textContent = `Download root: ${data.root}`;
  renderBreadcrumbs(currentDownloadsPath);

  // Update "Download All as ZIP" link to reflect current folder
  const downloadAllZip = document.getElementById("download-all-zip");
  downloadAllZip.href = `/gallery-dl/files/archive?path=${pathToParam(currentDownloadsPath)}`;

  const rows = [];
  if (currentDownloadsPath) {
    rows.push(`
      <tr>
        <td>
          <button class="btn btn-link p-0 folder-link" type="button" data-path="${escapeHtml(data.parent || "")}">
            <i class="bi bi-arrow-up-circle"></i> ..
          </button>
        </td>
        <td>Directory</td>
        <td>-</td>
        <td>-</td>
        <td></td>
      </tr>
    `);
  }

  for (const entry of data.entries) {
    const entryName = escapeHtml(entry.name);
    const entryPath = escapeHtml(entry.path);

    if (entry.is_dir) {
      rows.push(`
        <tr>
          <td>
            <button class="btn btn-link p-0 folder-link" type="button" data-path="${entryPath}">
              <i class="bi bi-folder-fill"></i> ${entryName}
            </button>
          </td>
          <td>Directory</td>
          <td>-</td>
          <td>${formatTimestamp(entry.modified)}</td>
          <td class="text-end text-nowrap">
            <a class="btn btn-sm btn-custom" href="/gallery-dl/files/archive?path=${pathToParam(entry.path)}" title="Download folder as ZIP"><i class="bi bi-file-earmark-zip"></i></a>
          </td>
        </tr>
      `);
    } else {
      const mediaType = getMediaType(entry.name);
      const icon = getFileIcon(entry.name);

      let nameCell;
      if (mediaType) {
        nameCell = `<button class="media-preview-btn" type="button" data-name="${entryName}" data-path="${entryPath}">${icon} ${entryName}</button>`;
      } else {
        nameCell = `${icon} ${entryName}`;
      }

      const previewBtn = mediaType
        ? `<button class="btn btn-sm btn-custom media-open-btn" type="button" data-name="${entryName}" data-path="${entryPath}" title="Preview"><i class="bi bi-eye"></i></button>`
        : "";

      rows.push(`
        <tr>
          <td>${nameCell}</td>
          <td>File</td>
          <td>${formatBytes(entry.size)}</td>
          <td>${formatTimestamp(entry.modified)}</td>
          <td class="text-end text-nowrap">
            ${previewBtn}
            <a class="btn btn-sm btn-custom" target="_blank" rel="noopener noreferrer" href="/gallery-dl/files/content?path=${pathToParam(entry.path)}">Open</a>
            <a class="btn btn-sm btn-custom" href="/gallery-dl/files/download?path=${pathToParam(entry.path)}">Download</a>
          </td>
        </tr>
      `);
    }
  }

  if (!rows.length) {
    rows.push(`
      <tr>
        <td colspan="5" class="text-center py-3">No files found in this folder.</td>
      </tr>
    `);
  }

  downloadsBody.innerHTML = rows.join("");

  downloadsBody.querySelectorAll(".folder-link").forEach((button) => {
    button.onclick = () => {
      loadDownloads(button.getAttribute("data-path") || "");
    };
  });

  downloadsBody.querySelectorAll(".media-preview-btn, .media-open-btn").forEach((button) => {
    button.onclick = () => {
      openMediaModal(button.dataset.name, button.dataset.path);
    };
  });
}

async function loadDownloads(path = "") {
  try {
    const response = await fetch(`/gallery-dl/files?path=${pathToParam(path)}`, {
      method: "GET",
      headers: {
        "Cache-Control": "no-cache"
      }
    });

    if (!response.ok) {
      throw new Error(`Response status: ${response.status}`);
    }

    const data = await response.json();

    if (!data.success) {
      throw new Error(data.error || "Failed to load downloads");
    }

    renderDownloadsTable(data);
  }
  catch (error) {
    downloadsRoot.textContent = "Unable to load downloads.";
    downloadsBreadcrumbs.textContent = "";
    downloadsBody.innerHTML = `
      <tr>
        <td colspan="5" class="text-center py-3">${escapeHtml(error.message)}</td>
      </tr>
    `;
  }
}

refreshDownloadsButton.onclick = () => loadDownloads(currentDownloadsPath);

const successAlert = Swal.mixin({
  animation: true,
  position: "top-end",
  icon: "success",
  iconColor: "#550572",
  color: "#550572",
  showConfirmButton: false,
  confirmButtonText: "OK",
  confirmButtonColor: "#550572",
  showCloseButton: true,
  closeButtonHtml: "&times;",
  target: "body",
  timer: 3000,
  timerProgressBar: true,
  toast: true,
  didOpen: (toast) => {
    toast.onmouseenter = Swal.stopTimer;
    toast.onmouseleave = Swal.resumeTimer;
  }
});

form.onsubmit = async (event) => {
  event.preventDefault();

  if (ws.readyState === WebSocket.CLOSED) {
    connectWebSocket();
  }

  const formData = new FormData(event.target);
  const url = formData.get("url");

  try {
    const response = await fetch("/gallery-dl/q", {
      method: "POST",
      body: formData
    });

    if (!response.ok) {
      throw new Error(`Response status: ${response.status}`);
    }

    const data = await response.json();
    console.log(data);

    event.target.url.value = "";

    if (url) {
      successAlert.fire({
        title: "Success!",
        html: `Added
          <a href="${url}" target="_blank" rel="noopener noreferrer">one item</a>
          to the download queue.`
      });

      // Refresh view shortly after submit so newly finished downloads appear.
      setTimeout(() => loadDownloads(currentDownloadsPath), 1200);
    }
  }
  catch (error) {
    console.error(error);
  }
};

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
        "Expires": "0"
      }
    });

    if (!response.ok) {
      throw new Error(`Response status: ${response.status}`);
    }

    const logs = await response.text();

    if (box.textContent != logs) {
      box.textContent = logs;
      box.scrollTop = box.scrollHeight;
    }

    if (!isConnected) {
      connectWebSocket();
    }
  }
  catch (error) {
    console.error(error.message);
  }
}

function connectWebSocket(allowReconnect = true) {
  const protocol = window.location.protocol === "https:" ? "wss://" : "ws://";
  const host = window.location.host;
  const url = `${protocol}${host}/ws/logs`;

  let lastLine = "";
  let lastPos = localStorage.getItem("lastPos") ? parseInt(localStorage.getItem("lastPos")) : 0;

  ws = new WebSocket(url);

  ws.onopen = () => {
    console.log("WebSocket connection established.");
    isConnected = true;
  };

  ws.onmessage = (event) => {
    const newLines = event.data.split("\n").filter(Boolean);
    if (!newLines.length) return;

    const lines = box.textContent.split("\n").filter(Boolean);

    lastLine = lastPos ? lines[lastPos] : lines[lines.length - 1] || null;

    const isLastLineProgress = lastLine?.includes("B/s");
    const isNewLineProgress = newLines[0].includes("B/s");

    if (newLines.length > 1 && isNewLineProgress && newLines[1].includes("B/s")) {
      newLines.pop();
    }

    let progressUpdate = false;

    if (isLastLineProgress && isNewLineProgress) {
      progressUpdate = true;
      lastPos = lastPos || lines.length - 1;
      lines[lastPos] = newLines[0];
    }
    else if (isLastLineProgress && !isNewLineProgress) {
      lastPos = 0;
    }

    lines.push(...newLines.slice(progressUpdate ? 1 : 0));

    box.textContent = lines.join("\n") + "\n";

    localStorage.setItem("lastPos", lastPos);

    if (!progressUpdate || newLines.length > 1) {
      box.scrollTop = box.scrollHeight;
    }
  };

  ws.onerror = (event) => {
    console.error("WebSocket error:", event);
  };

  ws.onclose = () => {
    if (isConnected) {
      isConnected = false;

      if (isPageAlive && allowReconnect) {
        console.log("WebSocket connection closed. Attempting to reconnect...");
        setTimeout(() => connectWebSocket(allowReconnect), 2000);
      }
    } else {
      console.log("WebSocket connection could not be established.");
    }
  };
}

fetchLogs();
loadDownloads();

window.onbeforeunload = () => {
  isPageAlive = false;

  ws.close(1000, "User is leaving the page");

  if (localStorage.getItem("logs") == "shown") {
    saveBox();
  }
};
