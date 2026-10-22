--!nonstrict
-- Panel desplegable con aspecto de iOS: batería de cada auricular y de la caja
-- (airpodsd, también con la caja cerrada), control de ruido, detección de conversación
-- iPhone por AirPlay (UxPlay) y gráfica de las últimas 24 h. El modo va por la conexión AAP de airpodsd o,
-- si la tiene airpods-helper, por airpods-cli.

local common = require("./lib/common.luau")
local settings = require("./lib/settings.luau")

local STATUS_KEY = "airpods.status"
local TRACK_WIDTH = 288   -- ancho útil del scroll (panel - márgenes - barra - hueco derecho)
local HAS_ANC_TOOL = noctalia.commandExists("airpods-cli")

-- Orden de los segmentos, de izquierda a derecha, como el control "Modo de escucha" de iOS.
local MODE_ORDER = { "transparency", "adaptive", "noise" }
local MODE_LABELS = { transparency = "Sonido ambiente", adaptive = "Adaptativo", noise = "Cancelación de ruido" }
local MODE_GLYPHS = { transparency = "sun", adaptive = "wave-sine", noise = "target" }

local status = nil      -- airpodsd
local anc = nil         -- airpods-cli status --json (opcional)
local panelOpen = false
local busy = false
local pendingMode = nil
local connecting = false
local view = "main"     -- "main" | "settings"
local render

-- ¿Tiene airpodsd su propia conexión AAP? Entonces el modo va por airpodsctl.
local function ownAap()
  local a = status and status.aap
  return a ~= nil and a.owner == "airpodsd" and a.connected == true
end

local function aapSetting(name)
  local a = status and status.aap
  return a and a.settings and a.settings[name]
end

local function currentMode()
  if ownAap() then return aapSetting("listening_mode") end
  return anc and anc.anc_mode
end

local function ctl()
  return (status and status.ctl) or "airpodsctl"
end

local function hasFeature(name)
  if anc == nil or anc.features == nil then return false end
  for _, f in ipairs(anc.features) do
    if f == name then return true end
  end
  return false
end

local function availableModes()
  local modes = {}
  if ownAap() then
    local offered = {}
    for _, m in ipairs(status.aap.modes or {}) do offered[m] = true end
    for _, m in ipairs(MODE_ORDER) do
      if offered[m] then table.insert(modes, m) end
    end
    return modes
  end
  if not hasFeature("anc") then return modes end
  for _, m in ipairs(MODE_ORDER) do
    if m ~= "adaptive" or hasFeature("adaptive") then table.insert(modes, m) end
  end
  return modes
end

local function refresh()
  common.read(function(s)
    noctalia.state.set(STATUS_KEY, s and noctalia.json.encode(s) or "")
  end)
  -- airpods-cli despierta a airpods-helper por D-Bus: solo se le pregunta si ya está en
  -- marcha (o si el daemon es antiguo y no lo dice), para no quitarle el canal AAP a airpodsd.
  local aap = status and status.aap
  local helperRunning = aap == nil or aap.owner == "airpods-helper"
  if HAS_ANC_TOOL and panelOpen and helperRunning then
    noctalia.runAsync({ "airpods-cli", "status", "--json" }, function(result)
      anc = (result.exitCode == 0) and common.decode(result.stdout) or nil
      render()
    end, 5000)
  elseif not helperRunning then
    anc = nil   -- dato viejo de airpods-helper: ya no manda él
  end
end

-- Cambia el modo y espera a que airpods-helper lo confirme (los AirPods tardan
-- 0,8-1,5 s); si lo rechazan (p. ej. sin auriculares puestos) vuelve al modo real.
local APPLY_SCRIPT = [[
airpods-cli anc "$1" >/dev/null || exit 1
i=0
while [ "$i" -lt 25 ]; do
  i=$((i + 1))
  out=$(airpods-cli status --json)
  case "$out" in *"\"anc_mode\": \"$1\""*) break ;; esac
  sleep 0.2
done
printf '%s' "$out"
]]

