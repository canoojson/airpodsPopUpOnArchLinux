--!nonstrict
-- Widget de barra: batería más baja de los auriculares (en la oreja si hay alguno)
-- a partir del estado de airpodsd. Funciona también con la caja cerrada.

local common = require("./lib/common.luau")

local PANEL_ID = "canoojson/airpods:panel"
local STATUS_KEY = "airpods.status"
local POLL_MS = 3000

local function render(status)
  barWidget.setGlyph("device-airpods")
  local level = status and common.lowestPod(status)
  if level == nil then
    barWidget.setGlyphColor("on_surface/0.4")
    barWidget.setText("")
    barWidget.setTooltip(status == nil and "airpodsd no está en ejecución" or "Sin datos de los AirPods todavía")
    return
  end

  local stale = common.isStale(status.last_seen)
  local low = level <= common.LOW_BATTERY
  barWidget.setGlyphColor(low and "error" or (stale and "on_surface/0.5" or "primary"))
  barWidget.setColor(low and "error" or (stale and "on_surface/0.6" or "on_surface"))
  barWidget.setText(level .. "%")

  local rows = {}
  for _, item in ipairs({ { "left", "Izquierdo" }, { "right", "Derecho" }, { "case", "Caja" } }) do
    local b = common.field(status, item[1])
    table.insert(rows, { item[2], b and (b.level .. "%" .. (b.charging and " ⚡" or "")) or "—" })
  end
  table.insert(rows, { "Visto", common.ago(status.last_seen) })
  barWidget.setTooltip(rows)
end

local function refresh()
  common.read(function(status)
    noctalia.state.set(STATUS_KEY, status and noctalia.json.encode(status) or "")
  end)
end

noctalia.state.watch(STATUS_KEY, function(value)
  render(common.decode(value))
end)

function update()
  noctalia.setUpdateInterval(POLL_MS)
  refresh()
end

function onClick()
  noctalia.togglePanel(PANEL_ID)
end

function onIpc(event, _payload)
  if event == "refresh" then refresh() end
end

render(common.decode(noctalia.state.get(STATUS_KEY)))
