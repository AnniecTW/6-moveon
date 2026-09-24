(() => {
  const MAX_PHOTOS = 8;
  const MAX_FILE_SIZE = 5 * 1024 * 1024;
  const MAX_PARALLEL_UPLOADS = 3;
  const ALLOWED_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);
  const ALLOWED_EXTENSIONS = /\.(jpe?g|png|webp)$/i;
  const DRAG_TYPE = "application/x-moveon-listing-photo";

  const form = document.getElementById("listing-form");
  const surface = document.querySelector("[data-photo-surface]");
  const emptyState = document.querySelector("[data-photo-empty]");
  const grid = document.querySelector("[data-photo-grid]");
  const fileInput = document.getElementById("photo-file-input");
  const emptyPrompt = document.querySelector("[data-photo-prompt]");
  const emptySubtext = document.querySelector("[data-photo-subtext]");
  const idsInput = document.getElementById("id_image_ids");
  const urlInput = document.getElementById("photo-url-input");
  const urlAddButton = document.querySelector("[data-photo-url-add]");
  const counter = document.querySelector("[data-photo-count]");
  const message = document.querySelector("[data-photo-message]");
  const uploadUrl = surface?.dataset.uploadUrl;
  if (!form || !surface || !emptyState || !grid || !fileInput || !idsInput || !uploadUrl) return;

  let photos = [];
  let activeUploads = 0;
  const uploadQueue = [];
  const uploadingListeners = new Set();

  const csrfToken = () => form.querySelector("[name=csrfmiddlewaretoken]")?.value || "";
  const isUploading = () => activeUploads > 0 || uploadQueue.length > 0;

  function notifyUploading() {
    uploadingListeners.forEach((listener) => listener(isUploading()));
  }

  function announce(text, isError = false) {
    if (!message) return;
    message.textContent = text;
    message.classList.toggle("is-error", isError);
  }

  function syncIds() {
    idsInput.value = photos
      .filter((photo) => photo.status === "done" && photo.id !== undefined)
      .map((photo) => photo.id)
      .join(",");
  }

  function photoSource(photo) {
    return photo.localPreviewUrl || photo.url || "";
  }

  function releasePreview(photo) {
    if (photo.localPreviewUrl) URL.revokeObjectURL(photo.localPreviewUrl);
    photo.localPreviewUrl = null;
  }

  function render() {
    const hasPhotos = photos.length > 0;
    emptyState.hidden = hasPhotos;
    grid.hidden = !hasPhotos;
    surface.classList.toggle("has-photos", hasPhotos);
    surface.classList.toggle("is-full", photos.length >= MAX_PHOTOS);
    counter.textContent = `${photos.length} / ${MAX_PHOTOS} photos`;
    grid.replaceChildren();

    photos.forEach((photo, index) => {
      const tile = document.createElement("article");
      tile.className = `photo-tile${index === 0 ? " is-cover" : ""}${photo.status === "error" ? " has-error" : ""}${photo.status === "uploading" ? " is-uploading" : ""}`;
      tile.dataset.photoIndex = String(index);
      tile.draggable = true;
      tile.tabIndex = 0;
      tile.setAttribute("aria-label", `Listing photo ${index + 1}${index === 0 ? ", cover" : ""}. Use Alt plus Left or Right to reorder.`);

      const imageUrl = photoSource(photo);
      if (imageUrl) {
        const image = document.createElement("img");
        image.src = imageUrl;
        image.alt = `Listing photo ${index + 1}`;
        tile.append(image);
      } else {
        const placeholder = document.createElement("span");
        placeholder.className = "photo-tile-placeholder";
        placeholder.textContent = "Image preview unavailable";
        tile.append(placeholder);
      }

      if (index === 0) {
        const badge = document.createElement("span");
        badge.className = "photo-cover-badge";
        badge.textContent = "Cover";
        tile.append(badge);
      }

      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "photo-remove-button";
      remove.setAttribute("aria-label", `Remove photo ${index + 1}`);
      remove.title = `Remove photo ${index + 1}`;
      remove.textContent = "×";
      remove.addEventListener("click", () => removePhoto(photo));
      tile.append(remove);

      if (index > 0 && photo.status !== "error") {
        const cover = document.createElement("button");
        cover.type = "button";
        cover.className = "photo-make-cover";
        cover.textContent = "Make cover";
        cover.setAttribute("aria-label", `Make photo ${index + 1} the cover`);
        cover.addEventListener("click", () => movePhoto(index, 0));
        tile.append(cover);
      }

      if (photo.status === "uploading") {
        const loading = document.createElement("span");
        loading.className = "photo-tile-loading";
        loading.setAttribute("role", "status");
        loading.setAttribute("aria-label", `Uploading photo ${index + 1}`);
        loading.innerHTML = '<span class="photo-spinner" aria-hidden="true"></span><span>Uploading</span>';
        tile.append(loading);
      }

      if (photo.status === "error") {
        const errorPanel = document.createElement("div");
        errorPanel.className = "photo-tile-error";
        errorPanel.setAttribute("role", "alert");
        const errorText = document.createElement("span");
        errorText.textContent = photo.error || "Upload failed.";
        const retry = document.createElement("button");
        retry.type = "button";
        retry.textContent = "Retry";
        retry.setAttribute("aria-label", `Retry upload for photo ${index + 1}`);
        retry.addEventListener("click", () => retryPhoto(photo));
        errorPanel.append(errorText, retry);
        tile.append(errorPanel);
      }

      tile.addEventListener("keydown", (event) => {
        if (!event.altKey || !["ArrowLeft", "ArrowRight"].includes(event.key)) return;
        event.preventDefault();
        movePhoto(index, index + (event.key === "ArrowLeft" ? -1 : 1));
        grid.querySelector(`[data-photo-index="${Math.min(index + (event.key === "ArrowLeft" ? -1 : 1), photos.length - 1)}"]`)?.focus();
      });
      tile.addEventListener("dragstart", (event) => {
        event.dataTransfer.setData(DRAG_TYPE, String(index));
        event.dataTransfer.effectAllowed = "move";
        tile.classList.add("is-moving");
      });
      tile.addEventListener("dragend", () => {
        tile.classList.remove("is-moving");
        grid.querySelectorAll(".is-drop-target").forEach((node) => node.classList.remove("is-drop-target"));
        grid.querySelectorAll(".is-drop-after").forEach((node) => node.classList.remove("is-drop-after"));
      });
      tile.addEventListener("dragover", (event) => {
        if (!Array.from(event.dataTransfer.types).includes(DRAG_TYPE)) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        const bounds = tile.getBoundingClientRect();
        tile.classList.toggle("is-drop-after", event.clientX > bounds.left + bounds.width / 2);
        tile.classList.add("is-drop-target");
      });
      tile.addEventListener("dragleave", () => tile.classList.remove("is-drop-target", "is-drop-after"));
      tile.addEventListener("drop", (event) => {
        if (!Array.from(event.dataTransfer.types).includes(DRAG_TYPE)) return;
        event.preventDefault();
        event.stopPropagation();
        const from = Number(event.dataTransfer.getData(DRAG_TYPE));
        const target = Number(tile.dataset.photoIndex);
        const after = event.clientX > tile.getBoundingClientRect().left + tile.getBoundingClientRect().width / 2;
        const insertionPoint = target + (after ? 1 : 0);
        movePhoto(from, insertionPoint > from ? insertionPoint - 1 : insertionPoint);
      });
      grid.append(tile);
    });

    if (photos.length < MAX_PHOTOS) {
      const addTile = document.createElement("button");
      addTile.type = "button";
      addTile.className = "photo-add-tile";
      addTile.setAttribute("aria-label", "Add photos. Press Enter or Space to browse.");
      addTile.innerHTML = '<span aria-hidden="true">+</span><span>Add</span>';
      addTile.addEventListener("click", () => fileInput.click());
      grid.append(addTile);
    }
  }

  function persistAndRender() {
    syncIds();
    render();
    notifyUploading();
  }

  function movePhoto(from, destination) {
    if (from < 0 || from >= photos.length) return;
    const [photo] = photos.splice(from, 1);
    const nextPosition = Math.max(0, Math.min(destination, photos.length));
    photos.splice(nextPosition, 0, photo);
    persistAndRender();
    announce(`Photo moved to position ${nextPosition + 1}`);
  }

  function removePhoto(photo) {
    const index = photos.indexOf(photo);
    if (index < 0) return;
    photos.splice(index, 1);
    for (let queuedIndex = uploadQueue.length - 1; queuedIndex >= 0; queuedIndex -= 1) {
      if (uploadQueue[queuedIndex] === photo) uploadQueue.splice(queuedIndex, 1);
    }
    releasePreview(photo);
    persistAndRender();
  }

  async function sendUpload(photo) {
    const body = new FormData();
    if (photo.file) body.append("file", photo.file);
    else body.append("url", photo.sourceUrl);
    const response = await fetch(uploadUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken() },
      body,
    });
    let result;
    try {
      result = await response.json();
    } catch (_error) {
      throw new Error("The server returned an unreadable response.");
    }
    if (!response.ok) throw new Error(result.error || "The image could not be uploaded.");
    return result;
  }

  function pumpQueue() {
    while (activeUploads < MAX_PARALLEL_UPLOADS && uploadQueue.length) {
      const photo = uploadQueue.shift();
      activeUploads += 1;
      sendUpload(photo)
        .then((result) => {
          if (!photos.includes(photo)) return;
          photo.id = result.id;
          photo.url = result.url;
          photo.status = "done";
          photo.error = "";
          releasePreview(photo);
        })
        .catch((error) => {
          if (!photos.includes(photo)) return;
          photo.status = "error";
          photo.error = error.message || "The image could not be uploaded.";
        })
        .finally(() => {
          activeUploads -= 1;
          persistAndRender();
          pumpQueue();
        });
    }
    notifyUploading();
  }

  function enqueue(photo) {
    photo.status = "uploading";
    photo.error = "";
    uploadQueue.push(photo);
    persistAndRender();
    pumpQueue();
  }

  function fileError(file, text) {
    photos.push({ file, url: "", status: "error", error: text });
  }

  function addFiles(fileList) {
    const files = Array.from(fileList || []);
    if (!files.length) return;
    const available = Math.max(0, MAX_PHOTOS - photos.length);
    const accepted = files.slice(0, available);
    if (files.length > available) announce("You can add up to 8 photos.");

    accepted.forEach((file) => {
      if ((file.type && !ALLOWED_TYPES.has(file.type)) || (!file.type && !ALLOWED_EXTENSIONS.test(file.name))) {
        fileError(file, "Use a JPG, PNG, or WEBP image.");
        return;
      }
      if (file.size > MAX_FILE_SIZE) {
        fileError(file, "Image must be 5MB or smaller.");
        return;
      }
      photos.push({ file, url: "", localPreviewUrl: URL.createObjectURL(file), status: "uploading", error: "" });
      enqueue(photos[photos.length - 1]);
    });
    persistAndRender();
  }

  function isHttpUrl(value) {
    try {
      return ["http:", "https:"].includes(new URL(value).protocol);
    } catch (_error) {
      return false;
    }
  }

  function addUrl(value) {
    const url = value.trim();
    if (!url) return;
    if (!isHttpUrl(url)) {
      announce("Enter a valid http or https photo URL.", true);
      return;
    }
    if (photos.length >= MAX_PHOTOS) {
      announce("You can add up to 8 photos.");
      return;
    }
    const photo = { sourceUrl: url, url, status: "uploading", error: "" };
    photos.push(photo);
    urlInput.value = "";
    announce("");
    enqueue(photo);
  }

  function retryPhoto(photo) {
    if (!photos.includes(photo)) return;
    enqueue(photo);
  }

  emptyState.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => {
    addFiles(fileInput.files);
    fileInput.value = "";
  });
  urlAddButton?.addEventListener("click", () => addUrl(urlInput.value));
  urlInput?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    addUrl(urlInput.value);
  });

  surface.addEventListener("dragenter", (event) => {
    if (Array.from(event.dataTransfer.types).includes(DRAG_TYPE)) return;
    event.preventDefault();
    surface.classList.add("is-dragging");
    if (photos.length === 0) {
      emptyPrompt.textContent = "Drop to upload";
      emptySubtext.textContent = "Release to add these photos";
    }
  });
  surface.addEventListener("dragover", (event) => {
    const types = Array.from(event.dataTransfer.types);
    if (types.includes(DRAG_TYPE)) return;
    if (types.includes("Files") || types.includes("text/uri-list") || types.includes("text/plain")) {
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
      surface.classList.add("is-dragging");
    }
  });
  surface.addEventListener("dragleave", (event) => {
    if (surface.contains(event.relatedTarget)) return;
    surface.classList.remove("is-dragging");
    if (photos.length === 0) {
      emptyPrompt.textContent = "Add photos";
      emptySubtext.textContent = "Drop images here, or click to browse";
    }
  });
  surface.addEventListener("drop", (event) => {
    if (Array.from(event.dataTransfer.types).includes(DRAG_TYPE)) return;
    event.preventDefault();
    surface.classList.remove("is-dragging");
    if (photos.length === 0) {
      emptyPrompt.textContent = "Add photos";
      emptySubtext.textContent = "Drop images here, or click to browse";
    }
    if (event.dataTransfer.files.length) {
      addFiles(event.dataTransfer.files);
      return;
    }
    const raw = event.dataTransfer.getData("text/uri-list") || event.dataTransfer.getData("text/plain");
    const url = raw.split(/\r?\n/).map((line) => line.trim()).find((line) => line && !line.startsWith("#") && isHttpUrl(line));
    if (url) addUrl(url);
    else if (raw) announce("Drop an image file or an http(s) image URL.", true);
  });
  window.addEventListener("dragover", (event) => event.preventDefault());
  window.addEventListener("drop", (event) => event.preventDefault());
  document.addEventListener("paste", (event) => {
    const files = Array.from(event.clipboardData?.files || []).filter((file) => file.type.startsWith("image/"));
    if (!files.length) return;
    event.preventDefault();
    addFiles(files);
  });
  window.addEventListener("beforeunload", () => photos.forEach(releasePreview));
  document.querySelectorAll(".ai-suggestion, .ai-benchmark").forEach((chip) => {
    chip.addEventListener("click", (event) => {
      if (event.target.closest("button")) return;
      chip.querySelector(".ai-range")?.click();
    });
  });

  const initialPhotos = JSON.parse(document.getElementById("initial-photos")?.textContent || "[]");
  photos = initialPhotos.slice(0, MAX_PHOTOS).map((photo) => ({
    id: photo.id,
    url: photo.url,
    status: "done",
    error: "",
  }));
  syncIds();
  render();
  window.listingPhotos = {
    isUploading,
    onUploadingChange(listener) {
      uploadingListeners.add(listener);
      listener(isUploading());
    },
  };
})();
