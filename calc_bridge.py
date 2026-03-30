"""LibreOffice Calc UNO bridge."""
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

LO_PROGRAM_PATH = "/snap/libreoffice/366/lib/libreoffice/program"
if LO_PROGRAM_PATH not in sys.path:
    sys.path.insert(0, LO_PROGRAM_PATH)

# Must be set before importing uno so the full LibreOffice type registry is
# loaded into the local UNO runtime.  Without this, createInstanceWithContext
# fails with "Binary URP bridge disposed during call" because pyuno cannot
# deserialise returned object references.
os.environ.setdefault(
    "URE_BOOTSTRAP",
    f"vnd.sun.star.pathname:{LO_PROGRAM_PATH}/fundamentalrc",
)
os.environ.setdefault("UNO_PATH", LO_PROGRAM_PATH)

import uno  # noqa: E402
import unohelper  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pv(name: str, value):
    from com.sun.star.beans import PropertyValue
    pv = PropertyValue()
    pv.Name = name
    pv.Value = value
    return pv


def _col_to_index(col: str) -> int:
    """'A' -> 0, 'B' -> 1, 'AA' -> 26 (0-based)."""
    result = 0
    for ch in col.upper():
        result = result * 26 + (ord(ch) - ord("A") + 1)
    return result - 1


def _index_to_col(idx: int) -> str:
    """0 -> 'A', 25 -> 'Z', 26 -> 'AA'."""
    name = ""
    idx += 1
    while idx:
        idx, rem = divmod(idx - 1, 26)
        name = chr(ord("A") + rem) + name
    return name


def _parse_address(address: str) -> tuple[int, int]:
    """'A1' -> (col=0, row=0)."""
    m = re.match(r"^([A-Za-z]+)(\d+)$", address.strip())
    if not m:
        raise ValueError(f"Invalid cell address: {address!r}")
    return _col_to_index(m.group(1)), int(m.group(2)) - 1


def _parse_range(range_addr: str) -> tuple[int, int, int, int]:
    """'A1:D5' -> (col1=0, row1=0, col2=3, row2=4)."""
    parts = range_addr.strip().split(":")
    col1, row1 = _parse_address(parts[0])
    if len(parts) == 1:
        return col1, row1, col1, row1
    col2, row2 = _parse_address(parts[1])
    return col1, row1, col2, row2


def _cell_to_python(cell):
    """Return (value, formula) from a UNO cell.

    CellContentType enum values: EMPTY, VALUE (numeric), TEXT, FORMULA.
    We compare using the .value string attribute rather than importing the
    enum class directly (which doesn't work cleanly in all PyUNO setups).
    """
    ct = cell.getType().value   # e.g. "EMPTY", "TEXT", "VALUE", "FORMULA"
    formula = cell.getFormula()
    if ct == "EMPTY":
        return None, formula
    if ct == "TEXT":
        return cell.getString(), formula
    if ct == "VALUE":
        return cell.getValue(), formula
    # FORMULA — try to return the evaluated value as a number; fall back to string
    val_str = cell.getString()
    try:
        return float(val_str), formula
    except (ValueError, TypeError):
        return val_str or None, formula


def _range_addr_to_str(addr) -> str:
    """Convert com.sun.star.table.CellRangeAddress to 'A1:D5' string."""
    c1 = _index_to_col(addr.StartColumn)
    c2 = _index_to_col(addr.EndColumn)
    return f"{c1}{addr.StartRow + 1}:{c2}{addr.EndRow + 1}"


def _path_to_url(path: str) -> str:
    return Path(os.path.abspath(path)).as_uri()


def _parse_color(color) -> int:
    """'#RRGGBB' string or integer → int."""
    if isinstance(color, int):
        return color
    if isinstance(color, str):
        return int(color.lstrip("#"), 16)
    raise ValueError(f"Invalid color {color!r}. Use '#RRGGBB' or an integer.")


