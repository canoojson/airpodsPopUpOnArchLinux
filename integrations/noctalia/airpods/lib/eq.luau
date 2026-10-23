--!nonstrict
-- Vista del ecualizador: interruptor, preajustes y una barra por banda. Los cambios van
-- por `airpodsctl eq`, que guarda la configuración y avisa a airpodsd; airpodsd cambia
-- las ganancias del filtro de PipeWire en vivo.

local M = {}

local busy = false
local drafts = {}   -- banda -> dB mientras se arrastra

local function ctl(status)
  return (status and status.ctl) or "airpodsctl"
end

function M.reset()
  busy = false
  drafts = {}
end

local function run(status, args, refresh, rerender)
  if busy then return end
  busy = true
  rerender()
  local argv = { ctl(status), "eq" }
  for _, a in ipairs(args) do table.insert(argv, a) end
  noctalia.runAsync(argv, function(result)
    busy = false
    drafts = {}
    if result.exitCode ~= 0 then
      noctalia.notifyError("AirPods", (result.stderr ~= "" and result.stderr) or "No se pudo cambiar el ecualizador")
    end
    refresh()
    rerender()
  end, 8000)
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
  if e.preset == "custom" then return "Personalizado" end
  for _, p in ipairs(e.presets or {}) do
    if p[1] == e.preset then return p[2] end
  end
  return e.preset
end

function M.render(status, opts)
  local common, refresh, rerender = opts.common, opts.refresh, opts.rerender
  local e = (status and status.eq) or {}
  local enabled = e.enabled == true

  local header = ui.column({ key = "eq-header", gap = 6 }, {
    ui.row({ key = "eq-back", gap = 2, align = "center", onClick = opts.back }, {
      ui.glyph({ name = "chevron-left", size = 18, color = "primary" }),
      ui.label({ text = "AirPods", fontSize = 14, color = "primary" }),
    }),
    ui.label({ text = "Ecualizador", fontSize = 22, fontWeight = "bold" }),
  })

  local children = {
    common.group("eq-on-g", {
      common.listRow("eq-on", {
        title = "Ecualizador", subtitle = (enabled and e.active ~= true) and "Se aplica al conectar los AirPods" or nil,
        trailing = ui.toggle({ key = "eq-on-toggle", checked = enabled, enabled = not busy and e.available ~= false,
                               onChange = function(v) run(status, { v == "true" and "on" or "off" }, refresh, rerender) end }),
      }),
    }),
  }
  if e.available == false then
    table.insert(children, common.sectionFooter("eq-na", "Hace falta PipeWire (pipewire y pw-cli) para el ecualizador."))
  end

  -- Preajustes: el actual marcado; "Personalizado" aparece al mover una banda.
  local options, keys, selected = {}, {}, nil
  for i, p in ipairs(e.presets or {}) do
    table.insert(options, p[2])
    table.insert(keys, p[1])
    if p[1] == e.preset then selected = i - 1 end
  end
  if e.preset == "custom" then
    table.insert(options, "Personalizado")
    table.insert(keys, "custom")
    selected = #options - 1
  end
  table.insert(children, common.sectionHeader("eq-preset-h", "Preajuste"))
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
    local value = drafts[band] or (e.gains and e.gains[i]) or 0
    table.insert(rows, ui.row({ key = "eq-band-" .. band, gap = 8, align = "center", paddingH = 14, paddingV = 4 }, {
      ui.label({ text = bandLabel(freq), fontSize = 12, color = common.SECONDARY, width = 48 }),
      ui.slider({ key = "eq-slider-" .. band, min = range[1], max = range[2], step = 0.5, value = value,
                  flexGrow = 1, controlSize = "sm", enabled = not busy,
                  onChange = function(v)
        drafts[band] = tonumber(v) or value
        rerender()
      end,
                  onDragEnd = function()
        if drafts[band] ~= nil then run(status, { "set", tostring(band), tostring(drafts[band]) }, refresh, rerender) end
      end }),
      ui.label({ text = fmtDb(value), fontSize = 12, color = common.SECONDARY, width = 52, textAlign = "right" }),
    }))
  end
  if #rows > 0 then
    table.insert(children, ui.row({ key = "eq-bands-h", align = "center" }, {
      common.sectionHeader("eq-bands-title", "Bandas"),
      ui.spacer({ key = "eq-bands-sp", flexGrow = 1 }),
      ui.row({ key = "eq-reset", paddingH = 4, onClick = function() run(status, { "reset" }, refresh, rerender) end }, {
        ui.label({ text = "Restablecer", fontSize = 12, color = busy and common.SECONDARY or "primary" }),
      }),
    }))
    table.insert(children, ui.column({ key = "eq-bands", gap = 0, radius = 14, fill = common.CARD, paddingV = 6 }, rows))
    table.insert(children, common.sectionFooter("eq-f",
      "Solo afecta a los AirPods. Al subir una banda se baja el volumen general lo mismo, para no saturar."))
  end

  return ui.column({ padding = 18, gap = 12, fill = "surface", radius = 24, flexGrow = 1 }, {
    header,
    ui.scroll({ key = "eq-scroll", flexGrow = 1 }, { common.scrollBody("eq", 8, children) }),
  })
end

return M
