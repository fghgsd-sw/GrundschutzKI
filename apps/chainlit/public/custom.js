(function () {
  const HINT_ID = "export-all-welcome-hint";

  function isVisible(el) {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    return style.display !== "none" && style.visibility !== "hidden";
  }

  function findComposerAnchor() {
    const input =
      document.querySelector("textarea") ||
      document.querySelector('input[type="text"]');
    if (!input || !isVisible(input)) return null;

    const form = input.closest("form");
    if (form && form.parentNode) return form;
    return input.parentElement;
  }

  function ensureHint() {
    const anchor = findComposerAnchor();
    if (!anchor || !anchor.parentNode) return;

    let hint = document.getElementById(HINT_ID);
    if (!hint) {
      hint = document.createElement("div");
      hint.id = HINT_ID;
      hint.style.margin = "0.55rem 0 0 0";
      hint.style.fontSize = "0.9rem";
      hint.style.lineHeight = "1.35";
      hint.style.color = "inherit";
      hint.style.opacity = "0.9";
      hint.innerHTML = 'Nutze "<code>/export all</code>" um alle Chats zu exportieren.';
    }

    if (anchor.nextSibling !== hint) {
      anchor.parentNode.insertBefore(hint, anchor.nextSibling);
    }
  }

  const observer = new MutationObserver(function () {
    ensureHint();
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });

  window.addEventListener("load", ensureHint);
  ensureHint();
})();

/* ── Prompt editor modal ─────────────────────────────────── */
(function () {
  const MODAL_ID = "gski-prompt-editor-modal";
  const OVERLAY_ID = "gski-prompt-editor-overlay";

  /* Create overlay + modal once; reuse. */
  function getOrCreateModal() {
    let overlay = document.getElementById(OVERLAY_ID);
    if (overlay) return overlay;

    overlay = document.createElement("div");
    overlay.id = OVERLAY_ID;
    overlay.className = "gski-modal-overlay";
    overlay.addEventListener("click", function (e) {
      if (e.target === overlay) closeModal();
    });

    const modal = document.createElement("div");
    modal.id = MODAL_ID;
    modal.className = "gski-modal";
    modal.innerHTML =
      '<div class="gski-modal-header">' +
        '<span class="gski-modal-title">System-Prompt bearbeiten</span>' +
        '<button class="gski-modal-close" title="Schließen">&times;</button>' +
      "</div>" +
      '<textarea class="gski-modal-textarea" spellcheck="false"></textarea>' +
      '<div class="gski-modal-footer">' +
        '<button class="gski-modal-btn gski-modal-btn-secondary" data-action="reset">Auf Standard zurücksetzen</button>' +
        '<button class="gski-modal-btn gski-modal-btn-primary" data-action="save">Speichern</button>' +
      "</div>";

    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    modal.querySelector(".gski-modal-close").addEventListener("click", closeModal);
    modal.querySelector('[data-action="save"]').addEventListener("click", savePrompt);
    modal.querySelector('[data-action="reset"]').addEventListener("click", resetPrompt);

    return overlay;
  }

  function openModal(currentPrompt) {
    var overlay = getOrCreateModal();
    overlay.querySelector(".gski-modal-textarea").value = currentPrompt || "";
    overlay.classList.add("gski-modal-visible");
  }

  function closeModal() {
    var overlay = document.getElementById(OVERLAY_ID);
    if (overlay) overlay.classList.remove("gski-modal-visible");
  }

  function sendChatMessage(text) {
    /* Programmatically send a message through the Chainlit chat input. */
    var textarea = document.querySelector("textarea");
    if (!textarea) return;
    var nativeInputValueSetter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype, "value"
    ).set;
    nativeInputValueSetter.call(textarea, text);
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
    /* Find and click the send button */
    setTimeout(function () {
      var sendBtn = textarea.closest("form")
        ? textarea.closest("form").querySelector('button[type="submit"]')
        : null;
      if (!sendBtn) {
        /* Fallback: press Enter */
        textarea.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", bubbles: true }));
      } else {
        sendBtn.click();
      }
    }, 50);
  }

  function savePrompt() {
    var textarea = document.querySelector("#" + MODAL_ID + " .gski-modal-textarea");
    var newPrompt = (textarea ? textarea.value : "").trim();
    if (!newPrompt) return;
    closeModal();
    sendChatMessage("/prompt set " + newPrompt);
  }

  function resetPrompt() {
    closeModal();
    sendChatMessage("/prompt reset");
  }

  /* Expose globally so Chainlit actions can call it. */
  window.gskiOpenPromptEditor = openModal;
})();
