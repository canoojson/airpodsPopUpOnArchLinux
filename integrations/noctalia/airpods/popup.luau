--!nonstrict
-- AirPods popup, estilo iOS: lo abre airpodsd al abrir la caja con los auriculares dentro
--   noctalia msg panel-open canoojson/airpods:popup '<json>'
-- y lo actualiza mientras está abierto con
--   noctalia msg plugin canoojson/airpods:popup all state '<json>'
-- Se cierra solo tras AUTO_CLOSE_S segundos, al cerrar la tapa o con Escape.

local common = require("./lib/common.luau")

local AUTO_CLOSE_S = 10

local state = nil
local openedAt = 0
local connecting = false

local function connect()
  if connecting or state == nil or state.address == nil then return end
  connecting = true
  render()
  noctalia.runAsync({ "bluetoothctl", "connect", state.address }, function(result)
    connecting = false
    if result.exitCode == 0 then
      state.connected = true
    else
      noctalia.notifyError("AirPods", "No se pudo conectar")
    end
    render()
  end, 15000)
end

function render()
  if state == nil then
    panel.render(ui.column({ padding = 20, align = "center", justify = "center" }, {
      ui.label({ text = "AirPods", fontSize = 15 }),
    }))
    return
  end

  local footer
  if state.connected == true then
    footer = ui.row({ key = "footer", gap = 6, align = "center", justify = "center" }, {
      ui.glyph({ name = "bluetooth-connected", size = 14, color = "primary" }),
      ui.label({ text = "Conectados a este equipo", fontSize = 12, color = "on_surface/0.7" }),
    })
  elseif state.connected == false then
    footer = ui.button({ key = "footer", text = connecting and "Conectando…" or "Conectar",
                         variant = "primary", onClick = connect })
  else
    -- connected == nil: los AirPods no están emparejados con este equipo.
    footer = ui.label({ key = "footer", text = "Empareja los AirPods con este equipo para conectarlos",
                        fontSize = 12, color = "on_surface/0.6" })
  end

  panel.render(ui.column({ padding = 16, gap = 14, fill = "surface", radius = 22 }, {
    ui.row({ key = "header", gap = 10, align = "center" }, {
      ui.glyph({ name = "device-airpods", size = 20, color = "primary" }),
      ui.label({ text = state.model_name or "AirPods", fontSize = 16, fontWeight = "bold", flexGrow = 1 }),
      ui.button({ glyph = "x", variant = "ghost", onClick = function() panel.close() end }),
    }),
    ui.row({ key = "cards", gap = 10 }, {
      common.card("left", "device-airpods", "Izquierdo", common.field(state, "left")),
      common.card("right", "device-airpods", "Derecho", common.field(state, "right")),
      common.card("case", "device-airpods-case", "Caja", common.field(state, "case")),
    }),
    footer,
  }))
end

function onOpen(context)
  state = common.decode(context) or state
  openedAt = os.time()
  panel.setWantsSecondTicks(true)
  render()
end

function onIpc(event, payload)
  if event == "state" then
    state = common.decode(payload) or state
    render()
  end
end

-- Con setWantsSecondTicks, update() corre cada segundo mientras el panel está abierto.
function update()
  if openedAt > 0 and not connecting and os.time() - openedAt >= AUTO_CLOSE_S then
    openedAt = 0
    panel.close()
  end
end

function onClose()
  openedAt = 0
  panel.setWantsSecondTicks(false)
end
