--!nonstrict
-- Popup de los AirPods con el aspecto de la tarjeta de iOS: lo abre airpodsd al abrir la caja con los auriculares dentro
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

-- El popup no toma el teclado (keyboard_focus = "none"), así que los ajustes, que
-- tienen un campo de texto, se abren en el panel normal.
local function openSettings()
  panel.close()
  noctalia.runAsync({ "noctalia", "msg", "panel-open", "canoojson/airpods:panel", "settings" }, function() end, 5000)
end

-- Batería de los auriculares bajo su icono: una sola si los dos van igual (como iOS),
-- y si no, izquierdo y derecho por separado.
local function podsBattery(left, right)
  if left ~= nil and right ~= nil and left.level == right.level and left.charging == right.charging then
    return common.batteryIcon("pods-bat", left, { fontSize = 15 })
  end
  local function side(key, letter, b)
    return ui.row({ key = key, gap = 6, align = "center" }, {
      ui.label({ text = letter, fontSize = 12, color = common.SECONDARY }),
      common.batteryIcon(key .. "-bat", b, { fontSize = 15 }),
    })
  end
  return ui.column({ key = "pods-bat", gap = 4, align = "center" }, {
    side("bat-l", "I", left),
    side("bat-r", "D", right),
  })
end

local function device(key, glyph, battery)
  return ui.column({ key = key, gap = 12, align = "center", flexGrow = 1 }, {
    ui.glyph({ key = key .. "-img", name = glyph, size = 76, color = "on_surface" }),
    battery,
  })
end

-- Botón redondo pequeño (cerrar, ajustes), como los de las tarjetas de iOS.
local function roundButton(key, glyph, onClick)
  return ui.row({ key = key, width = 30, height = 30, radius = 15, align = "center", justify = "center",
                  fill = "on_surface/0.1", onClick = onClick }, {
    ui.glyph({ name = glyph, size = 15, color = "on_surface/0.7" }),
  })
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
    footer = common.pillButton("footer", "Conectados", { glyph = "check", fill = "on_surface/0.08", color = "on_surface" })
  elseif state.connected == false then
    footer = common.pillButton("footer", connecting and "Conectando…" or "Conectar", { onClick = connect })
  else
    -- connected == nil: los AirPods no están emparejados con este equipo.
    footer = ui.label({ key = "footer", text = "Empareja los AirPods con este equipo para conectarlos",
                        fontSize = 12, color = common.SECONDARY, textAlign = "center" })
  end

  panel.render(ui.column({ padding = 22, gap = 20, fill = "surface", radius = 32, align = "stretch" }, {
    ui.row({ key = "header", gap = 8, align = "center" }, {
      roundButton("settings", "settings", openSettings),
      ui.label({ key = "title", text = state.name or state.model_name or "AirPods", fontSize = 17,
                 fontWeight = "semibold", flexGrow = 1, textAlign = "center", maxLines = 2 }),
      roundButton("close", "x", function() panel.close() end),
    }),
    ui.row({ key = "devices", gap = 10, align = "end" }, {
      device("pods", "device-airpods", podsBattery(common.field(state, "left"), common.field(state, "right"))),
      device("case", "device-airpods-case", common.batteryIcon("case-bat", common.field(state, "case"), { fontSize = 15 })),
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
