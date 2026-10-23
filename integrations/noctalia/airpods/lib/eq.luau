--!nonstrict
-- Vista del ecualizador: interruptor, preajustes y una barra por banda. Los cambios van
-- por `airpodsctl eq`, que guarda la configuración y avisa a airpodsd; airpodsd cambia
-- las ganancias del filtro de PipeWire en vivo.

local M = {}
-- Textos traducibles: el castellano es la clave; las traducciones están en translations/<idioma>.json.
local T = noctalia.tr

local busy = false
-- Barras: el valor que ha puesto el usuario se conserva (drafts) hasta que el estado de
-- airpodsd lo confirma, para que la barra no vuelva atrás mientras se guarda. Los cambios
-- se encolan (pending) y se mandan de uno en uno: soltar otra barra mientras se guarda
-- la anterior no se pierde.
local drafts = {}    -- banda -> dB
local pending = {}   -- banda -> dB por mandar
local sending = nil  -- banda que se está mandando
local ctx = nil      -- { status, refresh, rerender } del último render

local function ctl(status)
  return (status and status.ctl) or "airpodsctl"
end

function M.reset()
  busy = false
  drafts = {}
  pending = {}
end

local function run(status, args, refresh, rerender)
  if busy then return end
  busy = true
  rerender()
  local argv = { ctl(status), "eq" }
  for _, a in ipairs(args) do table.insert(argv, a) end
  -- Un preajuste o restablecer sustituye a lo que hubiera a medias en las barras.
  drafts, pending = {}, {}
  noctalia.runAsync(argv, function(result)
    busy = false
    if result.exitCode ~= 0 then
      noctalia.notifyError("AirPods", (result.stderr ~= "" and result.stderr) or T("No se pudo cambiar el ecualizador"))
    end
    refresh()
    rerender()
  end, 8000)
end

local function flush()
  if sending ~= nil or ctx == nil then return end
  local band, value = next(pending)
  if band == nil then return end
  pending[band] = nil
  sending = band
  noctalia.runAsync({ ctl(ctx.status), "eq", "set", tostring(band), tostring(value) }, function(result)
    sending = nil
    if result.exitCode ~= 0 then
      drafts[band] = nil
      noctalia.notifyError("AirPods", (result.stderr ~= "" and result.stderr) or T("No se pudo cambiar el ecualizador"))
    end
    ctx.refresh()
    flush()
  end, 8000)
end

-- Callbacks de las barras. Noctalia identifica cada callback por su nombre, y el de una
-- función anónima cambia en cada render: los eventos de arrastre que llegan con el nombre
-- anterior se descartan y al soltar se mandaba un valor viejo. Por eso panel.luau
-- registra funciones globales con nombre fijo (eqBand0..9, eqBandEnd0..9) que llaman aquí.
function M.bandChanged(band, v)
  drafts[band] = tonumber(v) or drafts[band]
  if ctx then ctx.rerender() end
end

function M.bandReleased(band)
  if drafts[band] == nil then return end
  pending[band] = drafts[band]
  flush()
end

local function bandLabel(freq)
  if freq >= 1000 then return tostring(math.floor(freq / 1000)) .. " kHz" end
  return tostring(freq) .. " Hz"
end

local function fmtDb(v)
  local s = string.format("%+.1f", v)
  return (s:gsub("%.0$", "")) .. " dB"
end

-- Nombre visible del preajuste actual.
function M.presetLabel(e)
  if e == nil then return nil end
  if e.preset == "custom" then return T("Personalizado") end
  for _, p in ipairs(e.presets or {}) do
    if p[1] == e.preset then return T(p[2]) end
  end
  return e.preset
end

