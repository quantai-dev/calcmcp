"""Open-WebUI style tool for LibreOffice Calc — column widths, row heights,
fonts, colors, borders, number formats, and cell merging.

This tool shares the CalcBridge instance and open-document registry with
open_webui_tool.py. Both tools must be installed and use the same
CALCMCP_PATH valve so they operate on the same LibreOffice session.

Installation:
  1. Install open_webui_tool.py first (it owns the bridge + doc registry).
  2. Copy this file into Open-WebUI → Workspace → Tools → Create tool.
  3. Set CALCMCP_PATH to the same directory used by open_webui_tool.py.
"""

import builtins as _builtins
import os
import sys
from typing import Optional

from pydantic import BaseModel, Field


def _get_shared_state(path: str, headless: bool):
    """Return (bridge, docs) from the process-global state store.

    Uses builtins._calcmcp so the same bridge and doc registry are shared with
    open_webui_tool regardless of how Open-WebUI loads each tool file.
    """
    _calcmcp = getattr(_builtins, '_calcmcp', None)
    if _calcmcp is None or _calcmcp.get('bridge') is None:
        # Main tool hasn't initialised yet — bootstrap it now.
        if path and path not in sys.path:
            sys.path.insert(0, path)
        tool_dir = os.path.dirname(os.path.abspath(__file__))
        if tool_dir not in sys.path:
            sys.path.insert(0, tool_dir)
        import open_webui_tool as _owt  # noqa: PLC0415
        _owt._get_bridge(path, headless)
        _calcmcp = _builtins._calcmcp

    return _calcmcp['bridge'], _calcmcp['docs']


