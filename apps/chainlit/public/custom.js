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

/* ── Self-registration form on the Chainlit login page ──── */
(function () {
  var REG_ID = "gski-register-panel";

  /* --- helpers ---------------------------------------------------------- */

  /* Returns the login-page password input, ignoring our own reg form and the
     settings sidebar. Returns null if no such input exists or is visible. */
  function getPwInput() {
    var all = document.querySelectorAll('input[type="password"]');
    for (var i = 0; i < all.length; i++) {
      var inp = all[i];
      if (inp.closest('[data-testid="chat-settings-sidebar-content"]')) continue;
      if (inp.closest('#' + REG_ID)) continue;
      return inp;
    }
    return null;
  }

  function isLoginPage() {
    return !!getPwInput();
  }

  /* Returns the form/container that wraps the login inputs so we can
     show/hide it when toggling between login and register views. */
  function findLoginForm() {
    var inp = getPwInput();
    if (!inp) return null;
    return inp.closest("form") || inp.parentElement;
  }

  /* --- build panel ------------------------------------------------------ */

  function buildRegPanel() {
    var panel = document.createElement("div");
    panel.id = REG_ID;
    panel.innerHTML =
      '<div class="gski-reg-toggle">' +
        '<span>Noch kein Konto? </span>' +
        '<a href="#" id="gski-reg-toggle-link">Registrieren</a>' +
      "</div>" +
      '<form id="gski-reg-form" style="display:none">' +
        '<h3 style="margin:0 0 12px">Konto erstellen</h3>' +
        '<input id="gski-reg-user" type="text" placeholder="Benutzername (mind. 3 Zeichen)" autocomplete="username" />' +
        '<input id="gski-reg-email" type="email" placeholder="E-Mail-Adresse" autocomplete="email" />' +
        '<input id="gski-reg-pw" type="password" placeholder="Passwort (mind. 8 Zeichen)" autocomplete="new-password" />' +
        '<input id="gski-reg-pw2" type="password" placeholder="Passwort wiederholen" autocomplete="new-password" />' +
        '<button id="gski-reg-submit" type="submit">Registrieren</button>' +
        '<div id="gski-reg-msg" style="display:none"></div>' +
        '<div class="gski-reg-toggle" style="margin-top:12px">' +
          '<span>Bereits registriert? </span>' +
          '<a href="#" id="gski-reg-back-link">Zum Login</a>' +
        "</div>" +
      "</form>";
    return panel;
  }

  /* --- handlers --------------------------------------------------------- */

  function attachHandlers(panel) {
    var toggleLink = panel.querySelector("#gski-reg-toggle-link");
    var backLink   = panel.querySelector("#gski-reg-back-link");
    var regForm    = panel.querySelector("#gski-reg-form");
    var toggleDiv  = panel.querySelector(".gski-reg-toggle");
    var submitBtn  = panel.querySelector("#gski-reg-submit");
    var msgDiv     = panel.querySelector("#gski-reg-msg");

    toggleLink.addEventListener("click", function (e) {
      e.preventDefault();
      regForm.style.display = "block";
      toggleDiv.style.display = "none";
      var loginForm = findLoginForm();
      if (loginForm) loginForm.style.display = "none";
    });

    backLink.addEventListener("click", function (e) {
      e.preventDefault();
      regForm.style.display = "none";
      toggleDiv.style.display = "";
      msgDiv.style.display = "none";
      var loginForm = findLoginForm();
      if (loginForm) loginForm.style.display = "";
    });

    regForm.addEventListener("submit", function (e) {
      e.preventDefault();
      var user  = panel.querySelector("#gski-reg-user").value.trim();
      var email = panel.querySelector("#gski-reg-email").value.trim();
      var pw    = panel.querySelector("#gski-reg-pw").value;
      var pw2   = panel.querySelector("#gski-reg-pw2").value;

      msgDiv.style.display = "none";
      function showMsg(text, ok) {
        msgDiv.textContent = text;
        msgDiv.className = ok ? "gski-reg-msg-ok" : "gski-reg-msg-err";
        msgDiv.style.display = "block";
      }

      if (user.length < 3)                     return showMsg("Benutzername muss mind. 3 Zeichen haben.", false);
      if (!email || email.indexOf("@") === -1) return showMsg("Bitte gültige E-Mail eingeben.", false);
      if (pw.length < 8)                       return showMsg("Passwort muss mind. 8 Zeichen haben.", false);
      if (pw !== pw2)                          return showMsg("Passwörter stimmen nicht überein.", false);

      submitBtn.disabled = true;
      submitBtn.textContent = "Wird registriert…";

      fetch("/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: user, email: email, password: pw }),
      })
        .then(function (res) {
          return res.json().then(function (data) {
            return { ok: res.ok, status: res.status, data: data, text: undefined };
          }).catch(function () {
            return res.text().then(function (txt) {
              var parsed;
              try { parsed = txt && JSON.parse(txt); } catch (ex) {}
              return { ok: res.ok, status: res.status, data: parsed, text: txt || undefined };
            });
          });
        })
        .then(function (result) {
          submitBtn.disabled = false;
          submitBtn.textContent = "Registrieren";
          if (result.ok) {
            showMsg((result.data && result.data.message) || "Registrierung erfolgreich! Du kannst dich jetzt einloggen.", true);
            panel.querySelector("#gski-reg-user").value = "";
            panel.querySelector("#gski-reg-email").value = "";
            panel.querySelector("#gski-reg-pw").value = "";
            panel.querySelector("#gski-reg-pw2").value = "";
            var delay = result.data && result.data.email_verification_required ? 8000 : 2500;
            setTimeout(function () { backLink.click(); }, delay);
          } else {
            var detail = result.data && result.data.detail;
            if (Array.isArray(detail)) detail = detail.map(function (d) { return d.msg || JSON.stringify(d); }).join(", ");
            else if (typeof detail === "object" && detail !== null) detail = JSON.stringify(detail);
            if (!detail && result.text) detail = result.text;
            showMsg(detail || "Registrierung fehlgeschlagen.", false);
          }
        })
        .catch(function () {
          submitBtn.disabled = false;
          submitBtn.textContent = "Registrieren";
          showMsg("Netzwerkfehler – bitte erneut versuchen.", false);
        });
    });
  }

  /* --- insertion -------------------------------------------------------- */

  function ensureRegPanel() {
    if (!isLoginPage()) return;
    if (document.getElementById(REG_ID)) return;

    var loginForm = findLoginForm();
    if (!loginForm || !loginForm.parentNode) return;

    var panel = buildRegPanel();
    /* Append at end of login card (after the GitHub button), inside the
       React-managed DOM. The login page does not re-render after mount, so
       the node survives. This avoids the fixed-positioning walk-up bug. */
    loginForm.parentNode.appendChild(panel);
    attachHandlers(panel);
  }

  /* MutationObserver catches React rendering the login form asynchronously */
  var _obs = new MutationObserver(function () { ensureRegPanel(); });
  _obs.observe(document.documentElement, { childList: true, subtree: true });
  window.addEventListener("load", ensureRegPanel);

  /* Polling fallback: retry every 500 ms for the first 15 s */
  var _pollCount = 0;
  var _pollTimer = setInterval(function () {
    ensureRegPanel();
    if (++_pollCount >= 30 || document.getElementById(REG_ID)) {
      clearInterval(_pollTimer);
    }
  }, 500);
})();
