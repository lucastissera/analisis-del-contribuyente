/**
 * CSRF para formularios POST y fetch same-origin (Flask-WTF).
 * Requiere window.CSRF_TOKEN (inyectado desde la barra superior).
 */
(function () {
  function token() {
    return (typeof window.CSRF_TOKEN === "string" && window.CSRF_TOKEN) || "";
  }

  function asegurarCampoForm(form) {
    if (!form || !form.tagName || form.tagName.toUpperCase() !== "FORM") return;
    var method = (form.getAttribute("method") || "get").toLowerCase();
    if (method !== "post") return;
    if (form.querySelector('input[name="csrf_token"]')) return;
    var t = token();
    if (!t) return;
    var input = document.createElement("input");
    input.type = "hidden";
    input.name = "csrf_token";
    input.value = t;
    form.appendChild(input);
  }

  function inyectarEnFormularios(root) {
    var forms = (root || document).querySelectorAll("form");
    for (var i = 0; i < forms.length; i++) asegurarCampoForm(forms[i]);
  }

  function esMismaOrigen(url) {
    try {
      var u = new URL(url, window.location.href);
      return u.origin === window.location.origin;
    } catch (e) {
      return true;
    }
  }

  function metodoMutador(method) {
    var m = (method || "GET").toUpperCase();
    return m === "POST" || m === "PUT" || m === "PATCH" || m === "DELETE";
  }

  if (typeof window.fetch === "function") {
    var fetchOrig = window.fetch.bind(window);
    window.fetch = function (input, init) {
      init = init ? Object.assign({}, init) : {};
      var url = typeof input === "string" ? input : input && input.url;
      var method =
        (init.method ||
          (input && input.method) ||
          "GET").toString();
      if (metodoMutador(method) && url && esMismaOrigen(url)) {
        var t = token();
        if (t) {
          var headers = new Headers(init.headers || (input && input.headers) || undefined);
          if (!headers.has("X-CSRFToken") && !headers.has("X-CSRF-Token")) {
            headers.set("X-CSRFToken", t);
          }
          init.headers = headers;
        }
      }
      return fetchOrig(input, init);
    };
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      inyectarEnFormularios(document);
    });
  } else {
    inyectarEnFormularios(document);
  }

  window.MC_CSRF = { injectForms: inyectarEnFormularios, token: token };
})();
