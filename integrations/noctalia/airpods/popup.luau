--!nonstrict
-- Popup de los AirPods con el aspecto de la tarjeta de iOS: lo abre airpodsd al abrir la caja con los auriculares dentro
--   noctalia msg panel-open canoojson/airpods:popup '<json>'
-- y lo actualiza mientras está abierto con
--   noctalia msg plugin canoojson/airpods:popup all state '<json>'
-- Se cierra solo tras AUTO_CLOSE_S segundos, al cerrar la tapa o con Escape.

local common = require("./lib/common.luau")
-- Textos traducibles: el castellano es la clave; las traducciones están en translations/<idioma>.json.
local T = noctalia.tr

local AUTO_CLOSE_S = 10

-- Auriculares y caja girando, como en iOS: fotogramas de un render del modelo 3D (ver
-- CREDITS.md), una vuelta cada SPIN_FRAMES / SPIN_FPS segundos. Están dibujados al doble.
local SPIN_FRAMES = 480
local SPIN_FPS = 60
local SPIN_W, SPIN_H = 150, 130

local state = nil
local openedAt = 0
local connecting = false
local spinStartMs = 0
local spinFrame = 0

local function connect()
  if connecting or state == nil or state.address == nil then return end
  connecting = true
  render()
  noctalia.runAsync({ "bluetoothctl", "connect", state.address }, function(result)
    connecting = false
    if result.exitCode == 0 then
      state.connected = true
    else
      noctalia.notifyError("AirPods", T("No se pudo conectar"))
    end
    render()
  end, 15000)
end

-- Batería de una pieza, como en iOS: insignia (I, D o el icono de la caja), icono de batería
-- y porcentaje debajo.
local function batteryStack(key, battery, badge)
  local level = battery and battery.level
  return ui.column({ key = key, gap = 8, align = "center", width = 64 }, {
    ui.row({ key = key .. "-badge", width = 22, height = 22, radius = 11, align = "center",
             justify = "center", fill = "on_surface/0.12" }, { badge }),
    common.batteryIcon(key .. "-bat", battery, { showText = false, width = 30, height = 14 }),
    ui.label({ key = key .. "-pct", text = level and (level .. " %") or "—", fontSize = 15,
               color = level and "on_surface" or common.SECONDARY }),
  })
end

local function letter(text)
  return ui.label({ text = text, fontSize = 11, fontWeight = "semibold", color = common.SECONDARY })
end

-- what: "buds" o "case" (carpeta de fotogramas en assets/); glyph: icono del tema si no hay.
local function spinning(what, glyph)
  local dir = noctalia.pluginDir()
  if dir == nil then
    return ui.glyph({ key = what .. "-img", name = glyph, size = 76, color = "on_surface" })
  end
  return ui.image({ key = what .. "-img", path = string.format("%s/assets/%s/%03d.webp", dir, what, spinFrame),
                    width = SPIN_W, height = SPIN_H })
end

-- Auriculares: un solo dibujo para los dos, con las dos baterías debajo.
local function pods(left, right)
  return ui.column({ key = "pods", gap = 12, align = "center" }, {
    spinning("buds", "device-airpods"),
    ui.row({ key = "pods-bats", gap = 8, align = "end" }, {
      batteryStack("left", left, letter(T("I"))),
      batteryStack("right", right, letter(T("D"))),
    }),
  })
end

local function casePart(battery)
  return ui.column({ key = "case", gap = 12, align = "center" }, {
    spinning("case", "device-airpods-case"),
    batteryStack("case-b", battery, ui.glyph({ name = "device-airpods-case", size = 13, color = common.SECONDARY })),
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
    footer = common.pillButton("footer", T("Listo"), { fill = "on_surface/0.12", color = "on_surface",
                                                    onClick = function() panel.close() end })
  elseif state.connected == false then
    footer = common.pillButton("footer", connecting and T("Conectando…") or T("Conectar"),
                               { fill = "primary", color = "on_primary", onClick = connect })
  else
    -- connected == nil: los AirPods no están emparejados con este equipo.
    footer = ui.label({ key = "footer", text = T("Empareja los AirPods con este equipo para conectarlos"),
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
    ui.row({ key = "parts", gap = 16, align = "end", justify = "center" }, {
      pods((common.field(state, "left")), (common.field(state, "right"))),
      casePart((common.field(state, "case"))),
    }),
    footer,
  }))
end

function onOpen(context)
  state = common.decode(context) or state
  openedAt = os.time()
  spinStartMs, spinFrame = noctalia.nowMs(), 0
  panel.setWantsSecondTicks(true)
  pcall(panel.setNeedsFrameTick, true)   -- versiones sin la función: la caja queda quieta
  render()
end

function onIpc(event, payload)
  if event == "state" then
    state = common.decode(payload) or state
    render()
  end
end

-- Se llama en cada fotograma de la pantalla: solo se redibuja al cambiar de imagen.
function onFrameTick()
  local frame = math.floor((noctalia.nowMs() - spinStartMs) * SPIN_FPS / 1000) % SPIN_FRAMES
  if frame ~= spinFrame then
    spinFrame = frame
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
  pcall(panel.setNeedsFrameTick, false)
end
