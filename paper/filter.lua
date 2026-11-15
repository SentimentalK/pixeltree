-- Pandoc Lua filter: PAPER.md -> LaTeX body for paper/template.tex.
--
-- * the first H1 becomes the title, the "**Summary.**" paragraph becomes the abstract, the status line and the
--   horizontal rule are dropped;
-- * manual section numbers ("3.1 Box convention") are stripped, LaTeX numbers the sections in the same order, so
--   the paper's "§6.2"-style cross references stay correct;
-- * "[n]" becomes \cite{key} (keys from paper/refs.bib, in the order of the related-work list);
-- * relative links point to the GitHub repository;
-- * a few non-ASCII symbols and the two CJK glyphs become engine-neutral macros (\pxcjk, \ensuremath{...}) so the
--   same .tex compiles with XeLaTeX and, through the template's pdfTeX branch, with pdfLaTeX;
-- * code blocks become fvextra Verbatim with line breaking, inline code becomes breakable \path where safe.

local REPO = "https://github.com/SentimentalK/pixeltree/blob/main/"
local CITE = {"lu2024omniparser", "muryn2025screen2ax", "xie2024osworld", "kuntz2025osharm",
              "abhyankar2025osworldhuman", "zhang2026believe"}

local SYMBOLS = {
  ["×"] = "\\ensuremath{\\times}", ["−"] = "\\ensuremath{-}", ["→"] = "\\ensuremath{\\rightarrow}",
  ["√"] = "\\pxsurd{}", ["≥"] = "\\ensuremath{\\geq}",
}

-- CJK glyphs become \pxcjk{<code point>}; the preamble prints them with a CJK font (XeLaTeX) or the CJK package
-- (pdfLaTeX, one \pxcjkdef line per glyph).
local function cjk_macro(cp)
  return string.format("\\pxcjk{%04X}", cp)
end

local function is_cjk(cp)
  return (cp >= 0x4E00 and cp <= 0x9FFF) or (cp >= 0x3400 and cp <= 0x4DBF)
end

local function latex_escape(s)
  return (s:gsub("[\\{}$&#%%_^~]", function(c)
    if c == "\\" then return "\\textbackslash{}" end
    if c == "^" then return "\\textasciicircum{}" end
    if c == "~" then return "\\textasciitilde{}" end
    return "\\" .. c
  end))
end

-- Split a string into runs; returns a list of inlines (Str for plain text, RawInline for special characters).
local function convert_text(s)
  local out, buf = {}, {}
  local function flush()
    if #buf > 0 then out[#out + 1] = pandoc.Str(table.concat(buf)); buf = {} end
  end
  for _, cp in utf8.codes(s) do
    local ch = utf8.char(cp)
    if SYMBOLS[ch] then
      flush(); out[#out + 1] = pandoc.RawInline("latex", SYMBOLS[ch])
    elseif is_cjk(cp) then
      flush(); out[#out + 1] = pandoc.RawInline("latex", cjk_macro(cp))
    else
      buf[#buf + 1] = ch
    end
  end
  flush()
  return out
end

-- Same conversion for verbatim content (fvextra commandchars \ { }).
local function convert_verbatim(s)
  local parts = {}
  for _, cp in utf8.codes(s) do
    local ch = utf8.char(cp)
    if SYMBOLS[ch] then parts[#parts + 1] = SYMBOLS[ch]
    elseif is_cjk(cp) then parts[#parts + 1] = cjk_macro(cp)
    elseif ch == "\\" then parts[#parts + 1] = "\\textbackslash{}"
    elseif ch == "{" then parts[#parts + 1] = "\\{"
    elseif ch == "}" then parts[#parts + 1] = "\\}"
    else parts[#parts + 1] = ch end
  end
  return table.concat(parts)
end

function Str(el)
  local s = el.text
  -- citations "[n]" (possibly followed by punctuation)
  local pre, n, post = s:match("^(.-)%[(%d)%](.*)$")
  if n and CITE[tonumber(n)] then
    local out = {}
    for _, x in ipairs(convert_text(pre)) do out[#out + 1] = x end
    out[#out + 1] = pandoc.RawInline("latex", "\\cite{" .. CITE[tonumber(n)] .. "}")
    for _, x in ipairs(convert_text(post)) do out[#out + 1] = x end
    return out
  end
  local conv = convert_text(s)
  if #conv == 1 and conv[1].t == "Str" then return nil end
  return conv
end

function Code(el)
  local t = el.text
  if t:match("^[%w_%./:=,%-%+%*%(%)%[%]@ ]+$") and not t:match("%%") then
    return pandoc.RawInline("latex", "\\path{" .. t .. "}")
  end
  local parts = {}
  for _, cp in utf8.codes(t) do
    local ch = utf8.char(cp)
    if SYMBOLS[ch] then parts[#parts + 1] = SYMBOLS[ch]
    elseif is_cjk(cp) then parts[#parts + 1] = cjk_macro(cp)
    else parts[#parts + 1] = latex_escape(ch) end
  end
  return pandoc.RawInline("latex", "\\texttt{" .. table.concat(parts) .. "}")
end

function CodeBlock(el)
  return pandoc.RawBlock("latex",
    "\\begin{Verbatim}[breaklines,breaksymbolleft={},fontsize=\\small,commandchars=\\\\\\{\\}]\n"
    .. convert_verbatim(el.text) .. "\n\\end{Verbatim}")
end

function Link(el)
  local t = el.target
  if not t:match("^%a+:") and not t:match("^#") then
    el.target = REPO .. t
  end
  local txt = pandoc.utils.stringify(el.content)
  if #el.content == 1 and el.content[1].t == "Str" and txt:match("^[%w_%./:%-]+$") and txt:match("[/_]") then
    el.content = {pandoc.RawInline("latex", "\\nolinkurl{" .. txt .. "}")}
  end
  return el
end

function Header(el)
  local first = el.content[1]
  if first and first.t == "Str" and first.text:match("^%d+%.%d*%.?$") then
    el.content:remove(1)
    if el.content[1] and el.content[1].t == "Space" then el.content:remove(1) end
  end
  el.level = el.level - 1          -- "##" -> \section
  return el
end

function Pandoc(doc)
  local blocks, meta = pandoc.List(), doc.meta
  for _, b in ipairs(doc.blocks) do
    if b.t == "Header" and b.level <= 1 and not meta.title then
      meta.title = b.content
    elseif b.t == "HorizontalRule" then
      -- dropped
    elseif b.t == "Para" and b.content[1] and b.content[1].t == "Emph" and not meta.status_dropped then
      meta.status_dropped = true       -- "*A short technical report. ...*" status line
    elseif b.t == "Para" and b.content[1] and b.content[1].t == "Strong"
        and pandoc.utils.stringify(b.content[1]) == "Summary." and not meta.abstract then
      local rest = pandoc.List(b.content)
      rest:remove(1)
      if rest[1] and rest[1].t == "Space" then rest:remove(1) end
      meta.abstract = pandoc.MetaBlocks({pandoc.Para(rest)})
    else
      blocks:insert(b)
    end
  end
  meta.status_dropped = nil
  doc.blocks = blocks
  doc.meta = meta
  -- run the inline/block converters on the remaining document and on the title / abstract
  doc = doc:walk({Str = Str, Code = Code, CodeBlock = CodeBlock, Link = Link})
  doc.meta.title = pandoc.MetaInlines(pandoc.Inlines(meta.title):walk({Str = Str, Code = Code}))
  return doc
end

return {{Header = Header}, {Pandoc = Pandoc}}
