(function () {
  "use strict";

  var cfgEl = document.getElementById("admin-cursor-config");
  var i18nEl = document.getElementById("i18n-js");
  var cfg = cfgEl ? JSON.parse(cfgEl.textContent || "{}") : {};
  var I = i18nEl ? JSON.parse(i18nEl.textContent || "{}") : {};

  var STORAGE_KEY = "aic_cursor_agent_id";
  var mensajesEl = document.getElementById("mensajes");
  var form = document.getElementById("form-chat");
  var input = document.getElementById("input-texto");
  var btnEnviar = document.getElementById("btn-enviar");
  var btnNueva = document.getElementById("btn-nueva");
  var btnCancelar = document.getElementById("btn-cancelar");
  var btnProbar = document.getElementById("btn-probar-api");
  var estadoRun = document.getElementById("estado-run");
  var avisoConfig = document.getElementById("aviso-config");
  var linkAgente = document.getElementById("link-agente");
  var checksLista = document.getElementById("checks-lista");
  var flujoPasos = document.getElementById("flujo-pasos");
  var panelGit = document.getElementById("panel-git");
  var gitResumen = document.getElementById("git-resumen");
  var gitLinks = document.getElementById("git-links");

  var agentId = null;
  var runId = null;
  var agentUrl = null;
  var eventSource = null;
  var asistenteActual = null;
  var ocupado = false;
  var pollTimer = null;
  var vioPush = false;

  function t(key, fallback) {
    return I[key] || fallback || key;
  }

  function setEstado(texto, activo) {
    if (!estadoRun) return;
    estadoRun.textContent = texto;
    estadoRun.classList.toggle("activo", !!activo);
  }

  function setOcupado(val) {
    ocupado = !!val;
    if (btnEnviar) btnEnviar.disabled = ocupado || !cfg.ready;
    if (input) input.disabled = ocupado || !cfg.ready;
    if (btnCancelar) btnCancelar.hidden = !ocupado;
  }

  function marcarPaso(paso, estado) {
    if (!flujoPasos) return;
    var li = flujoPasos.querySelector('[data-paso="' + paso + '"]');
    if (!li) return;
    li.classList.remove("activo", "hecho");
    if (estado) li.classList.add(estado);
  }

  function resetFlujo() {
    if (!flujoPasos) return;
    flujoPasos.querySelectorAll("li").forEach(function (li) {
      li.classList.remove("activo", "hecho");
    });
    vioPush = false;
  }

  function renderChecks(data) {
    cfg = data || cfg;
    if (!checksLista) return;
    checksLista.innerHTML = "";
    (cfg.checks || []).forEach(function (c) {
      var li = document.createElement("li");
      li.className = c.ok ? "ok" : "fail";
      li.textContent = c.mensaje || c.id;
      checksLista.appendChild(li);
    });
    if (avisoConfig) {
      if (cfg.ready) {
        avisoConfig.hidden = true;
      } else {
        avisoConfig.hidden = false;
        avisoConfig.textContent = t(
          "admin_cursor_err_checks",
          "Completá la configuración antes de enviar."
        );
      }
    }
    setOcupado(ocupado);
    if (avisoConfig && !cfg.ready && cfg.diagnostico) {
      var d = cfg.diagnostico;
      var extra = [];
      if (d.api_key_len) extra.push("API key: " + d.api_key_len + " chars");
      if (cfg.repo_url_raw && !cfg.repo_url) {
        extra.push("Repo con formato inválido: " + cfg.repo_url_raw);
      }
      if (d.vars_cursor && d.vars_cursor.length) {
        extra.push("Vars: " + d.vars_cursor.join(", "));
      }
      if (extra.length) {
        avisoConfig.textContent += " (" + extra.join(" · ") + ")";
      }
    }
  }

  function cargarEstado(probar) {
    var url = "/admin/cursor/estado" + (probar ? "?probar=1" : "");
    return fetch(url)
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        renderChecks(data);
        return data;
      });
  }

  function guardarAgentId(id) {
    agentId = id || null;
    try {
      if (agentId) localStorage.setItem(STORAGE_KEY, agentId);
      else localStorage.removeItem(STORAGE_KEY);
    } catch (e) {}
  }

  function cargarAgentId() {
    try {
      return localStorage.getItem(STORAGE_KEY) || null;
    } catch (e) {
      return null;
    }
  }

  function actualizarLinkAgente() {
    if (!linkAgente) return;
    if (agentUrl) {
      linkAgente.href = agentUrl;
      linkAgente.hidden = false;
    } else {
      linkAgente.hidden = true;
    }
  }

  function agregarMensaje(tipo, texto, meta) {
    if (!mensajesEl || !texto) return null;
    var div = document.createElement("div");
    div.className = "msg msg-" + tipo;
    if (meta) {
      var m = document.createElement("div");
      m.className = "msg-meta";
      m.textContent = meta;
      div.appendChild(m);
    }
    var body = document.createElement("div");
    body.textContent = texto;
    div.appendChild(body);
    mensajesEl.appendChild(div);
    mensajesEl.scrollTop = mensajesEl.scrollHeight;
    return body;
  }

  function agregarTool(nombre, detalle) {
    agregarMensaje("tool", detalle, nombre || "tool");
    var low = (detalle || "").toLowerCase();
    if (
      low.indexOf("push") >= 0 ||
      low.indexOf("commit") >= 0 ||
      low.indexOf("git") >= 0
    ) {
      vioPush = true;
      marcarPaso("push", "hecho");
    }
  }

  function mostrarGit(run) {
    if (!panelGit || !run) return;
    var branches = run.branches || [];
    if (!branches.length && !run.result) return;

    panelGit.hidden = false;
    if (gitLinks) gitLinks.innerHTML = "";

    var prUrl = null;
    var branchUrl = null;
    branches.forEach(function (b) {
      if (b.pr_url) prUrl = b.pr_url;
      if (b.branch_url) branchUrl = b.branch_url;
    });

    if (gitResumen) {
      var branchName = cfg.branch || "main";
      gitResumen.textContent = t(
        "admin_cursor_push_ok",
        "Código pusheado. Mergeá a " + branchName + " para actualizar Render."
      ).replace("{branch}", branchName);
    }

    if (gitLinks) {
      if (prUrl) {
        var aPr = document.createElement("a");
        aPr.href = prUrl;
        aPr.target = "_blank";
        aPr.rel = "noopener";
        aPr.textContent = t("admin_cursor_ver_pr", "Abrir pull request");
        gitLinks.appendChild(aPr);
        marcarPaso("pr", "hecho");
      }
      if (branchUrl) {
        var aBr = document.createElement("a");
        aBr.href = branchUrl;
        aBr.target = "_blank";
        aBr.rel = "noopener";
        aBr.textContent = t("admin_cursor_ver_rama", "Ver rama en GitHub");
        gitLinks.appendChild(aBr);
      }
    }
    if (prUrl || branchUrl) {
      marcarPaso("push", "hecho");
    }
  }

  function cerrarStream() {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
  }

  function detenerPoll() {
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
  }

  function pollRun(intentos) {
    if (!agentId || !runId) return;
    detenerPoll();
    fetch(
      "/admin/cursor/run/" +
        encodeURIComponent(agentId) +
        "/" +
        encodeURIComponent(runId)
    )
      .then(function (r) {
        return r.json().then(function (body) {
          if (!r.ok) throw new Error((body && body.error) || r.statusText);
          return body;
        });
      })
      .then(function (body) {
        var run = body.run || {};
        if (run.branches && run.branches.length) {
          mostrarGit(run);
        }
        if (run.terminal) {
          if (run.result && !asistenteActual) {
            asistenteActual = agregarMensaje(
              "asistente",
              run.result,
              t("admin_cursor_asistente", "Cursor Cloud")
            );
          }
          finalizarRun(
            t("admin_cursor_estado_fin", "Finalizado") + ": " + (run.status || "")
          );
          return;
        }
        if (intentos > 0) {
          setEstado(t("admin_cursor_esperando_git", "Esperando commit/push…"), true);
          pollTimer = setTimeout(function () {
            pollRun(intentos - 1);
          }, 4000);
        } else {
          finalizarRun(t("admin_cursor_estado_listo", "Listo"));
        }
      })
      .catch(function () {
        if (intentos > 0) {
          pollTimer = setTimeout(function () {
            pollRun(intentos - 1);
          }, 5000);
        } else {
          finalizarRun(t("admin_cursor_estado_listo", "Listo"));
        }
      });
  }

  function finalizarRun(estadoTexto) {
    cerrarStream();
    detenerPoll();
    setOcupado(false);
    asistenteActual = null;
    setEstado(estadoTexto || t("admin_cursor_estado_listo", "Listo"), false);
    marcarPaso("agente", "hecho");
    if (agentId && runId) {
      pollRun(8);
    }
  }

  function manejarEvento(tipo, data) {
    if (tipo === "assistant" && data && data.text) {
      marcarPaso("agente", "activo");
      if (!asistenteActual) {
        asistenteActual = agregarMensaje(
          "asistente",
          "",
          t("admin_cursor_asistente", "Cursor Cloud")
        );
      }
      if (asistenteActual) asistenteActual.textContent += data.text;
      if (mensajesEl) mensajesEl.scrollTop = mensajesEl.scrollHeight;
      return;
    }
    if (tipo === "status" && data && data.status) {
      marcarPaso("agente", "activo");
      setEstado(
        t("admin_cursor_estado_run", "Ejecutando") + ": " + data.status,
        true
      );
      return;
    }
    if (tipo === "tool_call" && data) {
      var det = data.name || "tool";
      if (data.status) det += " — " + data.status;
      if (data.args && data.args.path) det += " (" + data.args.path + ")";
      agregarTool(data.name, det);
      return;
    }
    if (tipo === "result" && data) {
      if (data.text && !asistenteActual) {
        asistenteActual = agregarMensaje(
          "asistente",
          data.text,
          t("admin_cursor_asistente", "Cursor Cloud")
        );
      } else if (data.text && asistenteActual && !asistenteActual.textContent) {
        asistenteActual.textContent = data.text;
      }
      if (data.git) {
        mostrarGit({ branches: (data.git.branches || []).map(function (b) {
          return {
            repo: b.repoUrl,
            branch: b.branch,
            pr_url: b.prUrl,
            branch_url: b.repoUrl && b.branch
              ? "https://" + b.repoUrl + "/tree/" + b.branch
              : null,
          };
        })});
      }
      var fin = data.status || "FINISHED";
      finalizarRun(t("admin_cursor_estado_fin", "Finalizado") + ": " + fin);
      return;
    }
    if (tipo === "cursor_error") {
      agregarMensaje(
        "sistema",
        (data && data.message) || t("admin_cursor_err_stream", "Error en el stream")
      );
      pollRun(5);
      return;
    }
    if (tipo === "done") {
      setOcupado(false);
      pollRun(8);
    }
  }

  function abrirStream(aid, rid) {
    cerrarStream();
    setOcupado(true);
    setEstado(t("admin_cursor_estado_run", "Ejecutando") + "…", true);
    asistenteActual = null;
    marcarPaso("agente", "activo");

    var url =
      "/admin/cursor/stream/" +
      encodeURIComponent(aid) +
      "/" +
      encodeURIComponent(rid);
    eventSource = new EventSource(url);

    ["assistant", "status", "tool_call", "result", "done"].forEach(function (ev) {
      eventSource.addEventListener(ev, function (e) {
        manejarEvento(ev === "done" ? "done" : ev, e.data ? JSON.parse(e.data) : {});
      });
    });

    eventSource.addEventListener("cursor_error", function (ev) {
      if (ev.data) {
        try {
          manejarEvento("cursor_error", JSON.parse(ev.data));
        } catch (e) {
          manejarEvento("cursor_error", { message: ev.data });
        }
      }
    });

    eventSource.onerror = function () {
      if (!ocupado) return;
      agregarMensaje(
        "sistema",
        t("admin_cursor_err_conexion", "Stream interrumpido; consultando estado…")
      );
      cerrarStream();
      setOcupado(false);
      pollRun(12);
    };
  }

  function enviarMensaje(texto) {
    if (!cfg.ready) {
      agregarMensaje(
        "sistema",
        t("admin_cursor_err_checks", "Completá la configuración antes de enviar.")
      );
      return;
    }
    resetFlujo();
    if (panelGit) panelGit.hidden = true;
    marcarPaso("enviado", "hecho");
    marcarPaso("agente", "activo");

    agregarMensaje("usuario", texto, t("admin_cursor_vos", "Vos"));
    setOcupado(true);

    fetch("/admin/cursor/mensaje", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: texto,
        agent_id: agentId,
      }),
    })
      .then(function (r) {
        return r.json().then(function (body) {
          if (!r.ok) {
            var err = new Error((body && body.error) || r.statusText);
            err.helpUrl = body && body.help_url;
            throw err;
          }
          return body;
        });
      })
      .then(function (body) {
        agentId = body.agent_id || agentId;
        runId = body.run_id;
        agentUrl = body.agent_url || agentUrl;
        guardarAgentId(agentId);
        actualizarLinkAgente();
        if (agentId && runId) abrirStream(agentId, runId);
        else {
          setOcupado(false);
          agregarMensaje(
            "sistema",
            t("admin_cursor_err_sin_run", "No se recibió un run válido.")
          );
        }
      })
      .catch(function (err) {
        setOcupado(false);
        marcarPaso("agente", "");
        agregarMensaje("sistema", String(err.message || err));
        if (err.helpUrl) {
          agregarMensaje("sistema", err.helpUrl);
        }
        setEstado(t("admin_cursor_estado_error", "Error"), false);
      });
  }

  function nuevaConversacion() {
    cerrarStream();
    detenerPoll();
    agentId = null;
    runId = null;
    agentUrl = null;
    guardarAgentId(null);
    actualizarLinkAgente();
    resetFlujo();
    setOcupado(false);
    setEstado(t("admin_cursor_estado_listo", "Listo"), false);
    if (panelGit) panelGit.hidden = true;
    if (mensajesEl) {
      mensajesEl.innerHTML = "";
      agregarMensaje("sistema", t("admin_cursor_nueva_ok", "Nueva conversación."));
    }
  }

  function cancelarRun() {
    if (!agentId || !runId) return;
    fetch(
      "/admin/cursor/cancelar/" +
        encodeURIComponent(agentId) +
        "/" +
        encodeURIComponent(runId),
      { method: "POST" }
    ).finally(function () {
      agregarMensaje("sistema", t("admin_cursor_cancelado", "Ejecución cancelada."));
      finalizarRun(t("admin_cursor_estado_cancelado", "Cancelado"));
    });
  }

  if (form) {
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      if (ocupado || !cfg.ready) return;
      var texto = (input && input.value || "").trim();
      if (!texto) return;
      if (input) input.value = "";
      enviarMensaje(texto);
    });
  }
  if (btnNueva) btnNueva.addEventListener("click", nuevaConversacion);
  if (btnCancelar) btnCancelar.addEventListener("click", cancelarRun);
  if (btnProbar) {
    btnProbar.addEventListener("click", function () {
      btnProbar.disabled = true;
      cargarEstado(true).finally(function () {
        btnProbar.disabled = false;
      });
    });
  }

  agentId = cargarAgentId();
  renderChecks(cfg);
  setEstado(t("admin_cursor_estado_listo", "Listo"), false);
})();
