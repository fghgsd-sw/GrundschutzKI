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

/* ── PDF viewer: default to page-width zoom in sidebar ── */
(function () {
  function fixPdfZoom(iframe) {
    var src = iframe.getAttribute("src") || "";
    if (!src.includes("/sources/pdf/")) return;
    if (src.includes("zoom=page-width")) return;
    var newSrc = src.includes("#") ? src + "&zoom=page-width" : src + "#zoom=page-width";
    iframe.setAttribute("src", newSrc);
  }

  function scanAll() {
    document.querySelectorAll("iframe").forEach(fixPdfZoom);
  }

  var observer = new MutationObserver(function (mutations) {
    mutations.forEach(function (m) {
      if (m.type === "attributes" && m.target.tagName === "IFRAME") {
        fixPdfZoom(m.target);
      }
      m.addedNodes.forEach(function (node) {
        if (!node || node.nodeType !== 1) return;
        if (node.tagName === "IFRAME") fixPdfZoom(node);
        if (node.querySelectorAll) node.querySelectorAll("iframe").forEach(fixPdfZoom);
      });
    });
  });

  observer.observe(document.documentElement, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["src"],
  });

  window.addEventListener("load", scanAll);
  scanAll();
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
