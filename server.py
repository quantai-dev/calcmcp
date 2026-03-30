"""MCP server for LibreOffice Calc via UNO bridge."""
import atexit
import logging
import os
import uuid
from typing import Any

from mcp.server.fastmcp import FastMCP

from calc_bridge import CalcBridge

_headless = os.environ.get("CALCMCP_HEADLESS", "").lower() in ("1", "true", "yes")
_host = os.environ.get("CALCMCP_HOST", "127.0.0.1")
_port = int(os.environ.get("CALCMCP_PORT", "8000"))

mcp = FastMCP(
    "libreoffice-calc",
    instructions=(
        "Interact with LibreOffice Calc spreadsheets via the UNO bridge. "
        "Open or create a document to get a doc_id, then use that id for "
        "all subsequent operations. Cell addresses use A1 notation (e.g. 'B3'). "
        "Ranges use A1:D5 notation. Row numbers are 1-based."
    ),
    host=_host,
    port=_port,
)

_bridge = CalcBridge(headless=_headless)
_docs: dict[str, Any] = {}   # doc_id -> UNO document object


def _new_id() -> str:
    return str(uuid.uuid4())[:8]


def _require_doc(doc_id: str):
    if doc_id not in _docs:
        raise ValueError(f"Unknown doc_id {doc_id!r}. Open or create a document first.")
    return _docs[doc_id]


@atexit.register
def _cleanup():
    _bridge.shutdown()


# ---------------------------------------------------------------------------
# Document tools
# ---------------------------------------------------------------------------

@mcp.tool()
def open_spreadsheet(path: str) -> dict:
    """Open an existing spreadsheet file (.ods, .xlsx, .xls, .csv).

    Returns a doc_id used by all other tools.
    """
    doc = _bridge.open_document(path)
    doc_id = _new_id()
    _docs[doc_id] = doc
    sheets = _bridge.list_sheets(doc)
    return {"doc_id": doc_id, "sheets": sheets}


@mcp.tool()
def create_spreadsheet() -> dict:
    """Create a new blank Calc spreadsheet in memory.

    Returns a doc_id used by all other tools.
    """
    doc = _bridge.create_document()
    doc_id = _new_id()
    _docs[doc_id] = doc
    sheets = _bridge.list_sheets(doc)
    return {"doc_id": doc_id, "sheets": sheets}


@mcp.tool()
def save_spreadsheet(doc_id: str, path: str | None = None) -> str:
    """Save the spreadsheet.

    - *path* given → save to that file (format inferred from extension).
    - *path* omitted → save in place (document must have been opened from a file).
    """
    doc = _require_doc(doc_id)
    _bridge.save_document(doc, path)
    return "saved"


@mcp.tool()
def close_spreadsheet(doc_id: str, save: bool = False) -> str:
    """Close a spreadsheet.

    Set *save=true* to save before closing. Note: save=true only works if the
    document was previously saved to a file (i.e. save_spreadsheet with a path
    was called at least once). For in-memory documents, call
    save_spreadsheet(doc_id, path=...) first, then close with save=false.
    """
    doc = _require_doc(doc_id)
    _bridge.close_document(doc, save=save)
    del _docs[doc_id]
    return "closed"


# ---------------------------------------------------------------------------
# Sheet tools
# ---------------------------------------------------------------------------

@mcp.tool()
def list_sheets(doc_id: str) -> list[str]:
    """Return the names of all sheets in the document."""
    return _bridge.list_sheets(_require_doc(doc_id))


@mcp.tool()
def add_sheet(doc_id: str, name: str, position: int = -1) -> str:
    """Add a new sheet. *position* is 0-based; -1 appends at the end."""
    _bridge.add_sheet(_require_doc(doc_id), name, position)
    return f"sheet '{name}' added"


@mcp.tool()
def remove_sheet(doc_id: str, name: str) -> str:
    """Remove a sheet by name."""
    _bridge.remove_sheet(_require_doc(doc_id), name)
    return f"sheet '{name}' removed"


@mcp.tool()
def rename_sheet(doc_id: str, old_name: str, new_name: str) -> str:
    """Rename a sheet."""
    _bridge.rename_sheet(_require_doc(doc_id), old_name, new_name)
    return f"renamed '{old_name}' -> '{new_name}'"


# ---------------------------------------------------------------------------
# Cell tools
# ---------------------------------------------------------------------------

