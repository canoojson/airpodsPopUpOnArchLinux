--!nonstrict
-- Vista de ajustes del panel: nombre del dispositivo, preferencias de airpodsd, ajustes
-- de los AirPods (con la conexión AAP de airpodsd), comprobación automática de
-- actualizaciones y búsqueda/instalación manual. Todo pasa por airpodsctl (ruta
-- absoluta publicada por airpodsd en status.json, para no depender del PATH).

local M = {}

local draftName = nil     -- texto del campo de nombre mientras se edita
local message = nil       -- { text, color } bajo los controles
local checkResult = nil   -- salida de `airpodsctl update --check --json`
local busy = nil          -- "name" | "toggle" | "check" | "update"

local function ctl(status)
  return (status and status.ctl) or "airpodsctl"
end

function M.reset()
  draftName = nil
  message = nil
  checkResult = nil
  busy = nil
end

local function run(status, args, what, timeout, done, rerender)
  if busy ~= nil then return end
  busy = what
  message = nil
  rerender()
  local argv = { ctl(status) }
  for _, a in ipairs(args) do table.insert(argv, a) end
  noctalia.runAsync(argv, function(result)
    busy = nil
    done(result)
    rerender()
  end, timeout)
end

local function saveName(status, refresh, rerender)
  local name = draftName
  if name == nil then return end
  run(status, { "rename", name }, "name", 8000, function(result)
    if result.exitCode == 0 then
      message = { text = "Nombre actualizado", color = "primary" }
      draftName = nil
      refresh()
    else
      message = { text = "No se pudo cambiar el nombre", color = "error" }
    end
  end, rerender)
end

local function setOption(status, key, enabled, refresh, rerender)
  run(status, { "config", "set", key, enabled and "true" or "false" }, "toggle", 8000, function(result)
    if result.exitCode ~= 0 then
      message = { text = "No se pudo guardar el ajuste", color = "error" }
    end
    refresh()
  end, rerender)
end

-- Ajuste de los propios AirPods por AAP (airpodsctl feature).
local function setFeature(status, name, enabled, refresh, rerender)
  run(status, { "feature", name, enabled and "on" or "off" }, "toggle", 8000, function(result)
    if result.exitCode ~= 0 then
      message = { text = "Los AirPods no aceptaron el cambio", color = "error" }
    end
    refresh()
  end, rerender)
end

local function checkNow(status, common, rerender)
  run(status, { "update", "--check", "--json" }, "check", 20000, function(result)
    checkResult = common.decode(result.stdout)
    if checkResult == nil or checkResult.error ~= nil then
      message = { text = "No se pudo consultar GitHub", color = "error" }
      checkResult = nil
    elseif checkResult.available then
      message = { text = "Versión " .. checkResult.latest .. " disponible", color = "primary" }
    else
      message = { text = "Tienes la última versión (" .. checkResult.current .. ")", color = "on_surface/0.7" }
    end
  end, rerender)
end

local function updateNow(status, refresh, rerender)
  run(status, { "update", "--yes" }, "update", 300000, function(result)
    if result.exitCode == 0 then
      message = { text = "Actualizado. Reabre el panel para ver los cambios", color = "primary" }
      checkResult = nil
    else
      message = { text = "La actualización falló: ejecuta airpodsctl update en una terminal", color = "error" }
    end
    refresh()
  end, rerender)
end

