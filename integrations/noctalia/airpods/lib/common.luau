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

-- Tarjeta de batería (auricular o caja) usada por el panel y el popup.
function M.card(key, glyph, label, battery, subtitle, opts)
  opts = opts or {}
  local level = battery and battery.level
  local charging = battery and battery.charging
  local low = level ~= nil and level <= M.LOW_BATTERY
  local children = {
    ui.glyph({ key = key .. "-icon", name = glyph, size = opts.iconSize or 30,
               color = opts.dim and "on_surface/0.5" or "on_surface" }),
    ui.row({ key = key .. "-level", gap = 4, align = "center" }, {
      ui.label({ key = key .. "-pct", text = level and (level .. "%") or "—", fontSize = 16, fontWeight = "bold",
                 color = opts.dim and "on_surface/0.6" or "on_surface" }),
      -- Siempre presente (transparente si no carga) para que el texto no se desplace.
      ui.glyph({ key = key .. "-bolt", name = "bolt", size = 14, color = charging and "primary" or "primary/0" }),
    }),
    ui.progress({ key = key .. "-bar", progress = level and (level / 100) or 0, fill = low and "error" or "primary",
                  track = "on_surface/0.12", radius = 3, height = 5, width = 70 }),
    ui.label({ key = key .. "-label", text = label, fontSize = 11, color = "on_surface/0.6" }),
  }
  if subtitle ~= nil and subtitle ~= "" then
    table.insert(children, ui.label({ key = key .. "-sub", text = subtitle, fontSize = 10, color = "on_surface/0.45" }))
  end
  return ui.column({ key = key, flexGrow = 1, gap = 7, padding = 12, radius = 14,
                     fill = "surface_variant/0.6", align = "center" }, children)
end

return M