local function applyMode(mode)
  pendingMode = mode
  if busy then return end
  busy = true
  if ownAap() then
    -- airpodsctl mode espera a que los AirPods confirmen el cambio.
    noctalia.runAsync({ ctl(), "mode", mode }, function(result)
      busy = false
      if result.exitCode ~= 0 then
        pendingMode = nil
        noctalia.notifyError("AirPods", (result.stderr ~= "" and result.stderr) or "No se pudo cambiar el modo")
      elseif pendingMode ~= nil and pendingMode ~= mode then
        applyMode(pendingMode)
        return
      end
      pendingMode = nil
      refresh()
    end, 8000)
    return
  end
  noctalia.runAsync({ "sh", "-c", APPLY_SCRIPT, "sh", mode }, function(result)
    busy = false
    if result.exitCode ~= 0 then
      pendingMode = nil
      noctalia.notifyError("AirPods", (result.stderr ~= "" and result.stderr) or "No se pudo cambiar el modo")
      refresh()
      return
    end
    if pendingMode ~= nil and pendingMode ~= mode then
      applyMode(pendingMode) -- llegó otra selección mientras tanto
    else
      pendingMode = nil
    end
    anc = common.decode(result.stdout) or anc
    render()
  end, 8000)
end

local function selectMode(mode)
  if (anc == nil and not ownAap()) or mode == (pendingMode or currentMode()) then return end
  applyMode(mode)
  render()
end

local function connect()
  if connecting or status == nil or status.address == nil then return end
  connecting = true
  render()
  noctalia.runAsync({ "bluetoothctl", "connect", status.address }, function(result)
    connecting = false
    if result.exitCode ~= 0 then noctalia.notifyError("AirPods", "No se pudo conectar") end
    refresh()
  end, 15000)
end

-- Botón redondo pequeño (ajustes), como los de las tarjetas de iOS.
local function roundButton(key, glyph, onClick)
  return ui.row({ key = key, width = 30, height = 30, radius = 15, align = "center", justify = "center",
                  fill = "on_surface/0.1", onClick = onClick }, {
    ui.glyph({ name = glyph, size = 15, color = "on_surface/0.7" }),
  })
end

