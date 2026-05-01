# CalcMCP

MCP server for LibreOffice Calc spreadsheets via UNO bridge. Programmatically read/write cells &amp; ranges (including formulas), manage sheets, apply styles, insert/delete rows/columns — all via Model Context Protocol (MCP).

Built by [Ethan Kuhrts](https://github.com/quantai-dev) to showcase MCP development skills.

## Features
- Full LibreOffice Calc integration (headless or GUI)
- Cell/range operations with value/formula support
- Sheet management (add/remove/rename/list)
- Row/column insertion/deletion
- Rich styling: fonts, colors, borders, alignment, widths/heights, number formats, merge/unmerge
- MCP transports: stdio, SSE, streamable-HTTP
- Open WebUI tools included (`open_webui_tool.py`, `open_webui_style_tool.py`)
- CLI for server lifecycle (start/stop/status/logs)

## Installation
1. Install LibreOffice: `sudo snap install libreoffice` (Ubuntu) or equivalent.
2. `pip install &quot;mcp[cli]&quot;`
3. `cd ~/Projects/calcmcp &amp;&amp; pip install -e .`

Requires Python &gt;=3.12.

## Usage as MCP Server

### CLI Commands
```bash
calcmcp start                    # SSE server on localhost:8000
calcmcp start --transport stdio  # For Hermes stdio transport
calcmcp stop
calcmcp restart
calcmcp status
calcmcp logs -f                  # Follow logs
```

### Hermes `config.yaml` Example
```yaml
mcp:
  - server: stdio
    command: calcmcp
    args: [&quot;start&quot;, &quot;--transport&quot;, &quot;stdio&quot;]
  # Or SSE:
  # - server: http
  #   url: http://127.0.0.1:8000/mcp
```

### Open WebUI
1. Copy `open_webui_tool.py` &amp; `open_webui_style_tool.py` to **Workspace &gt; Tools**.
2. Set env `CALCMCP_PATH=/home/ethan/Projects/calcmcp`.
3. LibreOffice auto-starts headless on first tool use.

## Available Tools
All tools require a `doc_id` from `create_spreadsheet()` or `open_spreadsheet(path)`.

**Documents:**
- `create_spreadsheet()` → `{doc_id, sheets}`
- `open_spreadsheet(path)` → `{doc_id, sheets}` (.ods/.xlsx/.xls/.csv)
- `save_spreadsheet(doc_id, path=None)`
- `close_spreadsheet(doc_id, save=False)`

**Sheets:**
- `list_sheets(doc_id)` → `["Sheet1", ...]`
- `add_sheet(doc_id, name, position=-1)`
- `remove_sheet(doc_id, name)`
- `rename_sheet(doc_id, old_name, new_name)`

**Cells/Ranges:**
- `get_cell(doc_id, sheet, address)` → `{address, value, formula}` (A1 notation)
- `set_cell(doc_id, sheet, address, value=None, formula=None)`
- `get_range(doc_id, sheet, range_address)` → `{range, data[][], formulas[][]}`
- `set_range(doc_id, sheet, start_address, data[][])`
- `get_used_range(doc_id, sheet)`

**Rows/Columns:**
- `insert_rows(doc_id, sheet, start_row, count=1)`
- `delete_rows(doc_id, sheet, start_row, count=1)`
- `insert_columns(doc_id, sheet, start_col, count=1)`
- `delete_columns(doc_id, sheet, start_col, count=1)`

**Styling:**
- `style_range(doc_id, sheet, range_address, bold=None, italic=None, font_size=None, font_name=None, color=None, background=None, align=None, valign=None, wrap=None, underline=None, strikethrough=None)`
- `set_column_width(doc_id, sheet, col, width_mm=None)` (null=auto)
- `set_row_height(doc_id, sheet, row, height_mm=None)`
- `set_range_border(doc_id, sheet, range_address, style=&quot;thin&quot;, sides=&quot;all&quot;, color=&quot;#000000&quot;)`
- `merge_cells(doc_id, sheet, range_address)`
- `unmerge_cells(doc_id, sheet, range_address)`
- `set_number_format(doc_id, sheet, range_address, fmt)` (e.g. `'#,##0.00'`, `'0%'`)

## Simple Example
```
doc_id = create_spreadsheet().doc_id
set_cell(doc_id, &quot;Sheet1&quot;, &quot;A1&quot;, &quot;Sales&quot;)
set_cell(doc_id, &quot;Sheet1&quot;, &quot;B1&quot;, value=100)
set_cell(doc_id, &quot;Sheet1&quot;, &quot;C1&quot;, formula=&quot;=B1*1.1&quot;)
style_range(doc_id, &quot;Sheet1&quot;, &quot;A1:C1&quot;, bold=true)
get_range(doc_id, &quot;Sheet1&quot;, &quot;A1:C1&quot;)
save_spreadsheet(doc_id, &quot;example.ods&quot;)
```

## License
MIT License

Copyright © 2026 Ethan Kuhrts
