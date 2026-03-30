"""Open-WebUI tool for LibreOffice Calc via CalcBridge.

Usage rules:
  - Call create_spreadsheet or open_spreadsheet ONCE to get a doc_id.
  - Reuse that doc_id for ALL subsequent operations in the conversation.
  - Never call create_spreadsheet again mid-conversation unless the user
    explicitly asks for a brand-new separate document.

Installation:
  1. Copy this file into Open-WebUI → Workspace → Tools → Create tool.
  2. Set CALCMCP_PATH to the directory containing calc_bridge.py.
  3. LibreOffice starts headless on first use and stays alive for the
     duration of the Open-WebUI server process.
"""

import builtins as _builtins
import os
import sys
import uuid
from typing import Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Process-global shared state — stored in builtins so it is the same object
# regardless of how Open-WebUI loads each tool file (exec, importlib, etc.).
# ---------------------------------------------------------------------------
if not hasattr(_builtins, '_calcmcp'):
    _builtins._calcmcp = {'bridge': None, 'docs': {}}

_docs: dict = _builtins._calcmcp['docs']


def _new_id() -> str:
    return str(uuid.uuid4())[:8]


def _get_bridge(path: str, headless: bool):
    """Lazily initialise and return the shared CalcBridge."""
    _calcmcp = _builtins._calcmcp
    _bridge = _calcmcp['bridge']

    # Re-use existing bridge unless the headless setting changed.
    if _bridge is not None and _bridge._headless == headless:
        return _bridge

    # Locate the LibreOffice snap program directory.
    for candidate in (
        "/snap/libreoffice/current/lib/libreoffice/program",
        "/snap/libreoffice/366/lib/libreoffice/program",
    ):
        if os.path.isdir(candidate):
            lo_program = candidate
            break
    else:
        lo_program = None

    # Set UNO env vars *before* importing calc_bridge / uno.
    # URE_BOOTSTRAP must be present so that createInstanceWithContext can
    # deserialise returned object references without disposing the bridge.
    if lo_program:
        os.environ["URE_BOOTSTRAP"] = (
            f"vnd.sun.star.pathname:{lo_program}/fundamentalrc"
        )
        os.environ["UNO_PATH"] = lo_program
        if lo_program not in sys.path:
            sys.path.insert(0, lo_program)

    if path and path not in sys.path:
        sys.path.insert(0, path)

    from calc_bridge import CalcBridge  # noqa: PLC0415

    if _bridge is not None:
        # Settings changed — shut down the old bridge gracefully.
        try:
            _bridge.shutdown()
        except Exception:
            pass

    _bridge = CalcBridge(headless=headless)
    _calcmcp['bridge'] = _bridge
    return _bridge


# ---------------------------------------------------------------------------