class Tools:
    class Valves(BaseModel):
        CALCMCP_PATH: str = Field(
            default="/home/ethan/Projects/calcmcp",
            description=(
                "Absolute path to the directory containing calc_bridge.py. "
                "Must match the value set in open_webui_tool.py."
            ),
        )
        CALCMCP_HEADLESS: bool = Field(
            default=False,
            description="Run LibreOffice without a visible window.",
        )

    def __init__(self):
        self.valves = self.Valves()

    def _state(self):
        return _get_shared_state(
            self.valves.CALCMCP_PATH, self.valves.CALCMCP_HEADLESS
        )

    def _b(self):
        bridge, _ = self._state()
        return bridge

    def _require_doc(self, doc_id: str):
        _, docs = self._state()
        if doc_id not in docs:
            raise ValueError(
                f"Unknown doc_id {doc_id!r}. "
                "Call create_spreadsheet or open_spreadsheet first."
            )
        return docs[doc_id]

    def reset_bridge(self) -> str:
        """Reload the CalcBridge module and restart the LibreOffice connection.

        Call this after updating either tool's code so new methods become
        available without restarting Open-WebUI. Delegates to open_webui_tool.
        """
        try:
            import open_webui_tool as _owt  # noqa: PLC0415
            t = _owt.Tools()
            t.valves.CALCMCP_PATH = self.valves.CALCMCP_PATH
            t.valves.CALCMCP_HEADLESS = self.valves.CALCMCP_HEADLESS
            return t.reset_bridge()
        except Exception as e:
            return f"Error: {e}"

    # -----------------------------------------------------------------------
    # Cell / range styles
    # -----------------------------------------------------------------------

    def style_range(
        self,
        doc_id: str,
        sheet: str,
        range_address: str,
        bold: Optional[bool] = None,
        italic: Optional[bool] = None,
        font_size: Optional[float] = None,
        font_name: Optional[str] = None,
        color: Optional[str] = None,
        background: Optional[str] = None,
        align: Optional[str] = None,
        valign: Optional[str] = None,
        wrap: Optional[bool] = None,
        underline: Optional[bool] = None,
        strikethrough: Optional[bool] = None,
    ) -> str:
        """Apply visual styles to a range of cells.

        Only the arguments you supply are changed; omitted ones leave the
        existing style untouched. range_address may be a single cell ('A1')
        or a range ('A1:D4').

        Args:
            doc_id: Document ID from create_spreadsheet or open_spreadsheet.
            sheet: Sheet name, e.g. 'Sheet1'.
            range_address: Cell or range in A1 notation.
            bold: True to bold, False to remove bold.
            italic: True to italicise, False to remove.
            font_size: Point size, e.g. 12.
            font_name: Font family name, e.g. 'Arial'.
            color: Text colour as '#RRGGBB', e.g. '#FF0000'.
            background: Cell background colour as '#RRGGBB'.
            align: Horizontal alignment — 'left', 'center', 'right', 'justify'.
            valign: Vertical alignment — 'top', 'middle', 'bottom'.
            wrap: True to enable text wrapping.
            underline: True to underline.
            strikethrough: True to strike through.
        """
        try:
            self._b().style_range(
                self._require_doc(doc_id), sheet, range_address,
                bold=bold, italic=italic, font_size=font_size,
                font_name=font_name, color=color, background=background,
                align=align, valign=valign, wrap=wrap,
                underline=underline, strikethrough=strikethrough,
            )
            return f"styled {range_address}"
        except Exception as e:
            return f"Error: {e}"

    # -----------------------------------------------------------------------
    # Column and row dimensions
    # -----------------------------------------------------------------------

    def set_column_width(
        self,
        doc_id: str,
        sheet: str,
        col: str,
        width_mm: Optional[float] = None,
    ) -> str:
        """Set the width of a column.

        Args:
            doc_id: Document ID.
            sheet: Sheet name.
            col: Column letter, e.g. 'A' or 'BC'.
            width_mm: Width in millimetres. Omit for auto-fit.
        """
        try:
            self._b().set_column_width(
                self._require_doc(doc_id), sheet, col, width_mm
            )
            label = f"{width_mm} mm" if width_mm is not None else "auto"
            return f"column {col} width → {label}"
        except Exception as e:
            return f"Error: {e}"

    def set_row_height(
        self,
        doc_id: str,
        sheet: str,
        row: int,
        height_mm: Optional[float] = None,
    ) -> str:
        """Set the height of a row.

        Args:
            doc_id: Document ID.
            sheet: Sheet name.
            row: 1-based row number.
            height_mm: Height in millimetres. Omit for auto-fit.
        """
        try:
            self._b().set_row_height(
                self._require_doc(doc_id), sheet, row, height_mm
            )
            label = f"{height_mm} mm" if height_mm is not None else "auto"
            return f"row {row} height → {label}"
        except Exception as e:
            return f"Error: {e}"

    # -----------------------------------------------------------------------
    # Borders
    # -----------------------------------------------------------------------

    def set_range_border(
        self,
        doc_id: str,
        sheet: str,
        range_address: str,
        style: str = "thin",
        sides: str = "all",
        color: str = "#000000",
    ) -> str:
        """Apply a border to a range of cells.

        Args:
            doc_id: Document ID.
            sheet: Sheet name.
            range_address: Cell or range in A1 notation.
            style: Border line style — 'thin', 'medium', 'thick', 'double',
                   or 'none' to remove borders.
            sides: Which sides to apply — 'all', 'outer', 'inner', or any
                   combination of 'top', 'bottom', 'left', 'right',
                   'horizontal', 'vertical' separated by spaces or commas.
            color: Border colour as '#RRGGBB'.
        """
        try:
            self._b().set_range_border(
                self._require_doc(doc_id), sheet, range_address,
                style=style, sides=sides, color=color,
            )
            return f"border ({style}, {sides}) applied to {range_address}"
        except Exception as e:
            return f"Error: {e}"

    # -----------------------------------------------------------------------
    # Cell merging
    # -----------------------------------------------------------------------

    def merge_cells(self, doc_id: str, sheet: str, range_address: str) -> str:
        """Merge all cells in a range into one cell.

        Args:
            doc_id: Document ID.
            sheet: Sheet name.
            range_address: Range to merge, e.g. 'A1:C1'.
        """
        try:
            self._b().merge_cells(self._require_doc(doc_id), sheet, range_address)
            return f"{range_address} merged"
        except Exception as e:
            return f"Error: {e}"

    def unmerge_cells(self, doc_id: str, sheet: str, range_address: str) -> str:
        """Unmerge a previously merged range.

        Args:
            doc_id: Document ID.
            sheet: Sheet name.
            range_address: Range to unmerge.
        """
        try:
            self._b().unmerge_cells(self._require_doc(doc_id), sheet, range_address)
            return f"{range_address} unmerged"
        except Exception as e:
            return f"Error: {e}"

    # -----------------------------------------------------------------------
    # Number formats
    # -----------------------------------------------------------------------

    def set_number_format(
        self,
        doc_id: str,
        sheet: str,
        range_address: str,
        fmt: str,
    ) -> str:
        """Apply a number format string to a range.

        Args:
            doc_id: Document ID.
            sheet: Sheet name.
            range_address: Cell or range in A1 notation.
            fmt: LibreOffice number format code. Examples:
                 '#,##0.00'       — two decimal places with thousands separator
                 '0%'             — percentage
                 '"$"#,##0.00'    — US dollar
                 'DD/MM/YYYY'     — date
                 'HH:MM:SS'       — time
                 '@'              — force text
        """
        try:
            self._b().set_number_format(
                self._require_doc(doc_id), sheet, range_address, fmt
            )
            return f"number format {fmt!r} applied to {range_address}"
        except Exception as e:
            return f"Error: {e}"
