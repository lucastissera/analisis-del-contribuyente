window.McCancelarDescarga = (function () {
  var activo = { tipo: null, jobId: null };
  var ui = null;
  var detenerPollFn = null;

  function registrar(tipo, jobId) {
    activo.tipo = tipo || null;
    activo.jobId = jobId || null;
  }

  function limpiarRegistro() {
    activo.tipo = null;
    activo.jobId = null;
  }

  function configurarUi(opts) {
    ui = opts || null;
  }

  function setDetenerPoll(fn) {
    detenerPollFn = fn;
  }

  function _resetUi(extra) {
    if (typeof detenerPollFn === "function") {
      try {
        detenerPollFn();
      } catch (e) {}
      detenerPollFn = null;
    }
    if (!ui) return;
    var msg =
      (extra && extra.mensaje) ||
      ui.mensajeCancelado ||
      "Descarga cancelada. Podés modificar los datos e iniciar de nuevo.";
    if (ui.submitBtn) {
      ui.submitBtn.disabled = false;
      if (ui.submitLabel) ui.submitBtn.textContent = ui.submitLabel;
    }
    if (ui.progreso) {
      if (ui.progresoModo === "class") ui.progreso.classList.remove("activo");
      else ui.progreso.style.display = "none";
    }
    if (ui.okBox) ui.okBox.style.display = "none";
    if (ui.errBox) {
      ui.errBox.style.display = "block";
      ui.errBox.textContent = msg;
    }
    if (ui.errProg) {
      ui.errProg.style.display = "block";
      ui.errProg.textContent = msg;
    }
    if (ui.resultado) {
      ui.resultado.innerHTML = '<p class="mensaje-error">' + msg + "</p>";
    }
    if (typeof ui.onReset === "function") {
      try {
        ui.onReset(extra);
      } catch (e) {}
    }
  }

  function _cancelarRemoto(snap) {
    return fetch("/api/cancelar-descarga", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-Requested-With": "fetch",
      },
      body: JSON.stringify({
        tipo: snap.tipo,
        job_id: snap.jobId,
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

  function abortarActivo(extra) {
    if (!activo.tipo) return Promise.resolve({ ok: false, sinJob: true });
    var snap = { tipo: activo.tipo, jobId: activo.jobId };
    _resetUi(extra);
    limpiarRegistro();
    return _cancelarRemoto(snap);
  }

  function cancelar() {
    return abortarActivo();
  }

  function enlazar(btn, opts) {
    if (!btn) return;
    if (opts) configurarUi(opts);
    var confirmMsg =
      (opts && opts.confirm) || "¿Detener el procesamiento en curso?";
    btn.addEventListener("click", function () {
      if (!activo.tipo) return;
      if (!confirm(confirmMsg)) return;
      btn.disabled = true;
      abortarActivo({
        mensaje: (opts && opts.mensajeCancelado) || (ui && ui.mensajeCancelado),
      }).finally(function () {
        btn.disabled = false;
      });
    });
  }

  return {
    registrar: registrar,
    limpiar: limpiarRegistro,
    cancelar: cancelar,
    abortarActivo: abortarActivo,
    enlazar: enlazar,
    configurarUi: configurarUi,
    setDetenerPoll: setDetenerPoll,
    activo: function () {
      return activo.tipo;
    },
  };
})();
