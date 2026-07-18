/**
 * Latido del .exe portable. Si el usuario cierra la ventana (X), deja de latir
 * y el servidor apaga el proceso. Si solo minimiza u oculta la ventana, no cuenta
 * como cierre (visibility hidden).
 */
(function () {
  if (!window.MC_MODO_ESCRITORIO) return;

  var INTERVALO_MS = 8000;
  var ventanaVisible = !document.hidden;

  function latido() {
    try {
      fetch("/desktop/alive", {
        method: "POST",
        credentials: "same-origin",
        keepalive: true,
        headers: {
          "X-Requested-With": "fetch",
          "X-Desktop-Visible": ventanaVisible ? "1" : "0",
        },
      }).catch(function () {});
    } catch (e) {}
  }

  document.addEventListener("visibilitychange", function () {
    ventanaVisible = !document.hidden;
    if (ventanaVisible) latido();
  });

  latido();
  setInterval(latido, INTERVALO_MS);
})();
