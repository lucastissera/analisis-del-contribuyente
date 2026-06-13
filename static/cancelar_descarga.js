window.McCancelarDescarga = (function () {
  var activo = { tipo: null, jobId: null };

  function registrar(tipo, jobId) {
    activo.tipo = tipo || null;
    activo.jobId = jobId || null;
  }

  function limpiarRegistro() {
    activo.tipo = null;
    activo.jobId = null;
  }

  function cancelar() {
    if (!activo.tipo) {
      return Promise.resolve({ ok: false, sinJob: true });
    }
    return fetch("/api/cancelar-descarga", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-Requested-With": "fetch",
      },
      body: JSON.stringify({
        tipo: activo.tipo,
        job_id: activo.jobId,
      }),
    })
      .then(function (r) {
        return r.json().then(function (data) {
          return { ok: r.ok, data: data };
        });
      })
      .catch(function () {
        return { ok: false, data: {} };
      });
  }

  function enlazar(btn, opts) {
    if (!btn) return;
    var confirmMsg =
      (opts && opts.confirm) || "¿Detener el procesamiento en curso?";
    btn.addEventListener("click", function () {
      if (!activo.tipo) return;
      if (!confirm(confirmMsg)) return;
      btn.disabled = true;
      cancelar().finally(function () {
        btn.disabled = false;
        if (opts && typeof opts.onSolicitado === "function") {
          opts.onSolicitado();
        }
      });
    });
  }

  return {
    registrar: registrar,
    limpiar: limpiarRegistro,
    cancelar: cancelar,
    enlazar: enlazar,
    activo: function () {
      return activo.tipo;
    },
  };
})();