@mcp.tool()
def get_cell(doc_id: str, sheet: str, address: str) -> dict:
    """Read a single cell.

    Returns ``{"address": "B3", "value": ..., "formula": "..."}``.
    For plain values, *formula* is the raw content. For formula cells,
    *formula* starts with ``=`` and *value* is the evaluated result.
    """
    return _bridge.get_cell(_require_doc(doc_id), sheet, address)


@mcp.tool()
def set_cell(
    doc_id: str,
    sheet: str,
    address: str,
    value: str | int | float | None = None,
    formula: str | None = None,
) -> str:
    """Write a value or formula to a single cell.

    Provide either *value* (string/number) **or** *formula* (e.g. ``"=SUM(A1:A5)"``).
    Pass ``value=null`` to clear the cell.
    """
    _bridge.set_cell(_require_doc(doc_id), sheet, address, value=value, formula=formula)
    return f"{address} set"


@mcp.tool()
def get_range(doc_id: str, sheet: str, range_address: str) -> dict:
    """Read a rectangular range of cells.

    Returns ``{"range": "A1:C3", "data": [[...], ...], "formulas": [[...], ...]}``.
    *data* holds evaluated values (numbers as floats, empty cells as 0 or ``""``).
    *formulas* holds raw cell content: plain values echo back as-is; formula cells
    start with ``=`` (e.g. ``"=SUM(A1:A5)"``).
    """
    return _bridge.get_range(_require_doc(doc_id), sheet, range_address)


@mcp.tool()
def set_range(
    doc_id: str,
    sheet: str,
    start_address: str,
    data: list[list],
) -> str:
    """Write a 2-D array of values or formulas starting at *start_address*.

    *data* is a list of rows, each row a list of numbers, strings, or formulas.
    Strings starting with ``=`` are written as formulas (e.g. ``"=SUM(A1:A5)"``).
    Example: ``[["Name", "Score"], ["Alice", 95], ["Total", "=SUM(B2:B2)"]]``.
    Each element of *data* must itself be a list — never pass a bare string
    or a flat list of scalars, as strings are iterable and will be split
    into individual characters.
    """
    # Normalise: wrap a bare string, and promote flat rows (scalars) to lists.
    if isinstance(data, str):
        data = [[data]]
    else:
        data = [list(r) if isinstance(r, (list, tuple)) else [r] for r in data]
    _bridge.set_range(_require_doc(doc_id), sheet, start_address, data)
    rows = len(data)
    cols = max((len(r) for r in data), default=0)
    return f"{rows}×{cols} block written at {start_address}"


@mcp.tool()
def get_used_range(doc_id: str, sheet: str) -> dict:
    """Return all data from the used area of a sheet.

    Returns ``{"range": "A1:E10", "data": [[...], ...], "formulas": [[...], ...]}``.
    See *get_range* for the distinction between *data* and *formulas*.
    """
    return _bridge.get_used_range(_require_doc(doc_id), sheet)


# ---------------------------------------------------------------------------
# Row / column tools
# ---------------------------------------------------------------------------

@mcp.tool()
def insert_rows(doc_id: str, sheet: str, start_row: int, count: int = 1) -> str:
    """Insert *count* blank rows before *start_row* (1-based)."""
    _bridge.insert_rows(_require_doc(doc_id), sheet, start_row, count)
    return f"{count} row(s) inserted before row {start_row}"


@mcp.tool()
def delete_rows(doc_id: str, sheet: str, start_row: int, count: int = 1) -> str:
    """Delete *count* rows starting at *start_row* (1-based)."""
    _bridge.delete_rows(_require_doc(doc_id), sheet, start_row, count)
    return f"{count} row(s) deleted from row {start_row}"


@mcp.tool()
def insert_columns(doc_id: str, sheet: str, start_col: str, count: int = 1) -> str:
    """Insert *count* blank columns before *start_col* (column letter, e.g. 'C')."""
    _bridge.insert_columns(_require_doc(doc_id), sheet, start_col, count)
    return f"{count} column(s) inserted before column {start_col}"


@mcp.tool()
def delete_columns(doc_id: str, sheet: str, start_col: str, count: int = 1) -> str:
    """Delete *count* columns starting at *start_col* (column letter)."""
    _bridge.delete_columns(_require_doc(doc_id), sheet, start_col, count)
    return f"{count} column(s) deleted from column {start_col}"


# ---------------------------------------------------------------------------
# Styling tools
# ---------------------------------------------------------------------------