function M.render(status, opts)
  local common, refresh, rerender = opts.common, opts.refresh, opts.rerender
  local e = (status and status.eq) or {}
  local enabled = e.enabled == true
  ctx = { status = status, refresh = refresh, rerender = rerender }

  local header = ui.column({ key = "eq-header", gap = 6 }, {
    ui.row({ key = "eq-back", gap = 2, align = "center", onClick = opts.back }, {
      ui.glyph({ name = "chevron-left", size = 18, color = "primary" }),
      ui.label({ text = "AirPods", fontSize = 14, color = "primary" }),
    }),
    ui.label({ text = T("Ecualizador"), fontSize = 22, fontWeight = "bold" }),
  })

  local children = {
    common.group("eq-on-g", {
      common.listRow("eq-on", {
        title = T("Ecualizador"), subtitle = (enabled and e.active ~= true) and T("Se aplica al conectar los AirPods") or nil,
        trailing = ui.toggle({ key = "eq-on-toggle", checked = enabled, enabled = not busy and e.available ~= false,
                               onChange = function(v) run(status, { v == "true" and "on" or "off" }, refresh, rerender) end }),
      }),
    }),
  }
  if e.available == false then
    table.insert(children, common.sectionFooter("eq-na", T("Hace falta PipeWire (pipewire y pw-cli) para el ecualizador.")))
  end

  -- Preajustes: el actual marcado; T("Personalizado") aparece al mover una banda.
  local options, keys, selected = {}, {}, nil
  for i, p in ipairs(e.presets or {}) do
    table.insert(options, T(p[2]))
    table.insert(keys, p[1])
    if p[1] == e.preset then selected = i - 1 end
  end
  if e.preset == "custom" then
    table.insert(options, T("Personalizado"))
    table.insert(keys, "custom")
    selected = #options - 1
  end
  table.insert(children, common.sectionHeader("eq-preset-h", T("Preajuste")))
  table.insert(children, ui.select({ key = "eq-preset", options = options, selectedIndex = selected or 0,
                                     enabled = not busy, controlSize = "sm",
                                     onChange = function(idx)
    local key = keys[(tonumber(idx) or 0) + 1]
    if key ~= nil and key ~= "custom" and key ~= e.preset then run(status, { "preset", key }, refresh, rerender) end
  end }))

  local range = e.range or { -12, 12 }
  local rows = {}
  for i, freq in ipairs(e.bands or {}) do
    local band = i - 1
    local confirmed = e.gains and e.gains[i]
    -- El valor puesto a mano deja de hacer falta cuando airpodsd ya lo tiene.
    if drafts[band] ~= nil and pending[band] == nil and sending ~= band and confirmed == drafts[band] then
      drafts[band] = nil
    end
    local value = drafts[band] or confirmed or 0
    table.insert(rows, ui.row({ key = "eq-band-" .. band, gap = 8, align = "center", paddingH = 14, paddingV = 4 }, {
      ui.label({ text = bandLabel(freq), fontSize = 12, color = common.SECONDARY, width = 48 }),
      ui.slider({ key = "eq-slider-" .. band, min = range[1], max = range[2], step = 0.5, value = value,
                  flexGrow = 1, controlSize = "sm", enabled = not busy,
                  onChange = "eqBand" .. band, onDragEnd = "eqBandEnd" .. band }),
      ui.label({ text = fmtDb(value), fontSize = 12, color = common.SECONDARY, width = 52, textAlign = "right" }),
    }))
  end
  if #rows > 0 then
    table.insert(children, ui.row({ key = "eq-bands-h", align = "center" }, {
      common.sectionHeader("eq-bands-title", T("Bandas")),
      ui.spacer({ key = "eq-bands-sp", flexGrow = 1 }),
      ui.row({ key = "eq-reset", paddingH = 4, onClick = function() run(status, { "reset" }, refresh, rerender) end }, {
        ui.label({ text = T("Restablecer"), fontSize = 12, color = busy and common.SECONDARY or "primary" }),
      }),
    }))
    table.insert(children, ui.column({ key = "eq-bands", gap = 0, radius = 14, fill = common.CARD, paddingV = 6 }, rows))
    table.insert(children, common.sectionFooter("eq-f",
      T("Solo afecta a los AirPods. Al subir una banda se baja el volumen general lo mismo, para no saturar.")))
  end

  return ui.column({ padding = 18, gap = 12, fill = "surface", radius = 24, flexGrow = 1 }, {
    header,
    ui.scroll({ key = "eq-scroll", flexGrow = 1 }, { common.scrollBody("eq", 8, children) }),
  })
end

return M
