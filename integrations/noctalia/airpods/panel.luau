--!nonstrict
-- Panel desplegable: batería de cada auricular y de la caja (airpodsd, también con la
-- caja cerrada) y, si airpods-helper está instalado y los AirPods conectados, un
-- selector de modo de escucha al estilo de iOS.

local common = require("./lib/common.luau")
local settings = require("./lib/settings.luau")

local STATUS_KEY = "airpods.status"
local TRACK_WIDTH = 320
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

local function hasFeature(name)
  if anc == nil or anc.features == nil then return false end
  for _, f in ipairs(anc.features) do
    if f == name then return true end
  end
  return false
end

local function availableModes()
  local modes = {}
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
  if HAS_ANC_TOOL and panelOpen then
    noctalia.runAsync({ "airpods-cli", "status", "--json" }, function(result)
      anc = (result.exitCode == 0) and common.decode(result.stdout) or nil
      render()
    end, 5000)
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
  if anc == nil or mode == (pendingMode or anc.anc_mode) then return end
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

local function ancSection(children)
  local modes = availableModes()
  if #modes == 0 or not (anc and anc.connected) then return end
  local current = pendingMode or anc.anc_mode
  -- flexGrow no reparte el ancho de una fila aquí: se calcula a mano.
  local segmentWidth = math.floor((TRACK_WIDTH - 8 - 4 * (#modes - 1)) / #modes)
  local segments = {}
  for _, m in ipairs(modes) do
    local selected = (m == current)
    table.insert(segments, ui.column({
      key = "seg-" .. m, width = segmentWidth, gap = 6, paddingV = 10, paddingH = 4, radius = 12, align = "center",
      -- Relleno transparente explícito: nil conservaría el resaltado anterior.
      fill = selected and "primary/0.18" or "primary/0",
      onClick = function() selectMode(m) end,
    }, {
      ui.glyph({ name = MODE_GLYPHS[m], size = 20, color = selected and "primary" or "on_surface/0.7" }),
      ui.label({ text = MODE_LABELS[m], fontSize = 11, maxLines = 2, maxWidth = segmentWidth - 8,
                 color = selected and "primary" or "on_surface/0.7", fontWeight = selected and "bold" or "normal" }),
    }))
  end
  local earsOut = anc.ear_left == false and anc.ear_right == false
  table.insert(children, ui.row({ key = "anc-title", align = "center" }, {
    ui.label({ text = "Modo de escucha", fontSize = 13, color = "on_surface/0.7", flexGrow = 1 }),
    -- Los AirPods ignoran el cambio de modo si no hay ningún auricular puesto.
    ui.label({ text = earsOut and "Ponte un auricular para cambiarlo" or "", fontSize = 11, color = "on_surface/0.5" }),
  }))
  table.insert(children, ui.row({ key = "anc-segments", gap = 4, padding = 4, radius = 16, fill = "surface_variant/0.6" }, segments))
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
        ui.button({ glyph = "settings", variant = "ghost", tooltip = "Ajustes", onClick = function() view = "settings"; render() end }),
      }))
    end
    table.insert(empty, ui.glyph({ key = "empty-icon", name = "device-airpods", size = 32, color = "on_surface/0.4" }))
    table.insert(empty, ui.label({ key = "empty-title", text = status == nil and "airpodsd no está en ejecución" or "Sin datos todavía",
                                   fontSize = 15, fontWeight = "bold" }))
    table.insert(empty, ui.label({ key = "empty-hint", text = status == nil and "systemctl --user start airpodsd" or "Abre la caja cerca del equipo",
                                   fontSize = 12, color = "on_surface/0.6" }))
    panel.render(ui.column({ padding = 20, gap = 10, align = "center", justify = "center", fill = "surface", radius = 16 }, empty))
    return
  end

  local stale = common.isStale(status.last_seen)
  local lid = common.field(status, "lid_closed")
  local onCharger = common.field(status, "case_on_charger")
  local caseSub = (lid == true and "Cerrada") or (lid == false and "Abierta") or ""
  if onCharger then caseSub = (caseSub ~= "" and (caseSub .. " · ") or "") .. "Cargando" end

  local children = {
    ui.row({ key = "header", gap = 10, align = "center" }, {
      ui.glyph({ name = "device-airpods", size = 22, color = "primary" }),
      ui.column({ key = "title", gap = 2, flexGrow = 1 }, {
        ui.label({ text = status.name or status.model_name or "AirPods", fontSize = 16, fontWeight = "bold" }),
        ui.label({ text = "Visto " .. common.ago(status.last_seen), fontSize = 11,
                   color = stale and "error/0.8" or "on_surface/0.55" }),
      }),
      ui.button({ key = "gear", glyph = "settings", variant = "ghost", tooltip = "Ajustes",
                  onClick = function() view = "settings"; render() end }),
    }),
    ui.row({ key = "batteries", gap = 10 }, {
      common.card("left", "device-airpods", "Izquierdo", common.field(status, "left"), common.where(status, "left"), { iconSize = 24, dim = stale }),
      common.card("right", "device-airpods", "Derecho", common.field(status, "right"), common.where(status, "right"), { iconSize = 24, dim = stale }),
      common.card("case", "device-airpods-case", "Caja", common.field(status, "case"), caseSub, { iconSize = 24, dim = stale }),
    }),
  }

  if status.connected == false then
    table.insert(children, ui.button({ key = "connect", text = connecting and "Conectando…" or "Conectar a este equipo",
                                       variant = "primary", onClick = connect }))
  elseif status.connected == nil then
    table.insert(children, ui.label({ key = "connect", text = "Empareja los AirPods con este equipo para conectarlos",
                                      fontSize = 12, color = "on_surface/0.6" }))
  end
  ancSection(children)
  local upd = status.update
  if upd ~= nil and upd.available then
    table.insert(children, ui.button({ key = "update-banner", glyph = "download", variant = "outline",
                                       text = "Versión " .. tostring(upd.latest) .. " disponible",
                                       onClick = function() view = "settings"; render() end }))
  end

  panel.render(ui.column({ padding = 16, gap = 14, fill = "surface", radius = 16 }, children))
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
