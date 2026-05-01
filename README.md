# MCP-A

[![MCP](https://img.shields.io/badge/MCP-Protocol-blue)](https://modelcontextprotocol.io/)
[![Python](https://img.shields.io/badge/Python-3.12+-3776ab)](https://python.org)
[![License](https://img.shields.io/badge/License-Apache%202.0-green)](LICENSE)

**MCP-A (Model Context Protocol Agent)** is an AI-native spreadsheet automation system built on the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/). It provides programmatic control over LibreOffice Calc via a UNO bridge, enabling AI agents to read, write, style, and manipulate spreadsheets with semantic understanding.

This is a reference implementation demonstrating **MCP-native tool architecture** — where AI agents interact with structured data through well-defined protocol interfaces rather than brittle API wrappers.

---

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           MCP-A Architecture                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────┐    ┌─────────────────┐    ┌──────────────────────┐     │
│  │   AI Agent      │    │   MCP Server    │    │   LibreOffice        │     │
│  │  (Hermes, etc)  │◄──►│  (FastMCP)      │◄──►│   Calc via UNO       │     │
│  │                 │    │                 │    │   Bridge             │     │
│  │  • Semantic     │    │  • Protocol     │    │                      │     │
│  │    intent       │    │    validation   │    │  • Document I/O      │     │
│  │  • Context      │    │  • Tool         │    │  • Cell operations   │     │
│  │    management   │    │    routing      │    │  • Styling engine    │     │
│  │  • Multi-step   │    │  • Transport    │    │  • Formula eval      │     │
│  │    reasoning    │    │    abstraction  │    │                      │     │
│  └─────────────────┘    └─────────────────┘    └──────────────────────┘     │
│          │                       │                                               │
│          │              ┌────────┴────────┐                                   │
│          │              │  Transports     │                                   │
│          │              │  • stdio        │                                   │
│          │              │  • SSE          │                                   │
│          │              │  • streamable-  │                                   │
│          │              │    http         │                                   │
│          │              └─────────────────┘                                   │
│          │                                                                  │
│          └────────────────────────────────────────────────┐               │
│                                                             │               │
│  ┌─────────────────────────────────────────────────────────┐│               │
│  │                    Tool Registry                        ││               │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  ││               │
│  │  │ Document │ │   Cell   │ │  Sheet   │ │  Style   │  ││               │
│  │  │  Tools   │ │  Tools   │ │  Tools   │ │  Tools   │  ││               │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘  ││               │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐              ││               │
│  │  │   Row/   │ │   CLI    │ │ Open     │              ││               │
│  │  │  Column  │ │ Manager  │ │ WebUI    │              ││               │
│  │  │  Tools   │ │          │ │ Tools    │              ││               │
│  │  └──────────┘ └──────────┘ └──────────┘              ││               │
│  └─────────────────────────────────────────────────────────┘               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Design Principles

1. **Protocol-Native**: Built on the Model Context Protocol standard for seamless AI agent integration
2. **Transport Agnostic**: Works over stdio (for local agents), SSE, or HTTP
3. **Semantic Tools**: Operations express intent (`style_range`, `set_formula`) not implementation
4. **Session-Based**: Documents persist in memory with UUID-based handles for multi-turn workflows
5. **Bidirectional**: AI agents can both read spreadsheet state and write structured data

---

## 🛠️ Tool Definitions

### Document Lifecycle

| Tool | Description | Returns |
|------|-------------|---------|
| `create_spreadsheet()` | Create new in-memory spreadsheet | `doc_id`, `sheets` |
| `open_spreadsheet(path)` | Open existing file (.ods/.xlsx/.xls/.csv) | `doc_id`, `sheets` |
| `save_spreadsheet(doc_id, path?)` | Save to disk | `"saved"` |
| `close_spreadsheet(doc_id, save=false)` | Close and cleanup | `"closed"` |

### Sheet Management

| Tool | Description |
|------|-------------|
| `list_sheets(doc_id)` | → `["Sheet1", "Sheet2", ...]` |
| `add_sheet(doc_id, name, position=-1)` | Insert at position (-1 = append) |
| `remove_sheet(doc_id, name)` | Delete sheet |
| `rename_sheet(doc_id, old_name, new_name)` | Rename existing sheet |

### Cell Operations

| Tool | Parameters | Description |
|------|------------|-------------|
| `get_cell` | `(doc_id, sheet, address)` | Read single cell (A1 notation) |
| `set_cell` | `(doc_id, sheet, address, value?, formula?)` | Write value or formula |
| `get_range` | `(doc_id, sheet, range_address)` | Read A1:D5 range |
| `set_range` | `(doc_id, sheet, start_addr, data[][])` | Write 2D data array |
| `get_used_range` | `(doc_id, sheet)` | Get all populated cells |

### Row & Column Operations

| Tool | Parameters |
|------|------------|
| `insert_rows(doc_id, sheet, start_row, count=1)` | Insert before row N |
| `delete_rows(doc_id, sheet, start_row, count=1)` | Remove rows |
| `insert_columns(doc_id, sheet, start_col, count=1)` | Insert before column letter |
| `delete_columns(doc_id, sheet, start_col, count=1)` | Remove columns |

### Styling Engine

| Tool | Key Parameters |
|------|----------------|
| `style_range` | `bold`, `italic`, `font_size`, `font_name`, `color` (#RRGGBB), `background`, `align`, `valign` |
| `set_column_width` | `col` (letter), `width_mm` (null = auto) |
| `set_row_height` | `row` (1-based), `height_mm` (null = auto) |
| `set_range_border` | `style` (thin/medium/thick/double), `sides` (all/top/bottom/left/right), `color` |
| `merge_cells` / `unmerge_cells` | `range_address` |
| `set_number_format` | `fmt` string (e.g., `'#,##0.00'`, `'0%'`)

---

## 📋 Installation

### Prerequisites

```bash
# Ubuntu/Debian
sudo snap install libreoffice

# Or equivalent for your platform
```

### Package Installation

```bash
# Clone repository
git clone https://github.com/quantai-dev/calcmcp.git
cd calcmcp

# Install MCP framework
pip install "mcp[cli]"

# Install package (editable)
pip install -e .
```

**Requirements**: Python >=3.12

---

## 🚀 Usage Examples

### Example 1: Basic Spreadsheet Creation

```python
# AI agent workflow via MCP tools
doc_id = create_spreadsheet().doc_id

set_cell(doc_id, "Sheet1", "A1", "Product")
set_cell(doc_id, "Sheet1", "B1", "Price")
set_cell(doc_id, "Sheet1", "C1", "Quantity")
set_cell(doc_id, "Sheet1", "D1", "Total")

set_range(doc_id, "Sheet1", "A2", [
    ["Widget", 19.99, 150],
    ["Gadget", 29.99, 75],
    ["Thingama", 9.99, 300]
])

set_cell(doc_id, "Sheet1", "D2", formula="=B2*C2")
set_cell(doc_id, "Sheet1", "D3", formula="=B3*C3")
set_cell(doc_id, "Sheet1", "D4", formula="=B4*C4")

style_range(doc_id, "Sheet1", "A1:D1", bold=True, background="#4472C4", color="#FFFFFF")
style_range(doc_id, "Sheet1", "B2:D4", align="right")
set_number_format(doc_id, "Sheet1", "B2:B4", '"$"#,##0.00')
set_number_format(doc_id, "Sheet1", "D2:D4", '"$"#,##0.00')

set_range_border(doc_id, "Sheet1", "A1:D5", style="thin", sides="all")

save_spreadsheet(doc_id, "inventory.xlsx")
close_spreadsheet(doc_id)
```

### Example 2: Hermes Agent Integration

Configure in `~/.hermes/config.yaml`:

```yaml
mcp:
  - server: stdio
    command: calcmcp
    args: ["start", "--transport", "stdio"]
    env:
      CALCMCP_HEADLESS: "true"

  # Or use SSE transport:
  # - server: http
  #   url: http://127.0.0.1:8000/mcp
```

After restart, Hermes automatically discovers all tools:

```
> Create a quarterly sales report with charts
I'll create a professional sales report with formatted data.

1. First, let me create a new spreadsheet...
✓ Created spreadsheet (doc_id: a3f8e21b)

2. Setting up headers and Q1-Q4 data...
✓ Added headers and sales data

3. Applying currency formatting and totals...
✓ Formatted columns and added SUM formulas

4. Creating header row styling...
✓ Applied branding colors

5. Saving to ~/Documents/q1_q4_sales.xlsx
✓ Report saved successfully
```

### Example 3: Streamlit Integration

```python
import streamlit as st
from mcp import ClientSession, StdioServerParameters

st.title("📊 MCP-A Spreadsheet Agent")

# Connect to MCP-A server
async with ClientSession(server) as session:
    tools = await session.list_tools()

uploaded = st.file_uploader("Upload spreadsheet", type=["xlsx", "ods", "csv"])

if uploaded:
    # Agent queries data
    result = await session.call_tool("open_spreadsheet", {"path": uploaded.name})
    doc_id = result.content[0].doc_id

    # Read data
    data = await session.call_tool("get_used_range", {"doc_id": doc_id, "sheet": "Sheet1"})
    st.dataframe(data.content[0].data)
```

---

## 🖥️ CLI Reference

```bash
# Start server (default: SSE on localhost:8000)
calcmcp start

# Start with stdio transport (for local agents)
calcmcp start --transport stdio

# Start with custom port/headless mode
calcmcp start --port 9000 --headless

# Server lifecycle management
calcmcp status          # Check if running
calcmcp stop            # Graceful shutdown
calcmcp restart         # Restart with same flags
calcmcp logs -f         # Follow logs in real-time
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CALCMCP_HEADLESS` | `false` | Run LibreOffice without GUI |
| `CALCMCP_HOST` | `127.0.0.1` | Server bind address |
| `CALCMCP_PORT` | `8000` | Server port |

---

## 🔌 Protocol Compliance

MCP-A implements the **Model Context Protocol** specification:

- ✅ **Tool Discovery**: Full tool schema with descriptions and types
- ✅ **Typed Arguments**: Pydantic-validated parameter schemas
- ✅ **Structured Responses**: Consistent JSON return values
- ✅ **Error Handling**: Protocol-compliant error messages
- ✅ **Multiple Transports**: stdio, SSE, streamable-HTTP

---

## 📊 Performance

Native UNO bridge performance characteristics:

| Operation | Latency (local) | Throughput |
|-----------|-----------------|------------|
| Single cell read | ~10ms | — |
| Cell write | ~15ms | — |
| 1000×1000 range read | ~2s | 500k cells/sec |
| Batch range write | ~3s | 330k cells/sec |
| Style application | ~50ms/range | — |

*Measured on AMD Ryzen 9, LibreOffice 24.x, local socket connection.*

---

## 🤝 Contributing

MCP-A is built to demonstrate MCP-native architecture. To extend:

1. **Add Tools**: Define in `server.py` with `@mcp.tool()` decorator
2. **Add Transports**: FastMCP supports additional transports out of the box
3. **Bridge Extensions**: Extend `calc_bridge.py` for Calc-specific features

```python
@mcp.tool()
def my_custom_operation(doc_id: str, param: str) -> dict:
    """Custom operation for specialized workflows.

    Args:
        doc_id: Document handle
        param: Operation parameter

    Returns:
        Operation results
    """
    doc = _require_doc(doc_id)
    # Implementation here
    return {"status": "success", "result": ...}
```

---

## 📄 License

```
Copyright 2026 Ethan Kuhrts (Superposition.devs)

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```

---

## 🔗 Links

- **Model Context Protocol**: https://modelcontextprotocol.io/
- **MCP Python SDK**: https://github.com/modelcontextprotocol/python-sdk
- **LibreOffice UNO**: https://api.libreoffice.org/
- **Author**: https://github.com/quantai-dev

---

<p align="center">
  <i>Built with ❤️ by Superposition.devs</i><br>
  <sub>MCP-Native • AI-First • Protocol Native</sub>
</p>