-- Devuelve el árbol de la vista de ajustes.
-- opts: { common, refresh = fn, rerender = fn, back = fn }
function M.render(status, opts)
  local common, refresh, rerender = opts.common, opts.refresh, opts.rerender
  local upd = (status and status.update) or {}
  -- Una búsqueda manual manda sobre el estado del daemon, que puede estar desfasado.
  local src = checkResult or upd
  local available, latest, managed = src.available, src.latest, src.managed
  local currentName = (status and status.name) or ""
  local ear = (status and status.ear) or {}
  local audio = (status and status.audio) or {}
  local alerts = (status and status.alerts) or {}
  local aap = (status and status.aap) or {}
  local device = (aap.owner == "airpodsd" and aap.connected and aap.settings) or nil

  local function toggleRow(key, title, subtitle, checked, onToggle)
    return common.listRow(key, {
      title = title, subtitle = subtitle,
      trailing = ui.toggle({ key = key .. "-toggle", checked = checked, enabled = busy == nil,
                             onChange = function(v) onToggle(v == "true") end }),
    })
  end

  -- Fila de acción en color, como "Buscar actualizaciones" en Ajustes de iOS.
  local function actionRow(key, title, onClick, enabled)
    return common.listRow(key, { title = title, titleColor = enabled and "primary" or common.SECONDARY,
                                 onClick = enabled and onClick or nil })
  end

  -- "‹ AirPods" para volver, con el título grande debajo, como en iOS.
  local header = ui.column({ key = "s-header", gap = 6 }, {
    ui.row({ key = "s-back", gap = 2, align = "center", onClick = opts.back }, {
      ui.glyph({ name = "chevron-left", size = 18, color = "primary" }),
      ui.label({ text = "AirPods", fontSize = 14, color = "primary" }),
    }),
    ui.label({ text = "Ajustes", fontSize = 22, fontWeight = "bold" }),
  })

  local children = {
    common.sectionHeader("s-name-h", "Nombre"),
    common.group("s-name-g", {
      ui.row({ key = "s-name", gap = 8, align = "center", paddingH = 10, paddingV = 8 }, {
        ui.input({ key = "s-name-input", value = currentName, placeholder = (status and status.model_name) or "AirPods",
                   submitOnEnter = true, flexGrow = 1, enabled = status ~= nil and status.address ~= nil,
                   onChange = function(v) draftName = v end,
                   onSubmit = function(v) draftName = v; saveName(status, refresh, rerender) end }),
        ui.row({ key = "s-name-save", width = 30, height = 30, radius = 15, align = "center", justify = "center",
                 fill = (draftName ~= nil and busy == nil) and "primary" or "on_surface/0.1",
                 onClick = function() if draftName ~= nil and busy == nil then saveName(status, refresh, rerender) end end }, {
          ui.glyph({ name = busy == "name" and "refresh" or "check", size = 15,
                     color = (draftName ~= nil and busy == nil) and "on_primary" or common.SECONDARY }),
        }),
      }),
    }),
    common.sectionFooter("s-name-f", "Es el nombre en este equipo; tu iPhone sigue viendo el suyo."),

    common.sectionHeader("s-audio-h", "Audio"),
    common.group("s-audio-g", {
      toggleRow("s-route", "Pasar el audio al ponértelos", "Si están en la caja, sigue sonando por donde estaba",
                audio.follow_ear ~= false, function(v) setOption(status, "audio_follow_ear", v, refresh, rerender) end),
      toggleRow("s-pause", "Pausar al quitarte uno", "También con uno en la caja y otro puesto",
                ear.pause ~= false, function(v) setOption(status, "ear_pause", v, refresh, rerender) end),
      toggleRow("s-resume", "Reanudar al volver a ponértelo", "Si vuelve a la oreja en menos de 2 min",
                ear.resume ~= false, function(v) setOption(status, "ear_resume", v, refresh, rerender) end),
      toggleRow("s-duck", "Bajar el volumen al hablar", "Con la detección de conversación activada",
                aap.conversation_duck ~= false, function(v) setOption(status, "conversation_duck", v, refresh, rerender) end),
    }),

    common.sectionHeader("s-bat-h", "Batería"),
    common.group("s-bat-g", {
      toggleRow("s-lowbat", "Avisar con batería baja", "Al 20 % y al 10 %, una vez por carga",
                alerts.low_battery ~= false, function(v) setOption(status, "low_battery_alert", v, refresh, rerender) end),
    }),
  }

  if device ~= nil and (device.one_bud_anc ~= nil or device.volume_swipe ~= nil) then
    local rows = {}
    if device.one_bud_anc ~= nil then
      table.insert(rows, toggleRow("s-onebud", "Cancelación con un auricular", "Mantener el modo con uno solo puesto",
                                   device.one_bud_anc == true, function(v) setFeature(status, "one_bud_anc", v, refresh, rerender) end))
    end
    if device.volume_swipe ~= nil then
      table.insert(rows, toggleRow("s-swipe", "Volumen deslizando en el tallo", "Desliza arriba o abajo en el sensor",
                                   device.volume_swipe == true, function(v) setFeature(status, "volume_swipe", v, refresh, rerender) end))
    end
    table.insert(children, common.sectionHeader("s-dev-h", "AirPods"))
    table.insert(children, common.group("s-dev-g", rows))
  end

  local updRows = {
    toggleRow("s-auto", "Buscar automáticamente", "Consulta GitHub una vez al día",
              upd.enabled == true, function(v) setOption(status, "update_check", v, refresh, rerender) end),
    actionRow("s-check", busy == "check" and "Buscando…" or "Buscar actualizaciones",
              function() checkNow(status, common, rerender) end, busy == nil),
  }
  if available and managed then
    table.insert(updRows, actionRow("s-update", busy == "update" and "Actualizando…" or ("Actualizar a la versión " .. latest),
                                    function() updateNow(status, refresh, rerender) end, busy == nil))
  end
  table.insert(children, common.sectionHeader("s-upd-h", "Actualizaciones"))
  table.insert(children, common.group("s-upd-g", updRows))

  local footer = nil
  if message ~= nil then
    footer = { text = message.text, color = message.color }
  elseif available and not managed then
    footer = { text = (upd.install == "package") and "Instalado como paquete: actualiza con tu gestor de paquetes."
                      or "Instalación de desarrollo: actualiza con git pull." }
  end
  if footer then table.insert(children, common.sectionFooter("s-upd-f", footer.text, footer.color)) end
  table.insert(children, ui.label({ key = "s-version", text = "AirPods Linux " .. ((status and status.version) or "?"),
                                    fontSize = 11, color = "on_surface/0.4", textAlign = "center" }))

  return ui.column({ padding = 18, gap = 12, fill = "surface", radius = 24, flexGrow = 1 }, {
    header,
    ui.scroll({ key = "s-scroll", flexGrow = 1 }, { common.scrollBody("s", 8, children) }),
  })
end

return M