def _make_border_line(style: str, color: int = 0):
    from com.sun.star.table import BorderLine2  # noqa: PLC0415
    bl = BorderLine2()
    bl.Color = color
    if style == "none":
        bl.LineStyle = 0
        bl.LineWidth = 0
    elif style == "thin":
        bl.LineStyle = 0
        bl.LineWidth = 26
    elif style == "medium":
        bl.LineStyle = 0
        bl.LineWidth = 53
    elif style == "thick":
        bl.LineStyle = 0
        bl.LineWidth = 88
    elif style == "double":
        bl.LineStyle = 4
        bl.LineWidth = 88
        bl.InnerLineWidth = 26
        bl.LineDistance = 26
    else:
        raise ValueError(
            f"Unknown border style {style!r}. "
            "Use 'none', 'thin', 'medium', 'thick', 'double'."
        )
    return bl


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------

class CalcBridge:
    """Manages a single LibreOffice Calc instance via UNO socket bridge.

    By default launches a visible window. Pass ``headless=True`` to run
    in the background with no GUI.
    """

    def __init__(self, headless: bool = False):
        self._headless = headless
        self._process: subprocess.Popen | None = None
        self._ctx = None
        self._desktop = None

    @staticmethod
    def _find_free_port() -> int:
        import socket as _socket
        with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
            s.bind(("localhost", 0))
            return s.getsockname()[1]

    # -- connection ----------------------------------------------------------

    def connect(self):
        if self._ctx is not None:
            return
        port = self._find_free_port()
        accept = f"socket,host=localhost,port={port};urp;"
        cmd = ["libreoffice", "--nologo", "--norestore", "--nofirststartwizard",
               f"--accept={accept}"]
        if self._headless:
            cmd.insert(1, "--headless")
            cmd.insert(2, "--nodefault")
        env = os.environ.copy()
        if not self._headless:
            # Ensure the X display is visible from the subprocess; default to
            # :0 if the calling process somehow has DISPLAY unset.
            env.setdefault("DISPLAY", ":0")
        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        local_ctx = uno.getComponentContext()
        resolver = local_ctx.ServiceManager.createInstanceWithContext(
            "com.sun.star.bridge.UnoUrlResolver", local_ctx
        )
        url = f"uno:{accept}StarOffice.ComponentContext"
        # GUI mode takes much longer to start than headless.
        delays = (1, 2, 3, 5, 8) if self._headless else (2, 4, 6, 10, 15, 20, 25)
        for delay in delays:
            try:
                self._ctx = resolver.resolve(url)
                break
            except Exception:
                time.sleep(delay)
        else:
            self._process.terminate()
            raise RuntimeError("Could not connect to LibreOffice after retries")
        smgr = self._ctx.ServiceManager
        self._desktop = smgr.createInstanceWithContext(
            "com.sun.star.frame.Desktop", self._ctx
        )

    def _reset(self):
        """Clear connection state and terminate the LO process if running."""
        self._ctx = None
        self._desktop = None
        if self._process is not None:
            try:
                self._process.terminate()
            except Exception:
                pass
            self._process = None

    @staticmethod
    def _is_bridge_error(e: Exception) -> bool:
        msg = str(e).lower()
        return "disposed" in msg or "bridge" in msg

    def ensure_connected(self):
        if self._ctx is None:
            self.connect()
            return
        # Fast check: if the LO process has exited, the bridge is definitely dead.
        if self._process is not None and self._process.poll() is not None:
            self._reset()
            self.connect()
            return
        # Probe using _desktop — a remote com.sun.star.frame.Desktop object —
        # which forces a real RPC round-trip (unlike ctx.ServiceManager which
        # may return a locally-cached attribute without hitting the socket).
        if self._desktop is not None:
            try:
                self._desktop.getAvailableServiceNames()
            except Exception:
                self._reset()
                self.connect()

    def shutdown(self):
        if self._ctx is not None:
            try:
                self._desktop.terminate()
            except Exception:
                pass
        self._reset()

    # -- documents -----------------------------------------------------------

    def _load_url(self, url: str, props: tuple):
        """Call loadComponentFromURL, reconnecting once on bridge-disposed errors."""
        for attempt in range(2):
            self.ensure_connected()
            try:
                return self._desktop.loadComponentFromURL(url, "_blank", 0, props)
            except Exception as e:
                if attempt == 0 and self._is_bridge_error(e):
                    self._reset()
                    continue
                raise

    def open_document(self, path: str):
        url = _path_to_url(path)
        doc = self._load_url(
            url,
            (_make_pv("MacroExecutionMode", 4),
             _make_pv("Hidden", self._headless)),
        )
        if doc is None:
            raise RuntimeError(f"Failed to open: {path}")
        return doc

    def create_document(self):
        doc = self._load_url(
            "private:factory/scalc",
            (_make_pv("Hidden", self._headless),),
        )
        return doc

    def save_document(self, doc, path: str | None = None):
        if path is None:
            doc.store()
            return
        url = _path_to_url(path)
        ext = Path(path).suffix.lower()
        filter_map = {
            ".xlsx": "Calc MS Excel 2007 XML",
            ".xls":  "MS Excel 97",
            ".csv":  "Text - txt - csv (StarCalc)",
            ".ods":  "calc8",
        }
        props = []
        if ext in filter_map:
            props.append(_make_pv("FilterName", filter_map[ext]))
        doc.storeToURL(url, tuple(props))

    def close_document(self, doc, save: bool = False):
        if save:
            if not doc.getURL():
                raise ValueError(
                    "Cannot save in place: this document was created in memory "
                    "and has no file path. Call save_spreadsheet(doc_id, path=...) "
                    "first, then close."
                )
            doc.store()
        doc.close(True)

    # -- sheets --------------------------------------------------------------

    def list_sheets(self, doc) -> list[str]:
        sheets = doc.getSheets()
        return [sheets.getByIndex(i).getName() for i in range(sheets.getCount())]

    def add_sheet(self, doc, name: str, position: int = -1):
        sheets = doc.getSheets()
        if position < 0:
            position = sheets.getCount()
        sheets.insertNewByName(name, position)

    def remove_sheet(self, doc, name: str):
        doc.getSheets().removeByName(name)

    def rename_sheet(self, doc, old_name: str, new_name: str):
        doc.getSheets().getByName(old_name).setName(new_name)

    def _sheet(self, doc, name: str):
        return doc.getSheets().getByName(name)

    # -- cells ---------------------------------------------------------------

    def get_cell(self, doc, sheet_name: str, address: str) -> dict:
        col, row = _parse_address(address)
        cell = self._sheet(doc, sheet_name).getCellByPosition(col, row)
        value, formula = _cell_to_python(cell)
        return {"address": address.upper(), "value": value, "formula": formula}

    def set_cell(self, doc, sheet_name: str, address: str,
                 value=None, formula: str | None = None):
        col, row = _parse_address(address)
        cell = self._sheet(doc, sheet_name).getCellByPosition(col, row)
        if formula is not None:
            cell.setFormula(formula)
        elif isinstance(value, (int, float)):
            cell.setValue(value)
        elif value is None:
            cell.setString("")
        else:
            cell.setString(str(value))

    def get_range(self, doc, sheet_name: str, range_addr: str) -> dict:
        col1, row1, col2, row2 = _parse_range(range_addr)
        cr = self._sheet(doc, sheet_name).getCellRangeByPosition(
            col1, row1, col2, row2
        )
        return {
            "range": range_addr.upper(),
            "data": [list(r) for r in cr.getDataArray()],
            "formulas": [list(r) for r in cr.getFormulaArray()],
        }

    def set_range(self, doc, sheet_name: str, start_address: str,
                  data: list[list]):
        if not data:
            return
        col, row = _parse_address(start_address)
        num_rows = len(data)
        num_cols = max(len(r) for r in data)
        padded = [list(r) + [""] * (num_cols - len(r)) for r in data]

        has_formulas = any(
            isinstance(cell, str) and cell.startswith("=")
            for row_d in padded for cell in row_d
        )

        cr = self._sheet(doc, sheet_name).getCellRangeByPosition(
            col, row, col + num_cols - 1, row + num_rows - 1
        )

        if not has_formulas:
            cr.setDataArray(tuple(tuple(r) for r in padded))
        else:
            sheet = self._sheet(doc, sheet_name)
            for r_idx, row_d in enumerate(padded):
                for c_idx, cell_val in enumerate(row_d):
                    cell = sheet.getCellByPosition(col + c_idx, row + r_idx)
                    if isinstance(cell_val, str) and cell_val.startswith("="):
                        cell.setFormula(cell_val)
                    elif isinstance(cell_val, (int, float)):
                        cell.setValue(cell_val)
                    elif cell_val == "" or cell_val is None:
                        cell.setString("")
                    else:
                        cell.setString(str(cell_val))

    def get_used_range(self, doc, sheet_name: str) -> dict:
        sheet = self._sheet(doc, sheet_name)
        cursor = sheet.createCursor()
        cursor.gotoStartOfUsedArea(False)
        cursor.gotoEndOfUsedArea(True)
        addr = cursor.getRangeAddress()
        return {
            "range": _range_addr_to_str(addr),
            "data": [list(r) for r in cursor.getDataArray()],
            "formulas": [list(r) for r in cursor.getFormulaArray()],
        }

    # -- rows / columns ------------------------------------------------------

    def insert_rows(self, doc, sheet_name: str, start_row: int, count: int = 1):
        """Insert *count* blank rows before *start_row* (1-based)."""
        self._sheet(doc, sheet_name).getRows().insertByIndex(start_row - 1, count)

    def delete_rows(self, doc, sheet_name: str, start_row: int, count: int = 1):
        """Delete *count* rows starting at *start_row* (1-based)."""
        self._sheet(doc, sheet_name).getRows().removeByIndex(start_row - 1, count)

    def insert_columns(self, doc, sheet_name: str, start_col: str, count: int = 1):
        """Insert *count* blank columns before *start_col* (letter, e.g. 'B')."""
        idx = _col_to_index(start_col)
        self._sheet(doc, sheet_name).getColumns().insertByIndex(idx, count)

    def delete_columns(self, doc, sheet_name: str, start_col: str, count: int = 1):
        """Delete *count* columns starting at *start_col* (letter)."""
        idx = _col_to_index(start_col)
        self._sheet(doc, sheet_name).getColumns().removeByIndex(idx, count)

    # -- styling -------------------------------------------------------------

    def style_range(
        self,
        doc,
        sheet_name: str,
        range_addr: str,
        bold: bool | None = None,
        italic: bool | None = None,
        font_size: float | None = None,
        font_name: str | None = None,
        color: str | int | None = None,
        background: str | int | None = None,
        align: str | None = None,
        valign: str | None = None,
        wrap: bool | None = None,
        underline: bool | None = None,
        strikethrough: bool | None = None,
    ):
        """Apply visual style properties to all cells in *range_addr*.

        Only the keyword arguments that are explicitly provided are changed;
        omitted arguments leave the existing cell style untouched.
        """
        col1, row1, col2, row2 = _parse_range(range_addr)
        cr = self._sheet(doc, sheet_name).getCellRangeByPosition(
            col1, row1, col2, row2
        )
        _H_ALIGN = {"standard": 0, "left": 1, "center": 2, "right": 3,
                    "justify": 4, "block": 4}
        _V_ALIGN = {"standard": 0, "top": 1, "middle": 2, "center": 2, "bottom": 3}

        if bold is not None:
            cr.CharWeight = 150.0 if bold else 100.0
        if italic is not None:
            cr.CharPosture = 2 if italic else 0
        if font_size is not None:
            cr.CharHeight = float(font_size)
        if font_name is not None:
            cr.CharFontName = str(font_name)
        if color is not None:
            cr.CharColor = _parse_color(color)
        if background is not None:
            cr.CellBackColor = _parse_color(background)
        if align is not None:
            cr.HoriJustify = _H_ALIGN.get(align.lower(), 0)
        if valign is not None:
            cr.VertJustify = _V_ALIGN.get(valign.lower(), 0)
        if wrap is not None:
            cr.IsTextWrapped = bool(wrap)
        if underline is not None:
            cr.CharUnderline = 1 if underline else 0
        if strikethrough is not None:
            cr.CharStrikeout = 1 if strikethrough else 0

    def set_column_width(
        self, doc, sheet_name: str, col: str, width_mm: float | None = None
    ):
        """Set column *col* width to *width_mm* mm. Pass None for auto-fit."""
        column = self._sheet(doc, sheet_name).getColumns().getByIndex(
            _col_to_index(col)
        )
        if width_mm is None:
            column.OptimalWidth = True
        else:
            column.Width = int(width_mm * 100)

    def set_row_height(
        self, doc, sheet_name: str, row: int, height_mm: float | None = None
    ):
        """Set *row* (1-based) height to *height_mm* mm. Pass None for auto-fit."""
        row_obj = self._sheet(doc, sheet_name).getRows().getByIndex(row - 1)
        if height_mm is None:
            row_obj.OptimalHeight = True
        else:
            row_obj.Height = int(height_mm * 100)

    def set_range_border(
        self,
        doc,
        sheet_name: str,
        range_addr: str,
        style: str = "thin",
        sides: str = "all",
        color: str | int = "#000000",
    ):
        """Apply a border to *range_addr*.

        *style*: 'thin', 'medium', 'thick', 'double', 'none'
        *sides*: 'all', 'outer', 'inner', or any combination of
                 'top', 'bottom', 'left', 'right', 'horizontal', 'vertical'
                 separated by spaces or commas.
        *color*: '#RRGGBB' string or integer.
        """
        from com.sun.star.table import TableBorder2  # noqa: PLC0415
        col1, row1, col2, row2 = _parse_range(range_addr)
        cr = self._sheet(doc, sheet_name).getCellRangeByPosition(
            col1, row1, col2, row2
        )
        color_int = _parse_color(color)
        bl = _make_border_line(style, color_int)
        no_bl = _make_border_line("none", 0)

        ss = {s.strip().lower() for s in re.split(r"[,\s]+", sides) if s.strip()}
        do_all = "all" in ss
        do_outer = do_all or "outer" in ss
        do_inner = do_all or "inner" in ss

        tb = TableBorder2()
        tb.TopLine        = bl if (do_outer or "top"        in ss) else no_bl
        tb.BottomLine     = bl if (do_outer or "bottom"     in ss) else no_bl
        tb.LeftLine       = bl if (do_outer or "left"       in ss) else no_bl
        tb.RightLine      = bl if (do_outer or "right"      in ss) else no_bl
        tb.HorizontalLine = bl if (do_inner or "horizontal" in ss) else no_bl
        tb.VerticalLine   = bl if (do_inner or "vertical"   in ss) else no_bl
        tb.IsTopLineValid = tb.IsBottomLineValid = tb.IsLeftLineValid = True
        tb.IsRightLineValid = tb.IsHorizontalLineValid = tb.IsVerticalLineValid = True
        cr.TableBorder2 = tb

    def merge_cells(self, doc, sheet_name: str, range_addr: str):
        """Merge all cells in *range_addr* into one."""
        col1, row1, col2, row2 = _parse_range(range_addr)
        self._sheet(doc, sheet_name).getCellRangeByPosition(
            col1, row1, col2, row2
        ).merge(True)

    def unmerge_cells(self, doc, sheet_name: str, range_addr: str):
        """Unmerge a previously merged range."""
        col1, row1, col2, row2 = _parse_range(range_addr)
        self._sheet(doc, sheet_name).getCellRangeByPosition(
            col1, row1, col2, row2
        ).merge(False)

    def set_number_format(self, doc, sheet_name: str, range_addr: str, fmt: str):
        """Apply a number format string to *range_addr*.

        Examples: '#,##0.00', '0%', 'DD/MM/YYYY', '"$"#,##0.00'.
        """
        from com.sun.star.lang import Locale  # noqa: PLC0415
        col1, row1, col2, row2 = _parse_range(range_addr)
        cr = self._sheet(doc, sheet_name).getCellRangeByPosition(
            col1, row1, col2, row2
        )
        formats = doc.getNumberFormats()
        locale = Locale()
        key = formats.queryKey(fmt, locale, False)
        if key == -1:
            key = formats.addNew(fmt, locale)
        cr.NumberFormat = key