@mcp.tool()
def style_range(
    doc_id: str,
    sheet: str,
    range_address: str,
    bold: bool | None = None,
    italic: bool | None = None,
    font_size: float | None = None,
    font_name: str | None = None,
    color: str | None = None,
    background: str | None = None,
    align: str | None = None,
    valign: str | None = None,
    wrap: bool | None = None,
    underline: bool | None = None,
    strikethrough: bool | None = None,
) -> str:
    """Apply visual styles to a range of cells.

    Only the arguments you supply are changed; omitted ones leave existing
    style untouched. *range_address* can be a single cell (e.g. 'A1') or a
    range (e.g. 'A1:D4').

    - *color* / *background*: '#RRGGBB' hex string (e.g. '#FF0000' for red).
    - *align*: 'left', 'center', 'right', 'justify'.
    - *valign*: 'top', 'middle', 'bottom'.
    - *font_size*: point size (e.g. 12).
    """
    _bridge.style_range(
        _require_doc(doc_id), sheet, range_address,
        bold=bold, italic=italic, font_size=font_size, font_name=font_name,
        color=color, background=background, align=align, valign=valign,
        wrap=wrap, underline=underline, strikethrough=strikethrough,
    )
    return f"styled {range_address}"


@mcp.tool()
def set_column_width(
    doc_id: str,
    sheet: str,
    col: str,
    width_mm: float | None = None,
) -> str:
    """Set the width of a column.

    - *col*: column letter, e.g. 'A' or 'BC'.
    - *width_mm*: width in millimetres. Omit (or pass null) for auto-fit.
    """
    _bridge.set_column_width(_require_doc(doc_id), sheet, col, width_mm)
    label = f"{width_mm} mm" if width_mm is not None else "auto"
    return f"column {col} width → {label}"


@mcp.tool()
def set_row_height(
    doc_id: str,
    sheet: str,
    row: int,
    height_mm: float | None = None,
) -> str:
    """Set the height of a row.

    - *row*: 1-based row number.
    - *height_mm*: height in millimetres. Omit (or pass null) for auto-fit.
    """
    _bridge.set_row_height(_require_doc(doc_id), sheet, row, height_mm)
    label = f"{height_mm} mm" if height_mm is not None else "auto"
    return f"row {row} height → {label}"


@mcp.tool()
def set_range_border(
    doc_id: str,
    sheet: str,
    range_address: str,
    style: str = "thin",
    sides: str = "all",
    color: str = "#000000",
) -> str:
    """Apply a border to a range.

    - *style*: 'thin', 'medium', 'thick', 'double', 'none'.
    - *sides*: 'all', 'outer', 'inner', or any combination of
               'top', 'bottom', 'left', 'right', 'horizontal', 'vertical'
               separated by spaces or commas.
    - *color*: '#RRGGBB' hex string.
    """
    _bridge.set_range_border(_require_doc(doc_id), sheet, range_address,
                             style=style, sides=sides, color=color)
    return f"border ({style}, {sides}) applied to {range_address}"


@mcp.tool()
def merge_cells(doc_id: str, sheet: str, range_address: str) -> str:
    """Merge all cells in a range into one cell."""
    _bridge.merge_cells(_require_doc(doc_id), sheet, range_address)
    return f"{range_address} merged"


@mcp.tool()
def unmerge_cells(doc_id: str, sheet: str, range_address: str) -> str:
    """Unmerge a previously merged range."""
    _bridge.unmerge_cells(_require_doc(doc_id), sheet, range_address)
    return f"{range_address} unmerged"


@mcp.tool()
def set_number_format(doc_id: str, sheet: str, range_address: str, fmt: str) -> str:
    """Apply a number format string to a range.

    Common examples:
    - ``'#,##0.00'``         — two decimal places with thousands separator
    - ``'0%'``               — percentage
    - ``'"$"#,##0.00'``      — US dollar
    - ``'DD/MM/YYYY'``       — date
    - ``'HH:MM:SS'``         — time
    - ``'@'``                — force text
    """
    _bridge.set_number_format(_require_doc(doc_id), sheet, range_address, fmt)
    return f"number format {fmt!r} applied to {range_address}"


# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="CalcMCP MCP server")
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "sse", "streamable-http"],
        help="Transport protocol (default: stdio)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log = logging.getLogger("calcmcp")
    log.info(
        "Starting CalcMCP (transport=%s, host=%s, port=%d, headless=%s)",
        args.transport, _host, _port, _headless,
    )
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
