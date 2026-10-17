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

-- Una pieza (auricular o caja): ilustración, insignia I/D y batería debajo, como en iOS.
-- Batería de una pieza: icono de iOS encima del porcentaje.
local function batteryStack(key, battery, badge)
  local level = battery and battery.level
  local children = {}
  if badge then
    table.insert(children, ui.row({ key = key .. "-badge", width = 18, height = 18, radius = 9, align = "center",
                                    justify = "center", fill = "on_surface/0.12" }, {
      ui.label({ text = badge, fontSize = 10, fontWeight = "semibold", color = common.SECONDARY }),
    }))
  end
  table.insert(children, common.batteryIcon(key .. "-bat", battery, { showText = false, width = 30, height = 14 }))
  table.insert(children, ui.label({ key = key .. "-pct", text = level and (level .. " %") or "—", fontSize = 15,
                                    color = level and "on_surface" or common.SECONDARY }))
  return ui.column({ key = key, gap = 8, align = "center", width = 64 }, children)
end

-- Auriculares: un solo icono (el tema no tiene uno por lado) con las dos baterías debajo.
local function pods(left, right)
  return ui.column({ key = "pods", gap = 12, align = "center" }, {
    ui.glyph({ key = "pods-img", name = "device-airpods", size = 76, color = "on_surface" }),
    ui.row({ key = "pods-bats", gap = 8, align = "end" }, {
      batteryStack("left", left, "I"),
      batteryStack("right", right, "D"),
    }),
  })
end

local function casePart(battery)
  return ui.column({ key = "case", gap = 12, align = "center" }, {
    ui.glyph({ key = "case-img", name = "device-airpods-case", size = 76, color = "on_surface" }),
    batteryStack("case-b", battery),
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
    footer = common.pillButton("footer", "Listo", { fill = "on_surface/0.12", color = "on_surface",
                                                    onClick = function() panel.close() end })
  elseif state.connected == false then
    footer = common.pillButton("footer", connecting and "Conectando…" or "Conectar",
                               { fill = "primary", color = "on_primary", onClick = connect })
  else
    -- connected == nil: los AirPods no están emparejados con este equipo.
    footer = ui.label({ key = "footer", text = "Empareja los AirPods con este equipo para conectarlos",
                        fontSize = 13, color = common.SECONDARY, textAlign = "center" })
  end

  panel.render(ui.column({ padding = 22, gap = 18, fill = "surface", radius = 36, align = "stretch" }, {
    ui.row({ key = "header", gap = 8, align = "center" }, {
      common.gap("header-spacer", 30, 30),
      ui.label({ key = "title", text = state.name or state.model_name or "AirPods", fontSize = 18,
                 fontWeight = "bold", flexGrow = 1, textAlign = "center", maxLines = 1 }),
      ui.row({ key = "close", width = 30, height = 30, radius = 15, align = "center", justify = "center",
               fill = "on_surface/0.12", onClick = function() panel.close() end }, {
        ui.glyph({ name = "x", size = 16, color = "on_surface/0.7" }),
      }),
    }),
    ui.row({ key = "parts", gap = 24, align = "end", justify = "center" }, {
      pods((common.field(state, "left")), (common.field(state, "right"))),
      casePart((common.field(state, "case"))),
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