class Tools:
    class Valves(BaseModel):
        CALCMCP_PATH: str = Field(
            default="/home/ethan/Projects/calcmcp",
            description=(
                "Absolute path to the directory containing calc_bridge.py."
            ),
        )
        CALCMCP_HEADLESS: bool = Field(
            default=False,
            description=(
                "Run LibreOffice without a visible window. "
                "Recommended for server / Open-WebUI environments."
            ),
        )

    def __init__(self):
        self.valves = self.Valves()

    def _b(self):
        return _get_bridge(self.valves.CALCMCP_PATH, self.valves.CALCMCP_HEADLESS)

    def reset_bridge(self) -> str:
        """Shut down the current LibreOffice connection and clear all open docs.

        Call this after changing the CALCMCP_HEADLESS valve, or after updating
        the tool code, so the new version takes effect without restarting
        Open-WebUI. The next tool call will start a fresh LibreOffice instance.
        """
        import importlib  # noqa: PLC0415
        _calcmcp = _builtins._calcmcp
        if _calcmcp['bridge'] is not None:
            try:
                _calcmcp['bridge'].shutdown()
            except Exception:
                pass
            _calcmcp['bridge'] = None
        _calcmcp['docs'].clear()
        # Reload calc_bridge so any newly added methods become available
        # without requiring a full Open-WebUI restart.
        if "calc_bridge" in sys.modules:
            importlib.reload(sys.modules["calc_bridge"])
        return (
            f"Bridge reset. Next call will start LibreOffice "
            f"(headless={self.valves.CALCMCP_HEADLESS})."
        )

    def diagnose(self) -> str:
        """Run a connectivity self-test and return diagnostic info.

        Call this first if create_spreadsheet is failing. It reports the
        Python interpreter, snap paths, env vars, UNO import status, and
        whether CalcBridge can connect to LibreOffice.
        """
        import traceback
        lines = [f"Python: {sys.executable}"]

        snap_paths = [
            "/snap/libreoffice/current/lib/libreoffice/program",
            "/snap/libreoffice/366/lib/libreoffice/program",
        ]
        for p in snap_paths:
            lines.append(f"  {p}: {'OK' if os.path.isdir(p) else 'MISSING'}")

        for var in ("URE_BOOTSTRAP", "UNO_PATH", "DISPLAY", "HOME"):
            lines.append(f"{var}={os.environ.get(var, '(not set)')}")

        try:
            import uno  # noqa: PLC0415
            lines.append(f"uno: {uno.__file__}")
        except Exception as e:
            lines.append(f"uno import FAILED: {e}")

        try:
            # Reset first so we get a fresh bridge with the current code.
            self.reset_bridge()
            b = _get_bridge(self.valves.CALCMCP_PATH, self.valves.CALCMCP_HEADLESS)
            b.ensure_connected()
            lines.append(f"connect: OK  ctx={b._ctx is not None}  desktop={b._desktop is not None}")
            doc = b.create_document()
            lines.append(f"create_document: OK  doc={doc is not None}")
            b.close_document(doc)
            lines.append("close_document: OK")
        except Exception as e:
            lines.append(f"FAILED: {e}")
            lines.append(traceback.format_exc())

        return "\n".join(lines)

    def _require_doc(self, doc_id: str):
        if doc_id not in _docs:
            raise ValueError(
                f"Unknown doc_id {doc_id!r}. Call create_spreadsheet or "
                "open_spreadsheet first."
            )
        return _docs[doc_id]

    # -----------------------------------------------------------------------
    # Document management
    # -----------------------------------------------------------------------

    def create_spreadsheet(self) -> str:
        """Create a new blank LibreOffice Calc spreadsheet in memory.

        IMPORTANT: Only call this when the user explicitly asks to create a
        NEW spreadsheet. If a doc_id was already returned earlier in this
        conversation, use that doc_id for all further operations — do NOT
        call this again. Creating a second spreadsheet abandons the first.

        Returns a doc_id string that must be passed to every subsequent
        operation on this document. The document exists only in memory
        until save_spreadsheet is called.
        """
        try:
            doc = self._b().create_document()
            doc_id = _new_id()
            _docs[doc_id] = doc
            sheets = self._b().list_sheets(doc)
            return (
                f"Spreadsheet created.\n"
                f"doc_id: {doc_id}\n"
                f"Sheets: {sheets}"
            )
        except Exception as e:
            return f"Error: {e}"

    def open_spreadsheet(self, path: str) -> str:
        """Open an existing spreadsheet file from disk and return its doc_id.

        IMPORTANT: Only call this to open a file that exists on disk. If a
        doc_id is already known from earlier in this conversation, use that
        doc_id directly — do NOT call this again.

        Args:
            path: Absolute path to the file (.ods, .xlsx, .xls, .csv).

        Returns the doc_id used by all subsequent operations.
        """
        try:
            doc = self._b().open_document(path)
            doc_id = _new_id()
            _docs[doc_id] = doc
            sheets = self._b().list_sheets(doc)
            return (
                f"Opened: {path}\n"
                f"doc_id: {doc_id}\n"
                f"Sheets: {sheets}"
            )
        except Exception as e:
            return f"Error: {e}"

    def save_spreadsheet(self, doc_id: str, path: Optional[str] = None) -> str:
        """Save a spreadsheet to disk.

        Args:
            doc_id: The doc_id returned by create_spreadsheet or open_spreadsheet.
            path: Absolute path to save to. File extension sets the format:
                  .ods, .xlsx, .xls, .csv. Omit to save in place (document
                  must have been opened from a file).
        """
        try:
            self._b().save_document(self._require_doc(doc_id), path)
            return f"Saved: {path or '(in place)'}"
        except Exception as e:
            return f"Error: {e}"

    def close_spreadsheet(self, doc_id: str, save: bool = False) -> str:
        """Close a spreadsheet and free its memory.

        Args:
            doc_id: The doc_id of the spreadsheet to close.
            save: If true, save before closing. Only works when the document
                  was previously saved to a file (save_spreadsheet with a path
                  was called at least once). For in-memory documents created
                  with create_spreadsheet, call save_spreadsheet(doc_id,
                  path=...) first, then close with save=False.
        """
        try:
            self._b().close_document(self._require_doc(doc_id), save=save)
            del _docs[doc_id]
            return "Closed."
        except Exception as e:
            return f"Error: {e}"

    # -----------------------------------------------------------------------
    # Sheet management
    # -----------------------------------------------------------------------

    def list_sheets(self, doc_id: str) -> str:
        """Return the names of all sheets in the spreadsheet.

        Args:
            doc_id: The doc_id of the spreadsheet.
        """
        try:
            sheets = self._b().list_sheets(self._require_doc(doc_id))
            return f"Sheets: {sheets}"
        except Exception as e:
            return f"Error: {e}"

    def add_sheet(self, doc_id: str, name: str, position: int = -1) -> str:
        """Add a new sheet to the spreadsheet.

        Args:
            doc_id: The doc_id of the spreadsheet.
            name: Name for the new sheet.
            position: 0-based insert position. -1 (default) appends at the end.
        """
        try:
            self._b().add_sheet(self._require_doc(doc_id), name, position)
            return f"sheet '{name}' added"
        except Exception as e:
            return f"Error: {e}"

    def remove_sheet(self, doc_id: str, name: str) -> str:
        """Remove a sheet from the spreadsheet by name.

        Args:
            doc_id: The doc_id of the spreadsheet.
            name: Name of the sheet to remove.
        """
        try:
            self._b().remove_sheet(self._require_doc(doc_id), name)
            return f"sheet '{name}' removed"
        except Exception as e:
            return f"Error: {e}"

    def rename_sheet(self, doc_id: str, old_name: str, new_name: str) -> str:
        """Rename a sheet.

        Args:
            doc_id: The doc_id of the spreadsheet.
            old_name: Current sheet name.
            new_name: New sheet name.
        """
        try:
            self._b().rename_sheet(self._require_doc(doc_id), old_name, new_name)
            return f"renamed '{old_name}' -> '{new_name}'"
        except Exception as e:
            return f"Error: {e}"

    # -----------------------------------------------------------------------
    # Cell I/O
    # -----------------------------------------------------------------------

    def get_cell(self, doc_id: str, sheet: str, address: str) -> str:
        """Read a single cell and return its value and formula.

        Args:
            doc_id: The doc_id of the spreadsheet.
            sheet: Sheet name, e.g. 'Sheet1'.
            address: Cell address in A1 notation, e.g. 'B3'.

        For formula cells, value is the evaluated result.
        For plain values, formula is the raw string content.
        """
        try:
            r = self._b().get_cell(self._require_doc(doc_id), sheet, address)
            return (
                f"Cell {r['address']}\n"
                f"  value:   {r['value']!r}\n"
                f"  formula: {r['formula']!r}"
            )
        except Exception as e:
            return f"Error: {e}"

    def set_cell(
        self,
        doc_id: str,
        sheet: str,
        address: str,
        value: Optional[str] = None,
        formula: Optional[str] = None,
    ) -> str:
        """Write a value or formula to a single cell.

        Args:
            doc_id: The doc_id of the spreadsheet.
            sheet: Sheet name, e.g. 'Sheet1'.
            address: Cell address in A1 notation, e.g. 'B3'.
            value: String or number to set. Omit (or pass null) to clear.
                   Ignored when formula is provided. Numeric strings are
                   converted to numbers automatically.
            formula: Formula string, e.g. '=SUM(A1:A5)'. Takes precedence
                     over value when both are provided.
        """
        try:
            if formula:
                parsed_value = None
            elif value is None:
                parsed_value = None
            else:
                try:
                    parsed_value = int(value) if "." not in str(value) else float(value)
                except (ValueError, TypeError):
                    parsed_value = value
            self._b().set_cell(
                self._require_doc(doc_id), sheet, address,
                value=parsed_value, formula=formula or None,
            )
            return f"{address} set"
        except Exception as e:
            return f"Error: {e}"

    def get_range(self, doc_id: str, sheet: str, range_address: str) -> str:
        """Read a rectangular range of cells, including formula strings.

        Args:
            doc_id: The doc_id of the spreadsheet.
            sheet: Sheet name, e.g. 'Sheet1'.
            range_address: Range in A1:D5 notation, e.g. 'A1:C3'.

        Returns evaluated values and raw formula strings for each row.
        Formula cells show the '=...' expression; plain value cells echo
        their value. Numbers are floats; empty cells are 0 or empty string.
        """
        try:
            r = self._b().get_range(self._require_doc(doc_id), sheet, range_address)
            lines = [f"Range {r['range']}:"]
            for i, (vals, fmls) in enumerate(zip(r["data"], r["formulas"])):
                lines.append(f"  row {i + 1} values:   {vals}")
                lines.append(f"  row {i + 1} formulas: {fmls}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"

    def set_range(
        self,
        doc_id: str,
        sheet: str,
        start_address: str,
        data: list,
    ) -> str:
        """Write a 2-D array of values or formulas starting at start_address.

        Args:
            doc_id: The doc_id of the spreadsheet.
            sheet: Sheet name, e.g. 'Sheet1'.
            start_address: Top-left cell in A1 notation, e.g. 'B2'.
            data: 2-D list of rows. Each row is a list of numbers, strings,
                  or formula strings. Strings starting with '=' are written
                  as formulas. Shorter rows are padded with empty string.
                  Example: [["Name", "Score"], ["Alice", 95],
                             ["Total", "=SUM(B2:B2)"]].
        """
        try:
            # Normalise: wrap a bare string; promote flat rows to single-col lists.
            if isinstance(data, str):
                data = [[data]]
            else:
                data = [list(r) if isinstance(r, (list, tuple)) else [r] for r in data]
            self._b().set_range(self._require_doc(doc_id), sheet, start_address, data)
            rows = len(data)
            cols = max((len(r) for r in data), default=0)
            return f"{rows}×{cols} block written at {start_address}"
        except Exception as e:
            return f"Error: {e}"

    def get_used_range(self, doc_id: str, sheet: str) -> str:
        """Return all data from the used area of a sheet, including formulas.

        Args:
            doc_id: The doc_id of the spreadsheet.
            sheet: Sheet name, e.g. 'Sheet1'.

        Returns the bounding range, evaluated values, and formula strings
        for every row. Useful for reading an entire sheet without knowing
        its dimensions.
        """
        try:
            r = self._b().get_used_range(self._require_doc(doc_id), sheet)
            lines = [f"Used range {r['range']}:"]
            for i, (vals, fmls) in enumerate(zip(r["data"], r["formulas"])):
                lines.append(f"  row {i + 1} values:   {vals}")
                lines.append(f"  row {i + 1} formulas: {fmls}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"

    # -----------------------------------------------------------------------
    # Row / column structural edits
    # -----------------------------------------------------------------------

    def insert_rows(
        self,
        doc_id: str,
        sheet: str,
        start_row: int,
        count: int = 1,
    ) -> str:
        """Insert blank rows before start_row. Existing rows shift down.

        Args:
            doc_id: The doc_id of the spreadsheet.
            sheet: Sheet name.
            start_row: Row number to insert before (1-based; 1 is the first row).
            count: Number of blank rows to insert (default 1).
        """
        try:
            self._b().insert_rows(self._require_doc(doc_id), sheet, start_row, count)
            return f"{count} row(s) inserted before row {start_row}"
        except Exception as e:
            return f"Error: {e}"

    def delete_rows(
        self,
        doc_id: str,
        sheet: str,
        start_row: int,
        count: int = 1,
    ) -> str:
        """Delete rows starting at start_row. Rows below shift up.

        Args:
            doc_id: The doc_id of the spreadsheet.
            sheet: Sheet name.
            start_row: First row to delete (1-based).
            count: Number of rows to delete (default 1).
        """
        try:
            self._b().delete_rows(self._require_doc(doc_id), sheet, start_row, count)
            return f"{count} row(s) deleted from row {start_row}"
        except Exception as e:
            return f"Error: {e}"

    def insert_columns(
        self,
        doc_id: str,
        sheet: str,
        start_col: str,
        count: int = 1,
    ) -> str:
        """Insert blank columns before start_col. Existing columns shift right.

        Args:
            doc_id: The doc_id of the spreadsheet.
            sheet: Sheet name.
            start_col: Column letter to insert before, e.g. 'C'. Supports
                       multi-letter columns like 'AA'.
            count: Number of blank columns to insert (default 1).
        """
        try:
            self._b().insert_columns(self._require_doc(doc_id), sheet, start_col, count)
            return f"{count} column(s) inserted before column {start_col}"
        except Exception as e:
            return f"Error: {e}"

    def delete_columns(
        self,
        doc_id: str,
        sheet: str,
        start_col: str,
        count: int = 1,
    ) -> str:
        """Delete columns starting at start_col. Columns to the right shift left.

        Args:
            doc_id: The doc_id of the spreadsheet.
            sheet: Sheet name.
            start_col: First column to delete, e.g. 'C'. Supports multi-letter
                       columns like 'AA'.
            count: Number of columns to delete (default 1).
        """
        try:
            self._b().delete_columns(self._require_doc(doc_id), sheet, start_col, count)
            return f"{count} column(s) deleted from column {start_col}"
        except Exception as e:
            return f"Error: {e}"
