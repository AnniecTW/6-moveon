/* MoveOn Messaging: native handoff view connected to Django APIs. */
(function () {
  "use strict";

  /* ==========================================================
     1. CONSTANTS & CONFIG
     ========================================================== */
  const ATTACH_LIMITS = { maxCount: 3, maxBytes: 10 * 1024 * 1024 };
  const config = JSON.parse(document.getElementById("messaging-config").textContent);
  const endpoint = (template, id) => template.replace("__id__", encodeURIComponent(id));
  const csrf = () => document.cookie.split("; ").find((part) => part.startsWith("csrftoken="))?.split("=")[1] || "";
  async function api(url, options = {}) {
    const response = await fetch(url, { credentials: "same-origin", ...options,
      headers: { "X-CSRFToken": csrf(), ...(options.headers || {}) } });
    const result = await response.json().catch(() => ({ error: "Request failed. Please try again." }));
    if (response.status === 401 || result.code === "campus_access_required" || result.code === "login_required") {
      const error = new Error("Your campus session is no longer available. Sign in again.");
      error.code = "auth";
      throw error;
    }
    if (!response.ok) throw new Error(result.error || "Request failed. Please try again.");
    return result;
  }

  const STATUS_LABEL = { awaiting: "Awaiting response", accepted: "Accepted", declined: "Declined" };

  /* ==========================================================
     2. STATE (in-memory only)
     ========================================================== */
  const state = {
    conversations: [],
    activeId: null,
    filter: "all",
    search: "",
    drafts: new Map(),        // convId -> draft text (NOT localStorage)
    pendingAttachments: new Map(), // convId -> [{id, file, url, status, uploadedId}]
    history: new Map(), // convId -> {nextBefore, hasMore}
    readInFlight: new Set(),
    readDone: new Set(),
    loadingHistory: false,
    polling: false,
    selectionVersion: 0,
    reqUi: {},                // requestId -> { mode, decision, error } inline action UI
  };

  // Root + cached DOM references (filled in bootstrap()).
  const dom = {};
  let imageScale = 1;
  function openImage(src) {
    if (!dom.imageViewer || !dom.imageViewerImage) return;
    imageScale = 1;
    dom.imageViewerImage.style.transform = "scale(1)";
    dom.imageViewerImage.src = src;
    dom.imageViewer.showModal();
  }
  function showError(message) {
    if (!dom.notice) return;
    dom.notice.hidden = false;
    dom.notice.textContent = message;
    if (message.includes("campus session")) {
      const link = document.createElement("a");
      link.href = config.account;
      link.textContent = " Sign in";
      dom.notice.appendChild(link);
    }
  }

  /* Data adapter. All URLs come from the Django page configuration. */
  const Adapter = {
    async fetchConversations() {
      return (await api(config.conversations)).conversations;
    },
    async fetchMessages(convId, query = "") {
      return api(endpoint(config.messages, convId) + query);
    },
    async markRead(convId, ids) {
      return api(endpoint(config.read, convId), { method: "POST",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ messageIds: ids }) });
    },
    async sendMessage(convId, text, imageIds, clientRequestId) {
      return api(endpoint(config.messages, convId), { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, imageIds, clientRequestId }) });
    },
    async submitRequestDecision(requestId, decision) {
      return api(endpoint(config.decision, requestId), { method: "POST",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision }) });
    },
    async uploadImage(convId, file) {
      const body = new FormData();
      body.append("conversationId", convId);
      body.append("file", file);
      return api(config.upload, { method: "POST", body });
    },
    async removeImage(id) {
      return api(endpoint(config.attachment, id), { method: "DELETE" });
    },
  };

  /* ==========================================================
     4. UTILITIES
     ========================================================== */
  function esc(str) {
    return String(str == null ? "" : str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function initials(name) {
    return String(name || "?")
      .trim()
      .split(/\s+/)
      .slice(0, 1)
      .map((w) => w[0] || "")
      .join("")
      .toUpperCase();
  }

  function money(n) {
    if (n == null) return "";
    return "$" + Number(n).toLocaleString();
  }

  function el(tag, className, html) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (html != null) node.innerHTML = html;
    return node;
  }

  // Short time for a bubble, e.g. "8:40 AM".
  function timeLabel(iso) {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }

  // Day bucket label: Today / Yesterday / Mon D, YYYY.
  function dayLabel(iso) {
    const d = new Date(iso);
    const now = new Date();
    const startOf = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
    if (d.toDateString() === now.toDateString()) return "Today";
    const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
    if (d.toDateString() === yesterday.toDateString()) return "Yesterday";
    return d.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });
  }

  function relTime(iso) {
    const d = new Date(iso);
    const now = new Date();
    if (d.toDateString() === now.toDateString()) return timeLabel(iso);
    const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
    if (d.toDateString() === yesterday.toDateString()) return "Yesterday";
    return d.toLocaleDateString([], { month: "short", day: "numeric" });
  }

  function getConversation(id) {
    return state.conversations.find((c) => c.id === id) || null;
  }

  // Small inline SVG icons (mirrors src/messaging/ui.tsx).
  const ICON = {
    alert:
      '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.46 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
    external:
      '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>',
    retry:
      '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M3 2v6h6"/><path d="M3 13a9 9 0 1 0 3-7.7L3 8"/></svg>',
    cube:
      '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>',
  };

  /* ==========================================================
     5. RENDER
     ========================================================== */

  // ----- 5a. Conversation list (left) -----
  function lastMessagePreview(conv) {
    const msgs = conv.messages || [];
    if (!msgs.length) return "No messages yet";
    const last = msgs[msgs.length - 1];
    const prefix = last.mine ? "You: " : "";
    return prefix + (last.text || (last.images && last.images.length ? "Photo" : ""));
  }

  function matchesFilter(conv) {
    if (state.filter === "buying") return conv.role === "buyer";
    if (state.filter === "selling") return conv.role === "seller";
    return true;
  }

  function matchesSearch(conv) {
    const q = state.search.trim().toLowerCase();
    if (!q) return true;
    // Search matches listing title + contact display name ONLY.
    const title = ((conv.listing && conv.listing.title) || "").toLowerCase();
    const name = ((conv.contact && conv.contact.displayName) || "").toLowerCase();
    return title.includes(q) || name.includes(q);
  }

  // Listing thumbnail: image when available, otherwise an initial fallback.
  function thumb(className, listing) {
    const t = el("div", className);
    if (listing && listing.imageUrl) {
      const im = document.createElement("img");
      im.src = listing.imageUrl;
      im.alt = listing.title || "";
      t.appendChild(im);
    } else {
      t.textContent = initials((listing && listing.title) || "?");
    }
    return t;
  }

  function bundleNoteText(conv) {
    const reqs = conv.bundleRequests || [];
    if (!reqs.length) return null;
    if (reqs.length > 1) return "Bundle request · " + reqs.length + " requests";
    return "Bundle request · " + (STATUS_LABEL[reqs[0].status] || reqs[0].status);
  }

  function renderList() {
    const list = dom.list;
    list.innerHTML = "";
    const visible = state.conversations
      .filter(matchesFilter)
      .filter(matchesSearch)
      .sort((a, b) => new Date(b.lastActivity) - new Date(a.lastActivity));

    if (!visible.length) {
      const emptyInbox = state.conversations.length === 0;
      const li = el("li", "messaging__list-empty");
      li.appendChild(
        el("div", "messaging__list-empty-title", emptyInbox ? "Your inbox is empty" : "No matches")
      );
      li.appendChild(
        el(
          "div",
          "messaging__list-empty-body",
          emptyInbox
            ? "Conversations about your listings and bundle requests will show up here."
            : "No conversations match your search."
        )
      );
      list.appendChild(li);
      return;
    }

    visible.forEach((conv) => {
      const row = el("li", "messaging__row");
      row.dataset.convId = conv.id;
      if (conv.id === state.activeId) row.classList.add("is-active");

      row.appendChild(thumb("messaging__thumb", conv.listing));

      const main = el("div", "messaging__row-main");

      // Top: listing title + relative time.
      const top = el("div", "messaging__row-top");
      top.appendChild(el("span", "messaging__row-name", esc(conv.listing.title)));
      top.appendChild(el("span", "messaging__row-time", esc(relTime(conv.lastActivity))));
      main.appendChild(top);

      // Contact + role tag.
      const contact = el("div", "messaging__row-contact");
      contact.appendChild(el("span", "messaging__row-contact-name", esc(conv.contact.displayName)));
      contact.appendChild(el("span", "messaging__tag", conv.role === "seller" ? "Selling" : "Buying"));
      main.appendChild(contact);

      // Bottom: failed alert + preview + unread pill.
      const bottom = el("div", "messaging__row-bottom");
      const msgs = conv.messages || [];
      const last = msgs[msgs.length - 1];
      if (last && last.status === "failed") {
        bottom.appendChild(el("span", "messaging__row-alert", ICON.alert));
      }
      bottom.appendChild(el("p", "messaging__row-preview", esc(lastMessagePreview(conv))));
      if (conv.unreadCount > 0) {
        bottom.appendChild(el("span", "messaging__unread", String(conv.unreadCount)));
      }
      main.appendChild(bottom);

      // Bundle-request note.
      const note = bundleNoteText(conv);
      if (note) main.appendChild(el("div", "messaging__row-bundle", esc(note)));

      row.appendChild(main);
      list.appendChild(row);
    });
  }

  // ----- 5b. Chat header (listing / contact) -----
  function renderChatHeader(conv) {
    const h = dom.chatHeader;
    h.innerHTML = "";
    const listing = conv.listing;

    h.appendChild(thumb("messaging__chat-thumb", listing));

    const info = el("div", "messaging__chat-listing");
    const titleRow = el("div", "messaging__chat-title-row");
    titleRow.appendChild(el("span", "messaging__chat-title", esc(listing.title)));
    if (listing.available === false) {
      titleRow.appendChild(
        el("span", "messaging__badge-unavailable", esc(listing.unavailableReason || "Unavailable"))
      );
    }
    info.appendChild(titleRow);

    // "Listed $X · with Name" — price comes from listing data, never chat.
    const subParts = [];
    if (listing.listedPrice != null) subParts.push("Listed " + money(listing.listedPrice));
    subParts.push("with " + conv.contact.displayName);
    info.appendChild(el("div", "messaging__chat-sub", esc(subParts.join(" · "))));
    h.appendChild(info);

    // View Listing (only when the listing is still available).
    if (listing.available !== false) {
      const link = el("a", "messaging__view-listing", "View Listing " + ICON.external);
      link.href = config.home + "?q=" + encodeURIComponent(listing.title) + "#listing-" + encodeURIComponent(listing.id);
      link.textContent = "View listing";
      h.appendChild(link);
    } else {
      h.appendChild(el("span", "messaging__view-unavailable", "Listing unavailable"));
    }
  }

  // ----- 5c. Thread (request cards + day-grouped bubbles) -----
  function renderThread(conv, forceBottom = false, prepended = false) {
    const thread = dom.thread;
    const nearBottom = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 80;
    const oldTop = thread.scrollTop;
    const oldHeight = thread.scrollHeight;
    thread.innerHTML = "";

    const history = state.history.get(conv.id);
    if (history?.hasMore) {
      const older = el("button", "messaging__load-earlier", "Load earlier messages");
      older.type = "button";
      older.addEventListener("click", () => loadHistory(conv.id));
      thread.appendChild(older);
    }

    // Bundle request cards render at the top of the thread.
    (conv.bundleRequests || []).forEach((req) => {
      thread.appendChild(renderRequestCard(conv, req));
    });

    // Messages grouped by day.
    let lastDay = null;
    (conv.messages || []).forEach((msg) => {
      const label = dayLabel(msg.timestamp);
      if (label !== lastDay) {
        thread.appendChild(el("div", "messaging__day", "<span>" + esc(label) + "</span>"));
        lastDay = label;
      }
      thread.appendChild(renderMessage(conv, msg));
    });

    if (forceBottom || nearBottom) thread.scrollTop = thread.scrollHeight;
    else thread.scrollTop = oldTop + (prepended ? Math.max(0, thread.scrollHeight - oldHeight) : 0);
    requestAnimationFrame(markVisibleRead);
  }

  function renderMessage(conv, msg) {
    const side = msg.mine ? "mine" : "theirs";
    const wrap = el("div", "messaging__msg messaging__msg--" + side);

    const bubble = el("div", "messaging__bubble");
    bubble.dataset.msgId = msg.id;
    if (msg.status === "sending") bubble.classList.add("is-sending");
    if (msg.text) bubble.appendChild(el("div", "messaging__bubble-text", esc(msg.text)));
    if (msg.images && msg.images.length) {
      const imgs = el("div", "messaging__bubble-images");
      msg.images.forEach((src) => {
        const button = document.createElement("button");
        button.type = "button";
        button.setAttribute("aria-label", "Enlarge image attachment");
        const im = document.createElement("img");
        im.src = src;
        im.alt = "attachment";
        button.appendChild(im);
        button.addEventListener("click", () => openImage(src));
        imgs.appendChild(button);
      });
      bubble.appendChild(imgs);
    }
    wrap.appendChild(bubble);

    // Meta row: time + sending/failed status + retry.
    const meta = el("div", "messaging__meta");
    meta.appendChild(el("span", "messaging__meta-time", esc(timeLabel(msg.timestamp))));
    if (msg.mine && msg.status === "waiting") {
      meta.appendChild(el("span", "messaging__meta-sending", "· Waiting for image…"));
    } else if (msg.mine && msg.status === "sending") {
      meta.appendChild(el("span", "messaging__meta-sending", "· Sending…"));
    } else if (msg.mine && msg.status === "failed") {
      meta.appendChild(el("span", "messaging__meta-failed", ICON.alert + " Not sent"));
      const retry = el("button", "messaging__retry", ICON.retry + " Retry");
      retry.type = "button";
      retry.addEventListener("click", () => retrySend(conv.id, msg.id));
      meta.appendChild(retry);
    }
    wrap.appendChild(meta);
    return wrap;
  }

  // ----- 5d. Bundle request card -----
  function renderRequestCard(conv, req) {
    const card = el("div", "messaging__request-card");
    card.dataset.requestId = req.requestId;

    // Top row: icon + fixed "Bundle request" label + meta, then status pill.
    const top = el("div", "messaging__request-top");
    const head = el("div", "messaging__request-head");
    head.appendChild(el("span", "messaging__request-icon", ICON.cube));
    const headText = el("div");
    headText.appendChild(el("div", "messaging__request-label", "Bundle request"));
    headText.appendChild(
      el("div", "messaging__request-meta", esc(req.bundleLabel + " · " + req.itemCount + " items"))
    );
    head.appendChild(headText);
    top.appendChild(head);
    top.appendChild(
      el(
        "span",
        "messaging__status-pill messaging__status-pill--" + req.status,
        esc(STATUS_LABEL[req.status] || req.status)
      )
    );
    card.appendChild(top);

    // Requested price is a DISTINCT field from the listing's listed price.
    const priceRow = el("div", "messaging__request-price-row");
    priceRow.appendChild(el("span", "messaging__request-price-label", "Requested price"));
    priceRow.appendChild(el("span", "messaging__request-price", esc(money(req.requestedPrice))));
    card.appendChild(priceRow);

    // Seller actions — only while awaiting a response (see TRANSACTION RULES).
    if (canDecide(conv, req)) {
      card.appendChild(renderRequestActions(conv, req));
    }
    return card;
  }

  // Inline accept/decline flow: idle -> confirming -> processing -> result / failed.
  function renderRequestActions(conv, req) {
    const ui = state.reqUi[req.requestId] || { mode: "idle", decision: null, error: null };
    const body = el("div", "messaging__request-body");

    if (ui.mode === "processing") {
      const p = el("div", "messaging__request-processing");
      p.appendChild(el("span", "messaging__spinner"));
      p.appendChild(document.createTextNode(" Submitting your response…"));
      body.appendChild(p);
      return body;
    }

    if (ui.mode === "confirming") {
      const prompt =
        ui.decision === "accepted"
          ? "Accept this bundle request at " + money(req.requestedPrice) + "?"
          : "Decline this bundle request?";
      body.appendChild(el("div", "messaging__request-confirm", esc(prompt)));
      const actions = el("div", "messaging__request-actions");
      const yes = el("button", "messaging__btn messaging__btn--solid",
        "Yes, " + (ui.decision === "accepted" ? "accept" : "decline"));
      yes.type = "button";
      yes.addEventListener("click", () => confirmDecision(conv, req));
      const cancel = el("button", "messaging__btn", "Cancel");
      cancel.type = "button";
      cancel.addEventListener("click", () => cancelDecision(conv, req));
      actions.appendChild(yes);
      actions.appendChild(cancel);
      body.appendChild(actions);
      return body;
    }

    if (ui.mode === "failed") {
      const err = el("div", "messaging__request-error", ICON.alert + " " + esc(ui.error || "Something went wrong."));
      body.appendChild(err);
      const actions = el("div", "messaging__request-actions");
      const again = el("button", "messaging__btn messaging__btn--solid", "Try again");
      again.type = "button";
      again.addEventListener("click", () => confirmDecision(conv, req));
      const cancel = el("button", "messaging__btn", "Cancel");
      cancel.type = "button";
      cancel.addEventListener("click", () => cancelDecision(conv, req));
      actions.appendChild(again);
      actions.appendChild(cancel);
      body.appendChild(actions);
      return body;
    }

    // idle
    const actions = el("div", "messaging__request-actions");
    const accept = el("button", "messaging__btn messaging__btn--solid", "Accept request");
    accept.type = "button";
    accept.addEventListener("click", () => startDecision(conv, req, "accepted"));
    const decline = el("button", "messaging__btn", "Decline request");
    decline.type = "button";
    decline.addEventListener("click", () => startDecision(conv, req, "declined"));
    actions.appendChild(accept);
    actions.appendChild(decline);
    body.appendChild(actions);
    return body;
  }

  /* ==========================================================
     6. COMPOSER / ATTACHMENTS
     ========================================================== */
  function pending(convId = state.activeId) {
    if (!state.pendingAttachments.has(convId)) state.pendingAttachments.set(convId, []);
    return state.pendingAttachments.get(convId);
  }

  function renderAttachments() {
    const wrap = dom.attachments;
    if (!wrap) return;
    wrap.innerHTML = "";
    if (!state.activeId || !pending().length) {
      wrap.hidden = true;
      return;
    }
    wrap.hidden = false;
    pending().forEach((att) => {
      const item = el("div", "messaging__attachment");
      if (att.status === "uploading") item.classList.add("is-uploading");
      if (att.status === "failed") item.classList.add("is-failed");

      if (att.url) {
        const im = document.createElement("img");
        im.src = att.url;
        im.alt = "preview";
        item.appendChild(im);
      }
      const remove = el("button", "messaging__attachment-remove", "&times;");
      remove.type = "button";
      remove.setAttribute("aria-label", "Remove image");
      remove.addEventListener("click", () => {
        if (att.url?.startsWith("blob:")) URL.revokeObjectURL(att.url);
        state.pendingAttachments.set(state.activeId, pending().filter((a) => a.id !== att.id));
        if (att.uploadedId) Adapter.removeImage(att.uploadedId).catch(() => {});
        renderAttachments();
      });
      item.appendChild(remove);
      if (att.status === "failed") {
        const retry = el("button", "messaging__retry", "Retry upload");
        retry.type = "button";
        retry.addEventListener("click", () => uploadAttachment(att.convId, att));
        item.appendChild(retry);
      }
      if (att.status === "uploading") item.appendChild(el("span", "", "Uploading…"));
      wrap.appendChild(item);
    });
  }

  async function handleFiles(fileList) {
    const convId = state.activeId;
    if (!convId) return;
    const files = Array.from(fileList || []);
    for (const file of files) {
      if (pending(convId).length >= ATTACH_LIMITS.maxCount) {
        alert("You can attach up to " + ATTACH_LIMITS.maxCount + " images.");
        break;
      }
      if (file.size > ATTACH_LIMITS.maxBytes) {
        alert('"' + file.name + '" is larger than 10MB and was skipped.');
        continue;
      }
      if (!["image/jpeg", "image/png", "image/webp", "image/gif"].includes(file.type)) {
        alert("Choose a JPEG, PNG, WebP, or GIF image.");
        continue;
      }
      const att = { id: crypto.randomUUID(), convId, file, url: URL.createObjectURL(file), status: "uploading", uploadedId: null };
      pending(convId).push(att);
      renderAttachments();
      uploadAttachment(convId, att);
    }
  }

  async function uploadAttachment(convId, att) {
    if (att.status === "uploading" && att.uploadedId) return;
    att.status = "uploading";
    if (state.activeId === convId) renderAttachments();
    try {
      const res = await Adapter.uploadImage(convId, att.file);
      if (!pending(convId).includes(att)) {
        await Adapter.removeImage(res.id).catch(() => {});
        return;
      }
      URL.revokeObjectURL(att.url);
      att.url = res.url;
      att.uploadedId = res.id;
      att.status = "ready";
    } catch (e) {
      att.status = "failed";
      att.error = e.message;
    }
    if (state.activeId === convId) renderAttachments();
  }

  /* ==========================================================
     7. TRANSACTION RULES
     ----------------------------------------------------------
     Only a SELLER may accept/decline, and only while the request
     is still 'awaiting'. Buyers never act on their own request.
     These rules are intentionally isolated so backend-confirmed
     policy (see README "Open questions") can replace them.
     ========================================================== */
  function canDecide(conv, req) {
    return conv.role === "seller" && req.status === "awaiting";
  }

  function refreshActiveThread() {
    const conv = getConversation(state.activeId);
    if (conv) renderThread(conv);
  }

  function startDecision(conv, req, decision) {
    if (!canDecide(conv, req)) return;
    state.reqUi[req.requestId] = { mode: "confirming", decision: decision, error: null };
    refreshActiveThread();
  }

  function cancelDecision(conv, req) {
    state.reqUi[req.requestId] = { mode: "idle", decision: null, error: null };
    refreshActiveThread();
  }

  async function confirmDecision(conv, req) {
    const ui = state.reqUi[req.requestId];
    const decision = ui && ui.decision;
    if (!decision || ui.mode === "processing") return;
    state.reqUi[req.requestId] = { mode: "processing", decision: decision, error: null };
    refreshActiveThread();
    try {
      const res = await Adapter.submitRequestDecision(req.requestId, decision);
      req.status = res.status; // authoritative status from adapter/server
      state.reqUi[req.requestId] = { mode: "idle", decision: null, error: null };
      if (state.activeId === conv.id) refreshActiveThread();
      renderList();
    } catch (e) {
      state.reqUi[req.requestId] = { mode: "failed", decision: decision, error: e.message || "Couldn't submit." };
      if (state.activeId === conv.id) refreshActiveThread();
    }
  }

  /* ==========================================================
     8. EVENT WIRING
     ========================================================== */

  function composerDisabled(conv) {
    // Match the React rule: only disabled for an unavailable listing that
    // never had any messages. Otherwise the history + composer stay usable.
    return conv.listing.available === false && (conv.messages || []).length === 0;
  }

  function applyComposerState(conv) {
    if (!dom.composer) return;
    const disabled = composerDisabled(conv);
    if (dom.composerRow) dom.composerRow.hidden = disabled;
    if (dom.attachments && disabled) {
      dom.attachments.hidden = true;
      dom.attachments.innerHTML = "";
    }
    // Lazily create the "listing unavailable" note element.
    if (!dom.composerNote) {
      dom.composerNote = el(
        "div",
        "messaging__composer-note",
        "This listing is no longer available. The conversation history is kept for reference."
      );
      dom.composer.appendChild(dom.composerNote);
    }
    dom.composerNote.hidden = !disabled;
    dom.composer.classList.toggle("messaging__composer--disabled", disabled);
  }

  async function selectConversation(id) {
    const version = ++state.selectionVersion;
    // Preserve the draft of the conversation we're leaving.
    if (state.activeId && dom.messageInput) {
      state.drafts.set(state.activeId, dom.messageInput.value);
    }
    const conv = getConversation(id);
    if (!conv) return;

    state.activeId = id;

    dom.chatEmpty.hidden = true;
    dom.chatInner.hidden = false;

    renderChatHeader(conv);
    renderThread(conv, true);
    renderAttachments();
    applyComposerState(conv);

    // Restore this conversation's draft (in-memory only).
    if (dom.messageInput) {
      dom.messageInput.value = state.drafts.get(id) || "";
      dom.messageInput.focus();
    }

    renderList(); // refresh active highlight + unread pills
    try {
      const page = await Adapter.fetchMessages(id);
      if (state.activeId !== id || state.selectionVersion !== version) return;
      const local = conv.messages.filter((m) => m.status === "sending" || m.status === "failed");
      conv.messages = [...page.messages, ...local.filter((m) => !page.messages.some((p) => p.clientRequestId && p.clientRequestId === m.clientRequestId))];
      state.history.set(id, { hasMore: page.hasMore, nextBefore: page.nextBefore });
      renderThread(conv, true);
      applyComposerState(conv);
      renderList();
    } catch (e) {
      if (state.activeId === id) showError(e.message);
    }
  }

  async function loadHistory(id) {
    const history = state.history.get(id);
    if (!history?.hasMore || state.loadingHistory) return;
    state.loadingHistory = true;
    try {
      const page = await Adapter.fetchMessages(id, "?before=" + encodeURIComponent(history.nextBefore));
      const conv = getConversation(id);
      if (!conv) return;
      const known = new Set(conv.messages.map((message) => message.id));
      conv.messages = [...page.messages.filter((message) => !known.has(message.id)), ...conv.messages];
      state.history.set(id, { hasMore: page.hasMore, nextBefore: page.nextBefore });
      if (state.activeId === id) renderThread(conv, false, true);
    } catch (e) {
      if (state.activeId === id) showError(e.message);
    } finally {
      state.loadingHistory = false;
    }
  }

  async function markVisibleRead() {
    if (!state.activeId || document.hidden) return;
    const conv = getConversation(state.activeId);
    if (!conv || !state.history.has(conv.id)) return;
    const bounds = dom.thread.getBoundingClientRect();
    const ids = [...dom.thread.querySelectorAll(".messaging__bubble[data-msg-id]")]
      .filter((bubble) => {
        const box = bubble.getBoundingClientRect();
        return box.bottom > bounds.top && box.top < bounds.bottom;
      })
      .map((bubble) => bubble.dataset.msgId)
      .filter((id) => /^\d+$/.test(id) && !state.readInFlight.has(id) &&
        !state.readDone.has(id) && conv.messages.some((m) => m.id === id && !m.mine));
    if (!ids.length) return;
    ids.forEach((id) => state.readInFlight.add(id));
    try {
      const result = await Adapter.markRead(conv.id, ids);
      ids.forEach((id) => state.readDone.add(id));
      conv.unreadCount = result.unreadCount;
      renderList();
      window.dispatchEvent(new Event("messaging:unread-changed"));
    } catch (e) {
      if (e.code === "auth") showError(e.message);
    } finally {
      ids.forEach((id) => state.readInFlight.delete(id));
    }
  }

  async function sendOptimistic(conv, msg) {
    if (!conv || !msg || msg.status === "sending" || msg.status === "sent") return;
    msg.status = "sending";
    if (state.activeId === conv.id) renderThread(conv);
    try {
      const res = await Adapter.sendMessage(conv.id, msg.text, msg._uploadedIds || [], msg.clientRequestId);
      const current = getConversation(conv.id) || conv;
      Object.assign(msg, res);
      current.messages = current.messages.filter((other) => other === msg || other.id !== res.id);
      current.lastActivity = res.timestamp;
      const followup = current.messages.find((other) => other.id === msg._followupId);
      if (followup?.status === "waiting") {
        if (state.activeId === conv.id) renderThread(current);
        renderList();
        await sendOptimistic(current, followup);
        return;
      }
    } catch (e) {
      msg.status = "failed";
      msg.error = e.message;
    }
    if (state.activeId === conv.id) renderThread(getConversation(conv.id) || conv);
    renderList();
  }

  async function sendCurrentMessage() {
    const conv = getConversation(state.activeId);
    if (!conv) return;
    const text = dom.messageInput.value.trim();
    const attachments = pending(conv.id);
    if (attachments.some((a) => a.status !== "ready")) {
      showError("Finish or retry image uploads before sending.");
      return;
    }
    const images = attachments;
    if (!text && !images.length) return;

    const outgoing = [];
    function queue(body, imageAttachments) {
      outgoing.push({
        id: "m-local-" + crypto.randomUUID(), clientRequestId: crypto.randomUUID(),
        mine: true, text: body, images: imageAttachments.map((a) => a.url),
        _uploadedIds: imageAttachments.map((a) => a.uploadedId),
        timestamp: new Date().toISOString(), status: "waiting",
      });
    }
    if (images.length) queue("", images);
    if (text) queue(text, []);
    if (outgoing.length === 2) outgoing[0]._followupId = outgoing[1].id;
    conv.messages.push(...outgoing);
    conv.lastActivity = outgoing[outgoing.length - 1].timestamp;

    // Clear composer immediately (optimistic UI).
    dom.messageInput.value = "";
    state.drafts.delete(conv.id);
    state.pendingAttachments.set(conv.id, []);
    renderAttachments();
    if (state.activeId === conv.id) renderThread(conv, true);
    renderList();

    await sendOptimistic(conv, outgoing[0]);
  }

  async function retrySend(convId, msgId) {
    const conv = getConversation(convId);
    if (!conv) return;
    const msg = conv.messages.find((m) => m.id === msgId);
    if (!msg || msg.status !== "failed") return;
    await sendOptimistic(conv, msg);
  }

  function wireEvents() {
    // Conversation selection (delegated).
    if (dom.list) {
      dom.list.addEventListener("click", (e) => {
        const row = e.target.closest(".messaging__row");
        if (row && row.dataset.convId) selectConversation(row.dataset.convId);
      });
    }

    // Filter pills.
    if (dom.filters) {
      dom.filters.addEventListener("click", (e) => {
        const btn = e.target.closest("[data-filter]");
        if (!btn) return;
        state.filter = btn.dataset.filter;
        dom.filters.querySelectorAll("[data-filter]").forEach((b) => b.classList.remove("is-active"));
        btn.classList.add("is-active");
        renderList();
      });
    }

    // Search (listing title + contact name only).
    if (dom.searchInput) {
      dom.searchInput.addEventListener("input", (e) => {
        state.search = e.target.value;
        renderList();
      });
    }

    // Composer send.
    if (dom.sendBtn) dom.sendBtn.addEventListener("click", sendCurrentMessage);
    if (dom.messageInput) {
      dom.messageInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          sendCurrentMessage();
        }
      });
      // Keep the draft map current as the user types.
      dom.messageInput.addEventListener("input", () => {
        if (state.activeId) state.drafts.set(state.activeId, dom.messageInput.value);
      });
    }

    // Attachments.
    if (dom.attachBtn && dom.fileInput) {
      dom.attachBtn.addEventListener("click", () => dom.fileInput.click());
      dom.fileInput.addEventListener("change", (e) => {
        handleFiles(e.target.files);
        dom.fileInput.value = ""; // allow re-selecting the same file
      });
    }
  }

  async function poll() {
    if (document.hidden || state.polling) return;
    state.polling = true;
    try {
      const fresh = await Adapter.fetchConversations();
      const old = new Map(state.conversations.map((conv) => [conv.id, conv]));
      state.conversations = fresh.map((conv) => {
        const prior = old.get(conv.id);
        if (!prior) return conv;
        const seen = new Set(prior.messages.map((message) => message.id));
        const newPreview = conv.id === state.activeId ? [] : conv.messages.filter((message) => !seen.has(message.id) &&
          !prior.messages.some((oldMessage) => oldMessage.clientRequestId && oldMessage.clientRequestId === message.clientRequestId));
        return { ...conv, messages: [...prior.messages, ...newPreview] };
      });
      renderList();
      const id = state.activeId;
      const conv = getConversation(id);
      if (conv) {
        const latest = Math.max(0, ...conv.messages.map((m) => /^\d+$/.test(m.id) ? Number(m.id) : 0));
        let page = await Adapter.fetchMessages(id, "?after=" + latest);
        if (state.activeId !== id) return;
        const seen = new Set(conv.messages.map((message) => message.id));
        let changed = false;
        while (true) {
          for (const message of page.messages) {
            if (seen.has(message.id)) continue;
            const optimistic = conv.messages.find((oldMessage) => oldMessage.clientRequestId && oldMessage.clientRequestId === message.clientRequestId);
            if (optimistic) {
              Object.assign(optimistic, message);
              const followup = conv.messages.find((oldMessage) => oldMessage.id === optimistic._followupId);
              if (followup?.status === "waiting") queueMicrotask(() => sendOptimistic(conv, followup));
            }
            else conv.messages.push(message);
            seen.add(message.id);
            changed = true;
          }
          if (!page.hasMore || !page.nextAfter) break;
          page = await Adapter.fetchMessages(id, "?after=" + page.nextAfter);
          if (state.activeId !== id) return;
        }
        if (changed) renderThread(conv);
      }
    } catch (e) {
      showError(e.message);
    } finally {
      state.polling = false;
    }
  }

  /* ==========================================================
     10. BOOTSTRAP
     ========================================================== */
  async function bootstrap() {
    const root = document.querySelector("[data-messaging-root]");
    if (!root) return;

    // Cache DOM references (all optional-guarded downstream).
    dom.root = root;
    dom.list = root.querySelector("[data-conversation-list]");
    dom.filters = root.querySelector("[data-filters]");
    dom.searchInput = root.querySelector("[data-search-input]");
    dom.chatEmpty = root.querySelector("[data-chat-empty]");
    dom.chatInner = root.querySelector("[data-chat-inner]");
    dom.chatHeader = root.querySelector("[data-chat-header]");
    dom.thread = root.querySelector("[data-thread]");
    dom.composer = root.querySelector("[data-composer]");
    dom.composerRow = root.querySelector(".messaging__composer-row");
    dom.attachments = root.querySelector("[data-attachments]");
    dom.attachBtn = root.querySelector("[data-attach-btn]");
    dom.fileInput = root.querySelector("[data-file-input]");
    dom.messageInput = root.querySelector("[data-message-input]");
    dom.sendBtn = root.querySelector("[data-send-btn]");
    dom.notice = root.querySelector("[data-messaging-notice]");
    dom.imageViewer = document.querySelector("[data-image-viewer]");
    dom.imageViewerImage = dom.imageViewer?.querySelector("[data-image-viewer-image]");
    dom.imageViewer?.querySelector("[data-image-viewer-close]")?.addEventListener("click", () => dom.imageViewer.close());
    dom.imageViewer?.addEventListener("close", () => {
      dom.imageViewerImage.removeAttribute("src");
      imageScale = 1;
    });
    dom.imageViewer?.addEventListener("wheel", (event) => {
      event.preventDefault();
      imageScale = Math.max(0.5, Math.min(4, imageScale * (event.deltaY < 0 ? 1.15 : 1 / 1.15)));
      dom.imageViewerImage.style.transform = `scale(${imageScale})`;
    }, { passive: false });
    dom.thread.addEventListener("scroll", () => requestAnimationFrame(markVisibleRead), { passive: true });

    if (dom.list) dom.list.innerHTML = '<li class="messaging__list-empty"><div class="messaging__list-empty-body">Loading…</div></li>';
    wireEvents();

    try {
      state.conversations = await Adapter.fetchConversations();
    } catch (e) {
      if (dom.list) {
        dom.list.innerHTML =
          '<li class="messaging__list-empty"><div class="messaging__list-empty-body">Failed to load conversations.</div></li>';
      }
      return;
    }

    renderList();
    const params = new URLSearchParams(location.search);
    if (params.has("listing")) {
      try {
        const conv = await api(config.create, { method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ listingId: params.get("listing") }) });
        if (!state.conversations.some((item) => item.id === conv.id)) state.conversations.unshift(conv);
        await selectConversation(conv.id);
      } catch (e) { showError(e.message); }
    } else if (params.has("conversation")) {
      const id = params.get("conversation");
      if (getConversation(id)) await selectConversation(id);
    }
    document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });
    setInterval(poll, 10000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootstrap);
  } else {
    bootstrap();
  }
})();
