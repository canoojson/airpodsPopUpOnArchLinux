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

local IOS_BLUE = "#0A84FF"

-- Una pieza (auricular o caja): ilustración, insignia I/D y batería debajo, como en iOS.
local function part(key, image, w, h, battery, badge)
  local level = battery and battery.level
  local children = {
    image == "pod-left" and common.earbud(key .. "-img", "left", 38)
    or image == "pod-right" and common.earbud(key .. "-img", "right", 38)
    or common.caseShape(key .. "-img", w, h),
  }
  -- Solo los auriculares llevan insignia. Las columnas se alinean por abajo, así que las
  -- baterías quedan a la misma altura sin necesidad de rellenar el hueco de la caja.
  if badge then
    table.insert(children, ui.row({ key = key .. "-badge", width = 18, height = 18, radius = 9, align = "center",
                                    justify = "center", fill = "on_surface/0.12" }, {
      ui.label({ text = badge, fontSize = 10, fontWeight = "semibold", color = common.SECONDARY }),
    }))
  end
  table.insert(children, common.batteryIcon(key .. "-bat", battery, { showText = false, width = 30, height = 14 }))
  table.insert(children, ui.label({ key = key .. "-pct", text = level and (level .. " %") or "—", fontSize = 15,
                                    color = level and "on_surface" or common.SECONDARY }))
  return ui.column({ key = key, gap = 8, align = "center", justify = "end", width = math.max(w, 64) }, children)
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
                               { fill = IOS_BLUE, color = "#FFFFFF", onClick = connect })
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
    ui.row({ key = "parts", gap = 4, align = "end", justify = "center" }, {
      part("left", "pod-left", 54, 80, common.field(state, "left"), "I"),
      part("right", "pod-right", 54, 80, common.field(state, "right"), "D"),
      common.gap("parts-gap", 14),
      -- Paréntesis: common.field devuelve también la hora, que si no ocuparía `badge`.
      part("case", "case", 84, 62, (common.field(state, "case"))),
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
