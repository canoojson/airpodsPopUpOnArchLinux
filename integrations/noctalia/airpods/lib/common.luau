--!nonstrict
-- Utilidades compartidas por el widget, el panel y el popup.
-- El estado lo escribe airpodsd en $XDG_RUNTIME_DIR/airpods-linux/status.json.

local M = {}

M.LOW_BATTERY = 20
M.STALE_S = 600 -- a partir de aquí el dato se muestra como "antiguo"

function M.statusPath()
  local runtime = noctalia.getenv("XDG_RUNTIME_DIR")
  if runtime == nil or runtime == "" then return nil end
  return runtime .. "/airpods-linux/status.json"
end

function M.decode(raw)
  if raw == nil or raw == "" then return nil end
  local ok, value = pcall(noctalia.json.decode, raw)
  return ok and value or nil
end

-- Lee el estado del daemon y llama a cb(status | nil).
function M.read(cb)
  local path = M.statusPath()
  if path == nil then cb(nil) return end
  noctalia.readFileAsync(path, function(contents, _err)
    cb(M.decode(contents))
  end)
end

function M.field(status, name)
  local f = status and status.fields and status.fields[name]
  return f and f.value, f and f.ts
end

function M.nowS()
  return noctalia.nowMs() / 1000
end

function M.ago(ts)
  if ts == nil then return "nunca" end
  local s = math.max(0, math.floor(M.nowS() - ts))
  if s < 60 then return "ahora" end
  if s < 3600 then return "hace " .. math.floor(s / 60) .. " min" end
  if s < 86400 then return "hace " .. math.floor(s / 3600) .. " h" end
  return "hace " .. math.floor(s / 86400) .. " d"
end

function M.isStale(ts)
  return ts == nil or (M.nowS() - ts) > M.STALE_S
end

-- Batería más baja de los auriculares en la oreja; si ninguno lo está, de ambos.
function M.lowestPod(status)
  local lowest = nil
  local function consider(side, onlyInEar)
    local b = M.field(status, side)
    local inEar = M.field(status, side .. "_in_ear")
    if b ~= nil and (not onlyInEar or inEar) then
      lowest = (lowest == nil) and b.level or math.min(lowest, b.level)
    end
  end
  consider("left", true)
  consider("right", true)
  if lowest == nil then
    consider("left", false)
    consider("right", false)
  end
  return lowest
end

function M.where(status, side)
  if M.field(status, side .. "_in_ear") then return "En la oreja" end
  local inCase = M.field(status, side .. "_in_case")
  if inCase == true then return "En la caja" end
  if inCase == false then return "Fuera" end
  return ""
end

-- Hueco fijo y transparente. Ni ui.box (lleva relleno por defecto) ni ui.spacer (es
-- elástico y se come el espacio libre) sirven para esto: una fila vacía sí.
function M.gap(key, width, height)
  return ui.row({ key = key, width = width or 1, height = height or 1 }, {})
end

-- Contenido de un scroll con un hueco a la derecha, para que no quede pegado a la
-- barra de desplazamiento ni al borde del panel (solo existe paddingH, a ambos lados).
M.SCROLL_GUTTER = 12

function M.scrollBody(key, gap, children)
  return ui.row({ key = key .. "-wrap", gap = 0 }, {
    ui.column({ key = key .. "-body", gap = gap, flexGrow = 1 }, children),
    M.gap(key .. "-gutter", M.SCROLL_GUTTER),
  })
end

-- ---------------------------------------------------------------------------
-- Componentes con estética iOS. La estructura copia iOS (listas agrupadas, icono de
-- batería horizontal, botones redondos, píldoras) y los colores siguen el tema de
-- Noctalia, salvo los de estado de la batería, que son los de iOS.

M.IOS_GREEN = "#34C759"   -- cargando
M.IOS_RED = "#FF3B30"     -- batería baja
M.CARD = "on_surface/0.07"      -- tarjeta agrupada: se distingue del fondo con cualquier tema
M.SEPARATOR = "on_surface/0.1"
M.SECONDARY = "on_surface/0.55"

-- Icono de batería horizontal (contorno, relleno proporcional y punta) + porcentaje.
function M.batteryIcon(key, battery, opts)
  opts = opts or {}
  local w, h = opts.width or 27, opts.height or 13
  local level = battery and battery.level
  local charging = battery and battery.charging
  local color = (charging and M.IOS_GREEN) or (level ~= nil and level <= M.LOW_BATTERY and M.IOS_RED)
                or (opts.dim and "on_surface/0.45") or "on_surface"
  local inner = w - 4
  local fillW = level and math.max(2, math.floor(inner * level / 100 + 0.5)) or 0
  local body = ui.row({ key = key .. "-body", width = w, height = h, radius = 3.5, padding = 1.5, gap = 0,
                        border = opts.dim and "on_surface/0.3" or "on_surface/0.45", borderWidth = 1 }, {
    ui.box({ key = key .. "-fill", width = fillW, height = h - 5, radius = 2, fill = level and color or "on_surface/0" }),
  })
  local children = {
    ui.row({ key = key .. "-shape", gap = 1, align = "center" }, {
      body,
      ui.box({ key = key .. "-tip", width = 1.5, height = 4, radius = 1, fill = opts.dim and "on_surface/0.3" or "on_surface/0.45" }),
    }),
  }
  if opts.showText ~= false then
    table.insert(children, 1, ui.label({ key = key .. "-pct", text = level and (level .. " %") or "—",
                                         fontSize = opts.fontSize or 13, color = opts.dim and M.SECONDARY or "on_surface" }))
  end
  if charging then
    table.insert(children, ui.glyph({ key = key .. "-bolt", name = "bolt", size = 12, color = M.IOS_GREEN }))
  end
  return ui.row({ key = key, gap = 6, align = "center" }, children)
