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

/* ── Force line break before follow-up question buttons ─────── */
(function () {
  var BREAK_ATTR = "data-gski-break";

  function injectBreak(container) {
    var buttons = container.querySelectorAll("button");
    for (var i = 0; i < buttons.length; i++) {
      var text = (buttons[i].textContent || "").trim();
      if (text.endsWith("?")) {
        if (!buttons[i].previousSibling || !buttons[i].previousSibling[BREAK_ATTR]) {
          var spacer = document.createElement("div");
          spacer[BREAK_ATTR] = "1";
          spacer.style.cssText = "flex-basis:100%;height:0;";
          container.insertBefore(spacer, buttons[i]);
        }
        break;
      }
    }
  }

  function scanAll() {
    document.querySelectorAll('[data-testid="actions"]').forEach(injectBreak);
  }

  var observer = new MutationObserver(function (mutations) {
    mutations.forEach(function (m) {
      m.addedNodes.forEach(function (node) {
        if (!node || node.nodeType !== 1) return;
        if (node.matches && node.matches('[data-testid="actions"]')) injectBreak(node);
        if (node.querySelectorAll) node.querySelectorAll('[data-testid="actions"]').forEach(injectBreak);
      });
    });
  });

  observer.observe(document.documentElement, { childList: true, subtree: true });
  window.addEventListener("load", scanAll);
})();

/* ── PDF.js viewer: trigger page-width scale on load ─────── */
(function () {
  var triggered = false;

  function applyPageWidth() {
    // PDF.js viewer application API (available when viewer is active)
    var app = window.PDFViewerApplication;
    if (app && app.pdfViewer) {
      app.pdfViewer.currentScaleValue = "page-width";
      triggered = false; // allow re-trigger on next open
      return true;
    }
    return false;
  }

  function onViewerAppear(node) {
    if (!node || node.nodeType !== 1) return;
    var hasPdfViewer =
      node.classList && node.classList.contains("pdfViewer") ||
      node.querySelector && node.querySelector(".pdfViewer");
    if (!hasPdfViewer) return;
    if (triggered) return;
    triggered = true;
    // Small delay to let PDF.js finish initialising the page
    setTimeout(function () { applyPageWidth(); }, 300);
  }

  var observer = new MutationObserver(function (mutations) {
    mutations.forEach(function (m) {
      m.addedNodes.forEach(onViewerAppear);
    });
  });

  observer.observe(document.documentElement, { childList: true, subtree: true });
})();

/* ── Auto-resize multiline TextInput fields in settings panel ── */
(function () {
  function autoResize(textarea) {
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = textarea.scrollHeight + "px";
    textarea.style.overflow = "hidden";
  }

  function processAllTextareas() {
    /* Target textareas inside the settings sidebar */
    var sidebar = document.querySelector('[data-testid="chat-settings-sidebar-content"]');
    if (!sidebar) return;
    var areas = sidebar.querySelectorAll("textarea");
    areas.forEach(function (ta) {
      autoResize(ta);
      if (!ta.dataset.gskiAutoResize) {
        ta.dataset.gskiAutoResize = "1";
        ta.addEventListener("input", function () { autoResize(ta); });
      }
    });
  }

  var observer = new MutationObserver(function () {
    processAllTextareas();
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });

  window.addEventListener("load", processAllTextareas);
})();
