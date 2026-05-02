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

  function isLoginPage() {
    /* Chainlit renders a form with password input on the login view */
    var pwInput = document.querySelector('input[type="password"]');
    if (!pwInput) return false;
    /* Avoid triggering inside the chat settings sidebar */
    if (pwInput.closest('[data-testid="chat-settings-sidebar-content"]')) return false;
    return true;
  }

  function findLoginForm() {
    var pwInput = document.querySelector('input[type="password"]');
    if (!pwInput) return null;
    var form = pwInput.closest("form");
    return form || pwInput.closest("div");
  }

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

  function attachHandlers(panel) {
    var toggleLink = panel.querySelector("#gski-reg-toggle-link");
    var backLink = panel.querySelector("#gski-reg-back-link");
    var regForm = panel.querySelector("#gski-reg-form");
    var toggleDiv = panel.querySelector(".gski-reg-toggle");
    var submitBtn = panel.querySelector("#gski-reg-submit");
    var msgDiv = panel.querySelector("#gski-reg-msg");

    toggleLink.addEventListener("click", function (e) {
      e.preventDefault();
      regForm.style.display = "block";
      toggleDiv.style.display = "none";
      /* Hide the original login form */
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
      var user = panel.querySelector("#gski-reg-user").value.trim();
      var email = panel.querySelector("#gski-reg-email").value.trim();
      var pw = panel.querySelector("#gski-reg-pw").value;
      var pw2 = panel.querySelector("#gski-reg-pw2").value;

      msgDiv.style.display = "none";
      function showMsg(text, ok) {
        msgDiv.textContent = text;
        msgDiv.className = ok ? "gski-reg-msg-ok" : "gski-reg-msg-err";
        msgDiv.style.display = "block";
      }

      if (user.length < 3) return showMsg("Benutzername muss mind. 3 Zeichen haben.", false);
      if (!email || email.indexOf("@") === -1) return showMsg("Bitte gültige E-Mail eingeben.", false);
      if (pw.length < 8) return showMsg("Passwort muss mind. 8 Zeichen haben.", false);
      if (pw !== pw2) return showMsg("Passwörter stimmen nicht überein.", false);

      submitBtn.disabled = true;
      submitBtn.textContent = "Wird registriert…";

      fetch("/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: user, email: email, password: pw }),
      })
        .then(function (res) {
          // Try to parse JSON, fall back to text, always resolve
          return res.json().then(function (data) {
            return { ok: res.ok, status: res.status, data: data, text: undefined };
          }).catch(function () {
            return res.text().then(function (txt) {
              var parsed = undefined;
              try {
                parsed = txt && JSON.parse(txt);
              } catch (e) {}
              return { ok: res.ok, status: res.status, data: parsed, text: txt || undefined };
            });
          });
        })
        .then(function (result) {
          submitBtn.disabled = false;
          submitBtn.textContent = "Registrieren";
          if (result.ok) {
            showMsg((result.data && result.data.message) || "Registrierung erfolgreich! Du kannst dich jetzt einloggen.", true);
            /* Clear form fields */
            panel.querySelector("#gski-reg-user").value = "";
            panel.querySelector("#gski-reg-email").value = "";
            panel.querySelector("#gski-reg-pw").value = "";
            panel.querySelector("#gski-reg-pw2").value = "";
            /* If email verification is required, keep the message visible longer */
            var delay = result.data && result.data.email_verification_required ? 8000 : 2500;
            /* Switch back to login after delay */
            setTimeout(function () {
              backLink.click();
            }, delay);
          } else {
            var detail = result.data && result.data.detail;
            if (Array.isArray(detail)) detail = detail.map(function(d) { return d.msg || JSON.stringify(d); }).join(", ");
            else if (typeof detail === "object" && detail !== null) detail = JSON.stringify(detail);
            // If no detail, try plain text
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

  function ensureRegPanel() {
    if (!isLoginPage()) return;
    if (document.getElementById(REG_ID)) return;

    var loginForm = findLoginForm();
    if (!loginForm || !loginForm.parentNode) return;

    var panel = buildRegPanel();
    loginForm.parentNode.insertBefore(panel, loginForm.nextSibling);
    attachHandlers(panel);
  }

  var observer = new MutationObserver(function () {
    ensureRegPanel();
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });
  window.addEventListener("load", ensureRegPanel);
})();