end

-- Cabecera de sección de una lista agrupada ("AUDIO", "BATERÍA"...).
function M.sectionHeader(key, text, trailing)
  local children = { ui.label({ key = key .. "-t", text = string.upper(text), fontSize = 11, color = M.SECONDARY,
                                flexGrow = 1 }) }
  if trailing then table.insert(children, ui.label({ key = key .. "-r", text = trailing, fontSize = 11, color = M.SECONDARY })) end
  return ui.row({ key = key, paddingH = 14, align = "center" }, children)
end

-- Pie de sección: texto explicativo pequeño bajo una lista agrupada.
function M.sectionFooter(key, text, color)
  -- Las etiquetas no admiten padding: la sangría la pone la fila.
  return ui.row({ key = key, paddingH = 14 }, {
    ui.label({ key = key .. "-t", text = text, fontSize = 11, color = color or M.SECONDARY, maxLines = 3, flexGrow = 1 }),
  })
end

-- Lista agrupada de iOS: filas en una tarjeta redondeada separadas por líneas finas.
function M.group(key, rows)
  local children = {}
  for i, row in ipairs(rows) do
    if i > 1 then
      table.insert(children, ui.row({ key = key .. "-sep" .. i, paddingH = 14 }, {
        ui.box({ key = key .. "-line" .. i, height = 1, flexGrow = 1, fill = M.SEPARATOR }),
      }))
    end
    table.insert(children, row)
  end
  return ui.column({ key = key, gap = 0, radius = 14, fill = M.CARD }, children)
end

-- Fila de lista: icono opcional en un círculo, título y subtítulo, y un control a la derecha.
function M.listRow(key, opts)
  local children = {}
  if opts.glyph or opts.icon then
    table.insert(children, ui.row({ key = key .. "-ic", width = 30, height = 30, radius = 15, align = "center",
                                    justify = "center", fill = opts.glyphFill or "primary/0.15" }, {
      opts.icon or ui.glyph({ name = opts.glyph, size = 17, color = opts.glyphColor or "primary" }),
    }))
  end
  local texts = { ui.label({ key = key .. "-title", text = opts.title, fontSize = 14,
                             color = opts.titleColor or "on_surface" }) }
  if opts.subtitle and opts.subtitle ~= "" then
    table.insert(texts, ui.label({ key = key .. "-sub", text = opts.subtitle, fontSize = 11, color = M.SECONDARY,
                                   maxLines = 2 }))
  end
  table.insert(children, ui.column({ key = key .. "-txt", gap = 2, flexGrow = 1 }, texts))
  if opts.trailing then table.insert(children, opts.trailing) end
  return ui.row({ key = key, gap = 12, align = "center", paddingH = 14, paddingV = 11, onClick = opts.onClick },
                children)
end

-- Auricular dibujado con elementos de Noctalia (sigue el color del tema): cabeza redonda
-- y tallo hacia abajo, en el lado interior. side = "left" | "right".
function M.earbud(key, side, size, color)
  local head = size
  local stemW, stemH = math.floor(size * 0.34 + 0.5), math.floor(size * 1.15 + 0.5)
  local inset = math.floor(size * 0.12 + 0.5)    -- el tallo no sale del borde de la cabeza
  color = color or "on_surface"
  local stemRow = { ui.box({ key = key .. "-stem", width = stemW, height = stemH, radius = stemW / 2, fill = color }) }
  local spacer = M.gap(key .. "-sp", head - stemW - inset)
  local edge = M.gap(key .. "-edge", inset)
  if side == "left" then
    stemRow = { spacer, stemRow[1], edge }   -- el tallo del izquierdo va a su derecha (hacia dentro)
  else
    stemRow = { edge, stemRow[1], spacer }
  end
  return ui.column({ key = key, gap = -math.floor(size * 0.18), align = "center", width = head }, {
    ui.box({ key = key .. "-head", width = head, height = head, radius = head / 2, fill = color }),
    ui.row({ key = key .. "-stemrow", gap = 0, width = head }, stemRow),
  })
end

-- Caja de carga con el mismo estilo: silueta redondeada, línea de la tapa y LED.
function M.caseShape(key, w, h, color)
  local lid = math.floor(h * 0.3 + 0.5)
  return ui.column({ key = key, width = w, height = h, radius = math.floor(h * 0.32), fill = color or "on_surface",
                     align = "center", gap = 0 }, {
    M.gap(key .. "-lidspace", 1, lid),
    ui.box({ key = key .. "-seam", width = w, height = 2, fill = "surface/0.35" }),
    M.gap(key .. "-ledspace", 1, math.floor((h - lid - 2) * 0.42)),
    ui.box({ key = key .. "-led", width = 6, height = 6, radius = 3, fill = "surface/0.3" }),
  })
end

-- Botón ancho en forma de píldora (acción principal, como "Conectar" en iOS).
function M.pillButton(key, text, opts)
  opts = opts or {}
  local children = {}
  if opts.glyph then
    table.insert(children, ui.glyph({ name = opts.glyph, size = 16, color = opts.color or "on_primary" }))
  end
  table.insert(children, ui.label({ text = text, fontSize = 15, fontWeight = "semibold",
                                    color = opts.color or "on_primary" }))
  return ui.row({ key = key, gap = 8, align = "center", justify = "center", paddingV = 13, radius = 24,
                  fill = opts.fill or "primary", onClick = opts.onClick }, children)
end

return M
