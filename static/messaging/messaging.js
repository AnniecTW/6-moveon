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
      error.code = result.code || "auth";
      error.status = response.status;
      throw error;
    }
    if (!response.ok) {
      const error = new Error(result.error || "Request failed. Please try again.");
      error.status = response.status;
      error.code = result.code || "request_failed";
      throw error;
    }
    return result;
  }

  const STATUS_LABEL = { awaiting: "Awaiting response", accepted: "Accepted", declined: "Declined" };
  const TRADE_LABEL = {
    negotiating: "Negotiating", action_needed: "Action needed",
    waiting: "Waiting for response", pending_pickup: "Pending pickup",
    declined: "Declined", unavailable: "Unavailable",
  };
  const DETAIL_LABEL = {
    negotiating: "Keep chatting to agree on the next step.",
    review_bundle_request: "Review this buyer's Bundle request.",
    waiting_for_seller: "Waiting for the seller to review your Bundle request.",
    review_deal: "The seller has submitted a final offer for your review.",
    awaiting_buyer: "Waiting for the buyer to review your final offer.",
    deal_declined: "The final offer was declined. You can keep chatting.",
    bundle_declined: "The Bundle request was declined. You can keep chatting.",
    pending_pickup: "This listing is reserved for your pickup.",
    unavailable: "This listing is no longer available.",
  };

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
    offerUi: {},              // proposalId -> { busy, error }
    dealUi: null,             // active offer/review dialog; kept across polling
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
    async createDeal(convId, payload) {
      return api(endpoint(config.dealCreate, convId), { method: "POST",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    },
    async reviseDeal(proposalId, payload) {
      return api(endpoint(config.dealRevise, proposalId), { method: "PATCH",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    },
    async withdrawDeal(proposalId) {
      return api(endpoint(config.dealWithdraw, proposalId), { method: "POST",
        headers: { "Content-Type": "application/json" }, body: "{}" });
    },
    async decideDeal(proposalId, decision) {
      return api(endpoint(config.dealDecision, proposalId), { method: "POST",
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

  function dealMoney(n) {
    return "$" + Number(n).toLocaleString(undefined,
      { minimumFractionDigits: 2, maximumFractionDigits: 2 });
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
    if (state.filter === "needs-action") return conv.trade?.summaryState === "action_needed";
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
            : state.search.trim()
              ? "No conversations match your search."
              : "No conversations match this filter."
        )
      );
      list.appendChild(li);
      return;
    }

    visible.forEach((conv) => {
      const row = el("li", "messaging__row");
      row.dataset.convId = conv.id;
      if (conv.id === state.activeId) row.classList.add("is-active");

      const rail = el("div", "messaging__row-rail");
      rail.appendChild(thumb("messaging__thumb", conv.listing));
      rail.appendChild(el("span", "messaging__tag", conv.role === "seller" ? "Selling" : "Buying"));
      row.appendChild(rail);

      const main = el("div", "messaging__row-main");

      // Top: listing title + relative time.
      const top = el("div", "messaging__row-top");
      top.appendChild(el("span", "messaging__row-name", esc(conv.listing.title)));
      top.appendChild(el("span", "messaging__row-time", esc(relTime(conv.lastActivity))));
      main.appendChild(top);

      // Contact name.
      const contact = el("div", "messaging__row-contact");
      contact.appendChild(el("span", "messaging__row-contact-name", esc(conv.contact.displayName)));
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

      const summary = conv.trade?.summaryState || "negotiating";
      const status = el("div", "messaging__row-state messaging__row-state--" + summary);
      status.appendChild(el("span", "messaging__row-state-dot"));
      status.appendChild(document.createTextNode(TRADE_LABEL[summary] || TRADE_LABEL.negotiating));
      main.appendChild(status);

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
    const summary = conv.trade?.summaryState || "negotiating";
    const status = el("span", "messaging__status-badge messaging__status-badge--" + summary,
      esc(TRADE_LABEL[summary] || TRADE_LABEL.negotiating));
    status.title = DETAIL_LABEL[conv.trade?.detailState] || "";
    titleRow.appendChild(status);
    info.appendChild(titleRow);

    // Prices come from server listing/transaction data, never chat text.
    const sub = el("div", "messaging__chat-sub");
    if (listing.listedPrice != null) {
      sub.append("Listed ", el("span", "messaging__chat-price", esc(money(listing.listedPrice))), " · ");
    }
    sub.append("with " + conv.contact.displayName);
    if (conv.trade?.transaction?.agreedPrice) {
      sub.append(" · Agreed ", el("span", "messaging__chat-price",
        esc(dealMoney(conv.trade.transaction.agreedPrice))));
    }
    info.appendChild(sub);
    h.appendChild(info);

    const actions = el("div", "messaging__chat-actions");
    const dealActions = conv.trade?.allowedActions?.deal || [];
    if (dealActions.includes("create")) {
      const start = el("button", "messaging__btn messaging__btn--solid", "Start Deal");
      start.type = "button";
      start.addEventListener("click", () => openDealDialog(conv.id, "create"));
      actions.appendChild(start);
    } else if (dealActions.includes("confirm") && conv.trade.currentProposalId) {
      const review = el("button", "messaging__btn messaging__btn--solid", "Review Deal");
      review.type = "button";
      review.addEventListener("click", () => openDealDialog(conv.id, "review", conv.trade.currentProposalId));
      actions.appendChild(review);
    }

    // View Listing (only when the listing is still available).
    if (listing.available !== false) {
      const link = el("a", "messaging__view-listing", "View Listing " + ICON.external);
      link.href = config.home + "?q=" + encodeURIComponent(listing.title) + "#listing-" + encodeURIComponent(listing.id);
      link.textContent = "View listing";
      actions.appendChild(link);
    }
    h.appendChild(actions);
  }

  function renderTradeStatus(conv) {
    const announcement = dom.tradeAnnouncement;
    if (!announcement) return;
    const trade = conv.trade || {};
    const summary = trade.summaryState || "negotiating";
    let detail = DETAIL_LABEL[trade.detailState] || DETAIL_LABEL.negotiating;
    if (summary === "pending_pickup" && trade.transaction?.agreedPrice) {
      detail += " Agreed price: " + dealMoney(trade.transaction.agreedPrice) + ".";
    }
    const key = JSON.stringify([conv.id, summary, detail]);
    if (announcement.dataset.tradeKey === key) return;
    announcement.dataset.tradeKey = key;
    announcement.textContent = (TRADE_LABEL[summary] || TRADE_LABEL.negotiating) + ". " + detail;
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

    // Offers are persistent conversation context, separate from timestamped messages.
    const proposals = conv.dealProposals || [];
    const currentId = conv.trade?.currentProposalId;
    const current = proposals.find((proposal) => proposal.id === currentId);
    if (current) thread.appendChild(renderDealProposalCard(conv, current, true));
    proposals.slice().reverse().filter((proposal) => proposal.id !== currentId)
      .forEach((proposal) => thread.appendChild(renderDealProposalCard(conv, proposal, false)));

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
    else thread.scrollTop = oldTop + (prepended ? thread.scrollHeight - oldHeight : 0);
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
    if (req.status !== "awaiting") card.classList.add("is-history");

    // Top row: icon + fixed "Bundle request" label + meta, then status pill.
    const top = el("div", "messaging__request-top");
    const head = el("div", "messaging__request-head");
    head.appendChild(el("span", "messaging__request-icon", ICON.cube));
    const headText = el("div");
    headText.appendChild(el("div", "messaging__request-label", "Bundle request"));
    headText.appendChild(
      el("div", "messaging__request-meta",
        esc(req.bundleLabel + " · " + req.itemCount + " items · " + money(req.requestedPrice)))
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

    // Seller actions — only while awaiting a response (see TRANSACTION RULES).
    if (canDecide(conv, req)) {
      card.appendChild(renderRequestActions(conv, req));
    }
    return card;
  }

  // Inline accept/decline flow: idle -> confirming -> processing -> result / failed.
  function renderRequestActions(conv, req) {
    let ui = state.reqUi[req.requestId] || { mode: "idle", decision: null, error: null };
    if (ui.decision && !canDecide(conv, req, ui.decision)) {
      ui = { mode: "idle", decision: null, error: null };
      state.reqUi[req.requestId] = ui;
    }
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
    if (canDecide(conv, req, "accepted")) {
      const accept = el("button", "messaging__btn messaging__btn--solid", "Accept request");
      accept.type = "button";
      accept.addEventListener("click", () => startDecision(conv, req, "accepted"));
      actions.appendChild(accept);
    }
    if (canDecide(conv, req, "declined")) {
      const decline = el("button", "messaging__btn", "Decline request");
      decline.type = "button";
      decline.addEventListener("click", () => startDecision(conv, req, "declined"));
      actions.appendChild(decline);
    }
    body.appendChild(actions);
    return body;
  }

  // ----- 5e. Final offer cards and review dialog -----
  const OFFER_LABEL = {
    awaiting_buyer: "Awaiting buyer", declined: "Declined", withdrawn: "Withdrawn",
    superseded: "Replaced", confirmed: "Confirmed", unavailable: "Unavailable",
  };

  function renderDealProposalCard(conv, proposal, isCurrent) {
    const card = el("div", "messaging__offer-card");
    card.dataset.proposalId = proposal.id;
    if (!isCurrent) card.classList.add("is-history");
    const top = el("div", "messaging__offer-top");
    const description = el("div", "messaging__offer-description");
    description.appendChild(el("strong", "", isCurrent ? "Final offer" : "Earlier offer"));
    description.appendChild(el("span", "", esc(dealMoney(proposal.agreedPrice))));
    top.appendChild(description);
    const status = isCurrent ? proposal.status :
      proposal.status === "awaiting_buyer" ? "unavailable" : proposal.status;
    top.appendChild(el("span", "messaging__offer-state", esc(OFFER_LABEL[status] || status)));
    card.appendChild(top);

    if (isCurrent) {
      const allowed = conv.trade?.allowedActions?.deal || [];
      const actions = el("div", "messaging__offer-actions");
      if (allowed.includes("edit")) {
        const edit = el("button", "messaging__btn", "Edit Offer");
        edit.type = "button";
        edit.addEventListener("click", () => openDealDialog(conv.id, "edit", proposal.id));
        actions.appendChild(edit);
      }
      if (allowed.includes("withdraw")) {
        const withdraw = el("button", "messaging__btn", "Withdraw");
        withdraw.type = "button";
        withdraw.disabled = !!state.offerUi[proposal.id]?.busy;
        withdraw.addEventListener("click", () => withdrawDeal(conv.id, proposal.id));
        actions.appendChild(withdraw);
      }
      if (allowed.includes("confirm")) {
        const review = el("button", "messaging__btn messaging__btn--solid", "Review Deal");
        review.type = "button";
        review.addEventListener("click", () => openDealDialog(conv.id, "review", proposal.id));
        actions.appendChild(review);
      }
      if (actions.childElementCount) card.appendChild(actions);
      const ui = state.offerUi[proposal.id];
      if (ui?.busy) card.appendChild(el("span", "messaging__offer-feedback", "Updating offer…"));
      if (ui?.error) card.appendChild(el("span", "messaging__offer-error", esc(ui.error)));
    }
    return card;
  }

  function applyDealResult(convId, result) {
    const conv = getConversation(convId);
    if (!conv) return;
    conv.listing = { ...conv.listing, ...result.listing };
    conv.trade = result.trade;
    conv.dealProposals = result.dealProposals;
    renderList();
    if (state.activeId === convId) {
      renderChatHeader(conv);
      renderTradeStatus(conv);
      renderThread(conv, false, true);
      applyComposerState(conv);
      syncDealDialog();
    }
  }

  async function withdrawDeal(convId, proposalId) {
    const conv = getConversation(convId);
    if (conv?.trade?.currentProposalId !== proposalId ||
        !conv.trade.allowedActions.deal.includes("withdraw")) return;
    if (state.offerUi[proposalId]?.busy) return;
    state.offerUi[proposalId] = { busy: true, error: null };
    if (state.activeId === convId) renderThread(conv);
    try {
      const result = await Adapter.withdrawDeal(proposalId);
      state.offerUi[proposalId] = { busy: false, error: null };
      applyDealResult(convId, result);
    } catch (error) {
      state.offerUi[proposalId] = { busy: false, error: error.message || "Could not withdraw." };
      if (error.status === 409) await poll();
      if (state.activeId === convId) renderThread(getConversation(convId) || conv);
    }
  }

  function closeDealDialog() {
    if (dom.dealDialog?.open) dom.dealDialog.close();
    state.dealUi = null;
  }

  function openDealDialog(convId, mode, proposalId = null) {
    const conv = getConversation(convId);
    if (!conv || !dom.dealDialog) return;
    const allowed = conv.trade?.allowedActions?.deal || [];
    const required = { create: "create", edit: "edit", review: "confirm" }[mode];
    if (!allowed.includes(required)) return;
    if (mode !== "create" && conv.trade.currentProposalId !== proposalId) return;
    const proposal = (conv.dealProposals || []).find((item) => item.id === proposalId);
    if (mode !== "create" && !proposal) return;
    state.dealUi = {
      convId, mode, proposalId, reviewPrice: proposal?.agreedPrice || null,
      request: null, busy: false, stale: false, error: null,
    };
    renderDealDialog(conv, proposal);
    dom.dealDialog.showModal();
    (dom.dealDialog.querySelector("[data-deal-price]") ||
      dom.dealDialog.querySelector("[data-deal-submit]"))?.focus();
  }

  function renderDealDialog(conv, proposal) {
    const ui = state.dealUi;
    const content = dom.dealContent;
    content.replaceChildren();
    const top = el("div", "messaging__deal-top");
    const title = el("h2", "messaging__deal-title",
      ui.mode === "create" ? "Start Deal" : ui.mode === "edit" ? "Edit Offer" : "Review Deal");
    title.id = "messaging-deal-title";
    top.appendChild(title);
    const close = el("button", "messaging__deal-close", "×");
    close.type = "button";
    close.setAttribute("aria-label", "Close deal dialog");
    close.addEventListener("click", closeDealDialog);
    top.appendChild(close);
    content.appendChild(top);
    content.appendChild(el("div", "messaging__deal-listing", esc(conv.listing.title)));
    content.appendChild(el("div", "messaging__deal-listed",
      "Public price: " + esc(money(conv.listing.listedPrice))));

    if (ui.mode === "review") {
      content.appendChild(el("div", "messaging__deal-price", esc(dealMoney(proposal.agreedPrice))));
      content.appendChild(el("p", "messaging__deal-note",
        "Accepting reserves this item for pickup. MoveOn does not process real payment."));
    } else {
      const label = el("label", "messaging__deal-field");
      label.appendChild(el("span", "", "Final agreed price"));
      const input = document.createElement("input");
      input.type = "text";
      input.inputMode = "decimal";
      input.autocomplete = "off";
      input.placeholder = "0.00";
      input.value = proposal?.agreedPrice || "";
      input.dataset.dealPrice = "";
      input.addEventListener("input", () => {
        ui.request = null; // Changing parameters must use a new idempotency key.
        ui.error = null;
        syncDealDialog();
      });
      label.appendChild(input);
      content.appendChild(label);
      const confirmation = el("label", "messaging__deal-confirm");
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.dataset.dealConfirm = "";
      checkbox.addEventListener("change", () => { ui.error = null; syncDealDialog(); });
      confirmation.appendChild(checkbox);
      confirmation.appendChild(document.createTextNode("I confirm I am willing to sell at this final price."));
      content.appendChild(confirmation);
      content.appendChild(el("p", "messaging__deal-note", "The buyer must confirm before the item is reserved."));
    }

    const stale = el("div", "messaging__deal-warning");
    stale.dataset.dealStale = "";
    stale.hidden = true;
    content.appendChild(stale);
    const error = el("div", "messaging__deal-error");
    error.dataset.dealError = "";
    error.hidden = true;
    content.appendChild(error);
    const actions = el("div", "messaging__deal-actions");
    if (ui.mode === "review") {
      const decline = el("button", "messaging__btn", "Decline");
      decline.type = "button";
      decline.dataset.dealAction = "decline";
      decline.addEventListener("click", () => submitDealDecision("declined"));
      actions.appendChild(decline);
    }
    if (ui.mode !== "review") {
      const cancel = el("button", "messaging__btn", "Close");
      cancel.type = "button";
      cancel.addEventListener("click", closeDealDialog);
      actions.appendChild(cancel);
    }
    const submit = el("button", "messaging__btn messaging__btn--solid",
      ui.mode === "review" ? "Accept" :
        ui.mode === "edit" ? "Update Offer" : "Submit Offer");
    submit.type = "button";
    submit.dataset.dealSubmit = "";
    submit.dataset.dealAction = ui.mode === "review" ? "confirm" : ui.mode;
    submit.addEventListener("click", ui.mode === "review" ?
      () => submitDealDecision("confirmed") : submitDealOffer);
    actions.appendChild(submit);
    content.appendChild(actions);
    syncDealDialog();
  }

  function syncDealDialog() {
    const ui = state.dealUi;
    if (!ui || !dom.dealDialog?.open && !dom.dealContent?.childElementCount) return;
    const conv = getConversation(ui.convId);
    const allowed = conv?.trade?.allowedActions?.deal || [];
    const current = (conv?.dealProposals || []).find((item) => item.id === ui.proposalId);
    const valid = ui.mode === "create" ? allowed.includes("create") :
      ui.mode === "edit" ? allowed.includes("edit") &&
        conv.trade.currentProposalId === ui.proposalId :
        allowed.includes("confirm") && allowed.includes("decline") &&
        conv.trade.currentProposalId === ui.proposalId &&
        current?.agreedPrice === ui.reviewPrice;
    ui.stale = !valid;
    const stale = dom.dealContent.querySelector("[data-deal-stale]");
    if (stale) {
      stale.hidden = !ui.stale;
      stale.textContent = ui.stale ? "This offer changed or is no longer available. Close and refresh the conversation." : "";
    }
    const error = dom.dealContent.querySelector("[data-deal-error]");
    if (error) {
      error.hidden = !ui.error;
      error.textContent = ui.error || "";
    }
    dom.dealContent.querySelectorAll("[data-deal-action]").forEach((button) => {
      button.disabled = ui.busy || ui.stale;
    });
  }

  async function submitDealOffer() {
    const ui = state.dealUi;
    if (!ui || ui.busy || ui.stale || ui.mode === "review") return;
    const price = dom.dealContent.querySelector("[data-deal-price]")?.value.trim() || "";
    const confirmed = dom.dealContent.querySelector("[data-deal-confirm]")?.checked;
    if (!/^(?:0|[1-9][0-9]{0,5})(?:\.[0-9]{1,2})?$/.test(price) ||
        Number(price) < 0.01 || Number(price) > 999999.99 || !confirmed) {
      ui.error = "Enter a price from $0.01 to $999,999.99 and confirm you will sell.";
      syncDealDialog();
      return;
    }
    if (!ui.request || ui.request.price !== price) {
      ui.request = { price, key: crypto.randomUUID() };
    }
    ui.busy = true;
    ui.error = null;
    syncDealDialog();
    const payload = { agreedPrice: price, sellerConfirmed: true, clientRequestId: ui.request.key };
    try {
      const result = ui.mode === "edit" ?
        await Adapter.reviseDeal(ui.proposalId, payload) :
        await Adapter.createDeal(ui.convId, payload);
      const convId = ui.convId;
      if (state.dealUi === ui) closeDealDialog();
      applyDealResult(convId, result);
    } catch (error) {
      ui.busy = false;
      ui.error = error.message || "Could not save the offer. Retry the same request.";
      if (error.status === 409) await poll();
      if (state.dealUi === ui) syncDealDialog();
    }
  }

  async function submitDealDecision(decision) {
    const ui = state.dealUi;
    if (!ui || ui.busy || ui.stale || ui.mode !== "review") return;
    const conv = getConversation(ui.convId);
    const required = decision === "confirmed" ? "confirm" : "decline";
    if (conv?.trade?.currentProposalId !== ui.proposalId ||
        !conv.trade.allowedActions.deal.includes(required)) return;
    ui.busy = true;
    ui.error = null;
    syncDealDialog();
    try {
      const result = await Adapter.decideDeal(ui.proposalId, decision);
      const convId = ui.convId;
      if (state.dealUi === ui) closeDealDialog();
      applyDealResult(convId, result);
    } catch (error) {
      ui.busy = false;
      ui.error = error.message || "Could not submit the decision. Try again.";
      if (error.status === 409) await poll();
      if (state.dealUi === ui) syncDealDialog();
    }
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
     The server supplies separate accept and decline permissions.
     ========================================================== */
  function canDecide(conv, req, decision) {
    if (req.status !== "awaiting") return false;
    const allowed = conv.trade?.allowedActions || {};
    if (decision === "accepted") return (allowed.bundleRequestIds || []).includes(req.requestId);
    if (decision === "declined") return (allowed.bundleDeclineRequestIds || []).includes(req.requestId);
    return canDecide(conv, req, "accepted") || canDecide(conv, req, "declined");
  }

  function refreshActiveThread() {
    const conv = getConversation(state.activeId);
    if (conv) renderThread(conv);
  }

  function startDecision(conv, req, decision) {
    if (!canDecide(conv, req, decision)) return;
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
    if (!canDecide(getConversation(conv.id) || conv, req, decision)) return;
    state.reqUi[req.requestId] = { mode: "processing", decision: decision, error: null };
    refreshActiveThread();
    try {
      const res = await Adapter.submitRequestDecision(req.requestId, decision);
      req.status = res.status; // authoritative status from adapter/server
      state.reqUi[req.requestId] = { mode: "idle", decision: null, error: null };
      if (state.activeId === conv.id) refreshActiveThread();
      renderList();
      await poll();
    } catch (e) {
      state.reqUi[req.requestId] = { mode: "failed", decision: decision, error: e.message || "Couldn't submit." };
      if (state.activeId === conv.id) refreshActiveThread();
    }
  }

  /* ==========================================================
     8. EVENT WIRING
     ========================================================== */

  function composerDisabled(conv) {
    // Keep the chat usable for the buyer and seller of a reserved listing.
    return conv.trade?.summaryState !== "pending_pickup" &&
      conv.listing.available === false && (conv.messages || []).length === 0;
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
    if (state.dealUi && state.dealUi.convId !== id) closeDealDialog();
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
    renderTradeStatus(conv);
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
      if (e.status === 401 || e.code === "auth" ||
          e.code === "login_required" || e.code === "campus_access_required") {
        showError(e.message);
      }
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
      const previousActive = old.get(state.activeId);
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
        renderChatHeader(conv);
        renderTradeStatus(conv);
        applyComposerState(conv);
        syncDealDialog();
        if (previousActive && (
          JSON.stringify(previousActive.trade) !== JSON.stringify(conv.trade) ||
          JSON.stringify(previousActive.bundleRequests) !== JSON.stringify(conv.bundleRequests) ||
          JSON.stringify(previousActive.dealProposals) !== JSON.stringify(conv.dealProposals) ||
          previousActive.listing.status !== conv.listing.status
        )) renderThread(conv, false, true);
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
    dom.tradeAnnouncement = root.querySelector("[data-trade-announcement]");
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
    dom.dealDialog = document.querySelector("[data-deal-dialog]");
    dom.dealContent = dom.dealDialog?.querySelector("[data-deal-content]");
    dom.dealDialog?.addEventListener("cancel", () => { state.dealUi = null; });
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