-- Control de ruido como en el Centro de control de iOS: un botón redondo por modo.
local function ancSection(children)
  local modes = availableModes()
  if #modes == 0 or not (ownAap() or (anc and anc.connected)) then return end
  local current = pendingMode or currentMode()
  -- flexGrow no reparte el ancho de una fila aquí: se calcula a mano.
  local cellWidth = math.floor((TRACK_WIDTH - 28) / #modes)
  local cells = {}
  for _, m in ipairs(modes) do
    local selected = (m == current)
    table.insert(cells, ui.column({ key = "mode-" .. m, width = cellWidth, gap = 8, align = "center",
                                    onClick = function() selectMode(m) end }, {
      ui.row({ key = "mode-" .. m .. "-c", width = 54, height = 54, radius = 27, align = "center", justify = "center",
               -- Relleno explícito también sin seleccionar: nil conservaría el anterior.
               fill = selected and "primary" or "on_surface/0.1" }, {
        ui.glyph({ name = MODE_GLYPHS[m], size = 24, color = selected and "on_primary" or "on_surface" }),
      }),
      ui.label({ text = MODE_LABELS[m], fontSize = 11, maxLines = 2, maxWidth = cellWidth - 4, textAlign = "center",
                 color = selected and "on_surface" or common.SECONDARY, fontWeight = selected and "semibold" or "normal" }),
    }))
  end
  local earsOut
  if ownAap() then
    earsOut = not common.field(status, "left_in_ear") and not common.field(status, "right_in_ear")
  else
    earsOut = anc.ear_left == false and anc.ear_right == false
  end
  table.insert(children, common.sectionHeader("anc-title", "Control de ruido"))
  table.insert(children, ui.column({ key = "anc-card", radius = 14, fill = common.CARD, paddingV = 14, paddingH = 14 }, {
    ui.row({ key = "anc-cells", gap = 0 }, cells),
  }))
  -- Los AirPods ignoran el cambio de modo si no hay ningún auricular puesto.
  if earsOut then
    table.insert(children, common.sectionFooter("anc-hint", "Ponte un auricular para cambiar el modo."))
  end
end

local caBusy = false

-- Detección de conversación (solo con la conexión AAP de airpodsd).
local function conversationSection(children)
  local ca = aapSetting("conversational_awareness")
  if not ownAap() or ca == nil then return end
  -- En llamada airpodsd la mantiene siempre desactivada: el interruptor no se puede tocar.
  local inCall = status.aap and status.aap.in_call == true
  table.insert(children, common.group("ca-group", {
    common.listRow("ca", {
      glyph = "message-circle", title = "Detección de conversación",
      subtitle = inCall and "Desactivada durante la llamada" or "Baja el volumen y deja pasar el sonido al hablar",
      trailing = ui.toggle({ key = "ca-toggle", checked = ca == true and not inCall, enabled = not caBusy and not inCall,
                             onChange = function(v)
        caBusy = true
        render()
        noctalia.runAsync({ ctl(), "feature", "conversational_awareness", v == "true" and "on" or "off" }, function(result)
          caBusy = false
          if result.exitCode ~= 0 then noctalia.notifyError("AirPods", "No se pudo cambiar la detección de conversación") end
          refresh()
        end, 8000)
      end }),
    }),
  }))
end

-- El iPhone por AirPlay (UxPlay): suena en el PC a la vez que el resto, con su propio volumen.
local airplayDraft = nil   -- volumen mientras se arrastra el control
local airplayBusy = false

local function setAirplayVolume(v)
  if airplayBusy then return end
  airplayBusy = true
  noctalia.runAsync({ ctl(), "airplay", tostring(v) }, function(result)
    airplayBusy = false
    airplayDraft = nil
    if result.exitCode ~= 0 then noctalia.notifyError("AirPods", "No se pudo cambiar el volumen de AirPlay") end
    refresh()
  end, 5000)
end

local function airplaySection(children)
  local ap = status.airplay
  if ap == nil or not ap.playing then return end
  local what = ap.title and (ap.artist and (ap.title .. " · " .. ap.artist) or ap.title) or "Sonando a la vez que el PC"
  local rows = {
    common.listRow("airplay", { glyph = "device-mobile", title = "iPhone por AirPlay", subtitle = what }),
  }
  local volume = airplayDraft or ap.volume
  if volume ~= nil then
    table.insert(rows, ui.row({ key = "airplay-vol", gap = 10, align = "center", paddingH = 14, paddingV = 6 }, {
      ui.glyph({ name = "volume-2", size = 16, color = common.SECONDARY }),
      ui.slider({ key = "airplay-slider", min = 0, max = 100, step = 1, value = math.min(volume, 100), flexGrow = 1,
                  controlSize = "sm", enabled = not airplayBusy,
                  onChange = function(v)
        airplayDraft = math.floor(tonumber(v) or volume)
        render()
      end,
                  onDragEnd = function()
        if airplayDraft ~= nil then setAirplayVolume(airplayDraft) end
      end }),
      ui.label({ text = tostring(volume) .. " %", fontSize = 12, color = common.SECONDARY, width = 40, textAlign = "right" }),
    }))
  end
  table.insert(children, common.sectionHeader("airplay-title", "AirPlay"))
  table.insert(children, common.group("airplay-group", rows))
end

local function fmtMinutes(m)
  if m >= 60 then return string.format("%d h %02d min", math.floor(m / 60), m % 60) end
  return m .. " min"
end

-- Gráfica de las últimas horas (el auricular más bajo en cada intervalo), como la de
-- Ajustes → Batería de iOS. Los huecos sin datos repiten el último valor conocido.
local function historySection(children)
  local h = status.history
  if h == nil or h.series == nil or h.buckets == nil then return end
  local left, right = h.series.left or {}, h.series.right or {}
  local values, last, any = {}, nil, false
  for i = 1, h.buckets do
    local l, r = left[i], right[i]
    local v = (l ~= nil and r ~= nil) and math.min(l, r) or (l or r)
    if v ~= nil then any = true; last = v end
    values[i] = last
  end
  if not any then return end
  local first = nil
  for i = 1, h.buckets do if values[i] ~= nil then first = values[i]; break end end
  for i = 1, h.buckets do values[i] = (values[i] or first) / 100 end
  local est = h.remaining_min or {}
  local remaining = nil
  if est.left ~= nil and est.right ~= nil then remaining = math.min(est.left, est.right) else remaining = est.left or est.right end
  table.insert(children, common.sectionHeader("hist-title", "Últimas " .. tostring(h.hours) .. " h",
                                              remaining and ("Quedan ~" .. fmtMinutes(remaining)) or nil))
  table.insert(children, ui.column({ key = "hist-card", radius = 14, fill = common.CARD, padding = 12 }, {
    ui.graph({ key = "hist-graph", values = values, height = 64, lineWidth = 2, fillOpacity = 0.35 }),
  }))
end

local function batteryRow(key, glyph, title, subtitle, battery, dim)
  return common.listRow(key, { glyph = glyph, title = title, subtitle = subtitle,
                               trailing = common.batteryIcon(key .. "-bat", battery, { dim = dim }) })
end

render = function()
  if not panelOpen then return end

  if view == "settings" then
    panel.render(settings.render(status, {
      common = common, refresh = refresh, rerender = function() render() end,
      back = function() view = "main"; settings.reset(); render() end,
    }))
    return
  end

  if status == nil or common.lowestPod(status) == nil then
    local empty = {}
    if status ~= nil then
      table.insert(empty, ui.row({ key = "gear-row", justify = "end" }, {
        roundButton("gear", "settings", function() view = "settings"; render() end),
      }))
    end
    table.insert(empty, ui.glyph({ key = "empty-icon", name = "device-airpods", size = 56, color = "on_surface/0.35" }))
    table.insert(empty, ui.label({ key = "empty-title", text = status == nil and "airpodsd no está en ejecución" or "Sin datos todavía",
                                   fontSize = 17, fontWeight = "semibold" }))
    table.insert(empty, ui.label({ key = "empty-hint", text = status == nil and "systemctl --user start airpodsd" or "Abre la caja cerca del equipo",
                                   fontSize = 13, color = common.SECONDARY }))
    panel.render(ui.column({ padding = 24, gap = 12, align = "center", justify = "center", fill = "surface", radius = 24,
                             flexGrow = 1 }, empty))
    return
  end

  local stale = common.isStale(status.last_seen)
  local lid = common.field(status, "lid_closed")
  local onCharger = common.field(status, "case_on_charger")
  local caseSub = (lid == true and "Cerrada") or (lid == false and "Abierta") or ""
  if onCharger then caseSub = (caseSub ~= "" and (caseSub .. " · ") or "") .. "Cargando" end
  local connText = (status.connected == true and "Conectados") or (status.connected == false and "No conectados")
                   or "No emparejados"

  local header = {
    ui.row({ key = "header", gap = 10, align = "center" }, {
      ui.column({ key = "title", gap = 2, flexGrow = 1 }, {
        ui.label({ text = status.name or status.model_name or "AirPods", fontSize = 22, fontWeight = "bold", maxLines = 1 }),
        ui.label({ text = connText .. " · visto " .. common.ago(status.last_seen), fontSize = 12,
                   color = stale and "error/0.8" or common.SECONDARY }),
      }),
      roundButton("gear", "settings", function() view = "settings"; render() end),
    }),
  }
  local upd = status.update
  if upd ~= nil and upd.available then
    -- Arriba y fuera del scroll: siempre visible y dentro del panel (abajo podía quedar
    -- fuera del borde, y pulsarla contaba como un clic fuera que cerraba el panel).
    table.insert(header, ui.row({ key = "update-banner", gap = 8, align = "center", paddingH = 14, paddingV = 10,
                                  radius = 14, fill = "primary/0.14", onClick = function() view = "settings"; render() end }, {
      ui.glyph({ name = "download", size = 16, color = "primary" }),
      ui.label({ text = "Versión " .. tostring(upd.latest) .. " disponible", fontSize = 13, color = "primary", flexGrow = 1 }),
      ui.glyph({ name = "chevron-right", size = 16, color = "primary" }),
    }))
  end

  local children = {
    common.group("batteries", {
      batteryRow("left", "device-airpods", "Izquierdo", common.where(status, "left"), common.field(status, "left"), stale),
      batteryRow("right", "device-airpods", "Derecho", common.where(status, "right"), common.field(status, "right"), stale),
      batteryRow("case", "device-airpods-case", "Caja", caseSub, common.field(status, "case"), stale),
    }),
  }

  if status.connected == false then
    table.insert(children, common.pillButton("connect", connecting and "Conectando…" or "Conectar a este equipo",
                                             { onClick = connect }))
  elseif status.connected == nil then
    table.insert(children, common.sectionFooter("connect", "Empareja los AirPods con este equipo para conectarlos."))
  end
  ancSection(children)
  conversationSection(children)
  airplaySection(children)
  historySection(children)
  -- El resto va en un scroll del alto del panel: así nada se sale de su borde.
  table.insert(header, ui.scroll({ key = "main-scroll", flexGrow = 1 }, { common.scrollBody("main", 12, children) }))
  panel.render(ui.column({ padding = 18, gap = 14, fill = "surface", radius = 24, flexGrow = 1 }, header))
end

noctalia.state.watch(STATUS_KEY, function(value)
  status = common.decode(value)
  render()
end)

function update()
  refresh()
end

function onOpen(context)
  panelOpen = true
  view = (context == "settings") and "settings" or "main"
  settings.reset()
  status = common.decode(noctalia.state.get(STATUS_KEY))
  panel.setWantsSecondTicks(true) -- refresca cada segundo mientras está abierto
  render()
  refresh()
end

function onClose()
  panelOpen = false
  panel.setWantsSecondTicks(false)
end

-- `noctalia msg plugin canoojson/airpods:panel all select <modo>` equivale a pulsar un segmento.
function onIpc(event, payload)
  if event == "select" then selectMode(payload) end
end
