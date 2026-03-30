"""Comprehensive tests for CalcBridge and the MCP server tools."""
import sys
import os
import tempfile
import traceback

# ---- helper ---------------------------------------------------------------

passed = failed = 0

def check(label, got, expected=None, *, contains=None, truthy=False):
    global passed, failed
    ok = True
    if expected is not None and got != expected:
        ok = False
    if contains is not None and contains not in str(got):
        ok = False
    if truthy and not got:
        ok = False
    if ok:
        print(f"  PASS  {label}")
        passed += 1
    else:
        exp_str = f"expected={expected!r}" if expected is not None else ""
        cnt_str = f"contains={contains!r}" if contains is not None else ""
        print(f"  FAIL  {label}  got={got!r}  {exp_str}{cnt_str}")
        failed += 1

def section(name):
    print(f"\n=== {name} ===")

# ---- setup ----------------------------------------------------------------

from calc_bridge import CalcBridge, _parse_address, _parse_range, _col_to_index, _index_to_col

# ---- unit tests for helpers -----------------------------------------------

section("Address helpers")
check("A→0",  _col_to_index("A"), 0)
check("Z→25", _col_to_index("Z"), 25)
check("AA→26",_col_to_index("AA"), 26)
check("AZ→51",_col_to_index("AZ"), 51)
check("BA→52",_col_to_index("BA"), 52)
check("0→A",  _index_to_col(0), "A")
check("25→Z", _index_to_col(25), "Z")
check("26→AA",_index_to_col(26), "AA")
check("parse A1",   _parse_address("A1"),   (0, 0))
check("parse B3",   _parse_address("B3"),   (1, 2))
check("parse AA1",  _parse_address("AA1"),  (26, 0))
check("parse a1 lc",_parse_address("a1"),   (0, 0))
check("range A1:C3",_parse_range("A1:C3"),  (0, 0, 2, 2))
check("range A1",   _parse_range("A1"),     (0, 0, 0, 0))
check("range B2:B2",_parse_range("B2:B2"),  (1, 1, 1, 1))

# invalid address
try:
    _parse_address("123")
    check("invalid address raises", False, True)
except ValueError:
    check("invalid address raises", True, True)

# ---- live UNO tests -------------------------------------------------------

section("CalcBridge connection")
bridge = CalcBridge(headless=True)
bridge.connect()
check("connected", bridge._ctx is not None, True)
check("desktop exists", bridge._desktop is not None, True)

# ---- create & basic cell ops ----------------------------------------------

section("Create document & cell operations")
doc = bridge.create_document()
check("doc created", doc is not None, True)
check("sheets list", bridge.list_sheets(doc), ["Sheet1"])

bridge.set_cell(doc, "Sheet1", "A1", value="Hello")
bridge.set_cell(doc, "Sheet1", "B1", value=42)
bridge.set_cell(doc, "Sheet1", "B2", value=3.14)
bridge.set_cell(doc, "Sheet1", "C1", formula="=B1*2")

r = bridge.get_cell(doc, "Sheet1", "A1")
check("text cell value",   r["value"], "Hello")
check("text cell formula", r["formula"], "Hello")

r = bridge.get_cell(doc, "Sheet1", "B1")
check("int cell value", r["value"], 42.0)

r = bridge.get_cell(doc, "Sheet1", "B2")
check("float cell value", r["value"], 3.14)

r = bridge.get_cell(doc, "Sheet1", "C1")
check("formula cell formula", r["formula"], "=B1*2")
check("formula cell value",   r["value"],   84.0)

# empty cell
r = bridge.get_cell(doc, "Sheet1", "Z99")
check("empty cell value", r["value"], None)

# clear a cell
bridge.set_cell(doc, "Sheet1", "A1", value=None)
r = bridge.get_cell(doc, "Sheet1", "A1")
check("cleared cell", r["value"], None)

# string formula
bridge.set_cell(doc, "Sheet1", "D1", formula='="foo"&"bar"')
r = bridge.get_cell(doc, "Sheet1", "D1")
check("string formula value", r["value"], "foobar")

# ---- range ops ------------------------------------------------------------

section("Range operations")
data_in = [
    ["Name",  "Score", "Grade"],
    ["Alice",  95,     "A"],
    ["Bob",    73,     "C"],
    ["Carol",  88,     "B"],
]
bridge.set_range(doc, "Sheet1", "A1", data_in)
r = bridge.get_range(doc, "Sheet1", "A1:C4")
check("range rows",  len(r["data"]), 4)
check("range cols",  len(r["data"][0]), 3)
check("range [0][0]",r["data"][0][0], "Name")
check("range [1][1]",r["data"][1][1], 95.0)
check("range [3][2]",r["data"][3][2], "B")
check("range addr",  r["range"], "A1:C4")

# set_range with ragged rows (shorter rows get padded)
bridge.set_range(doc, "Sheet1", "E1", [[1, 2], [3]])
r = bridge.get_range(doc, "Sheet1", "E1:F2")
check("ragged [0]", r["data"][0], [1.0, 2.0])
check("ragged [1]", r["data"][1], [3.0, ""])

# get_used_range
bridge.set_cell(doc, "Sheet1", "A5", formula="=SUM(B2:B4)")
u = bridge.get_used_range(doc, "Sheet1")
check("used range", u["range"].startswith("A1"), True, truthy=True)
check("used data non-empty", len(u["data"]) > 0, True)

# ---- sheet management -----------------------------------------------------

section("Sheet management")
bridge.add_sheet(doc, "Sheet2")
bridge.add_sheet(doc, "Sheet3", position=1)
sheets = bridge.list_sheets(doc)
check("add sheet count", len(sheets), 3)
check("insert at pos 1", sheets[1], "Sheet3")

bridge.rename_sheet(doc, "Sheet2", "Data")
sheets = bridge.list_sheets(doc)
check("rename", "Data" in sheets, True)
check("old name gone", "Sheet2" not in sheets, True)

bridge.remove_sheet(doc, "Sheet3")
sheets = bridge.list_sheets(doc)
check("remove sheet", "Sheet3" not in sheets, True)
check("count after remove", len(sheets), 2)

# ---- row/column operations ------------------------------------------------

section("Row and column operations")
bridge.set_range(doc, "Sheet1", "A10", [
    ["Row10A", "Row10B"],
    ["Row11A", "Row11B"],
    ["Row12A", "Row12B"],
])

bridge.insert_rows(doc, "Sheet1", 11)  # insert before row 11
bridge.set_cell(doc, "Sheet1", "A11", value="INSERTED")
r = bridge.get_range(doc, "Sheet1", "A10:B13")
check("row insert A10 preserved", r["data"][0][0], "Row10A")
check("row inserted at 11",       r["data"][1][0], "INSERTED")
check("row 12 shifted",           r["data"][2][0], "Row11A")

bridge.delete_rows(doc, "Sheet1", 11)  # remove the inserted row
r = bridge.get_range(doc, "Sheet1", "A10:B12")
check("row delete restores",      r["data"][1][0], "Row11A")

bridge.insert_columns(doc, "Sheet1", "B")
bridge.set_cell(doc, "Sheet1", "B10", value="INSERTED_COL")
r = bridge.get_range(doc, "Sheet1", "A10:C10")
check("col insert preserves A",   r["data"][0][0], "Row10A")
check("col inserted at B",        r["data"][0][1], "INSERTED_COL")
check("old B shifted to C",       r["data"][0][2], "Row10B")

bridge.delete_columns(doc, "Sheet1", "B")
r = bridge.get_range(doc, "Sheet1", "A10:B10")
check("col delete restores B",    r["data"][0][1], "Row10B")

# ---- save & open ----------------------------------------------------------

section("Save and re-open")
with tempfile.TemporaryDirectory(dir=os.path.expanduser("~")) as tmp:
    ods_path = os.path.join(tmp, "test.ods")
    xlsx_path = os.path.join(tmp, "test.xlsx")

    # populate fresh doc
    doc2 = bridge.create_document()
    bridge.set_cell(doc2, "Sheet1", "A1", value="Persist")
    bridge.set_cell(doc2, "Sheet1", "B1", value=999)
    bridge.set_cell(doc2, "Sheet1", "C1", formula="=B1+1")

    bridge.save_document(doc2, ods_path)
    check("ods saved", os.path.exists(ods_path), True)

    bridge.save_document(doc2, xlsx_path)
    check("xlsx saved", os.path.exists(xlsx_path), True)
    bridge.close_document(doc2)

    # reopen ods
    doc3 = bridge.open_document(ods_path)
    check("ods reopened", doc3 is not None, True)
    r = bridge.get_cell(doc3, "Sheet1", "A1")
    check("ods text preserved", r["value"], "Persist")
    r = bridge.get_cell(doc3, "Sheet1", "B1")
    check("ods number preserved", r["value"], 999.0)
    r = bridge.get_cell(doc3, "Sheet1", "C1")
    check("ods formula preserved", r["formula"], "=B1+1")
    check("ods formula value", r["value"], 1000.0)
    bridge.close_document(doc3)

    # reopen xlsx
    doc4 = bridge.open_document(xlsx_path)
    check("xlsx reopened", doc4 is not None, True)
    r = bridge.get_cell(doc4, "Sheet1", "A1")
    check("xlsx text preserved", r["value"], "Persist")
    bridge.close_document(doc4)

# ---- MCP server tools (via direct calls) ----------------------------------

section("MCP server tools")
# Import server after bridge is already set up to avoid double-starting LO
import server as srv

# Patch bridge to reuse existing connection
srv._bridge = bridge

doc_id = None
try:
    result = srv.create_spreadsheet()
    doc_id = result["doc_id"]
    check("create_spreadsheet doc_id", len(doc_id), 8)
    check("create_spreadsheet sheets", result["sheets"], ["Sheet1"])

    result = srv.set_cell(doc_id, "Sheet1", "A1", value="MCP Test")
    check("set_cell result", "A1" in result, True)

    result = srv.get_cell(doc_id, "Sheet1", "A1")
    check("get_cell value", result["value"], "MCP Test")

    result = srv.set_range(doc_id, "Sheet1", "B1", [[1, 2], [3, 4]])
    check("set_range result", "2×2" in result, True)

    result = srv.get_range(doc_id, "Sheet1", "B1:C2")
    check("get_range data", result["data"], [[1.0, 2.0], [3.0, 4.0]])

    result = srv.set_cell(doc_id, "Sheet1", "D1", formula="=SUM(B1:C2)")
    result = srv.get_cell(doc_id, "Sheet1", "D1")
    check("formula via server", result["value"], 10.0)

    result = srv.add_sheet(doc_id, "New")
    check("add_sheet", "New" in result, True)

    result = srv.list_sheets(doc_id)
    check("list_sheets", result, ["Sheet1", "New"])

    result = srv.rename_sheet(doc_id, "New", "Renamed")
    check("rename_sheet", "Renamed" in result, True)

    result = srv.remove_sheet(doc_id, "Renamed")
    check("remove_sheet", "Renamed" in result, True)

    result = srv.get_used_range(doc_id, "Sheet1")
    check("get_used_range", result["range"].startswith("A"), True)

    result = srv.insert_rows(doc_id, "Sheet1", 1)
    check("insert_rows", "inserted" in result, True)

    result = srv.delete_rows(doc_id, "Sheet1", 1)
    check("delete_rows", "deleted" in result, True)

    result = srv.insert_columns(doc_id, "Sheet1", "A")
    check("insert_columns", "inserted" in result, True)

    result = srv.delete_columns(doc_id, "Sheet1", "A")
    check("delete_columns", "deleted" in result, True)

    with tempfile.TemporaryDirectory(dir=os.path.expanduser("~")) as tmp_srv:
        tmp_path = os.path.join(tmp_srv, "save_test.ods")
        result = srv.save_spreadsheet(doc_id, tmp_path)
        check("save_spreadsheet", result, "saved")
        check("file written", os.path.exists(tmp_path), True)

    # open via server
    with tempfile.TemporaryDirectory(dir=os.path.expanduser("~")) as tmp:
        p = os.path.join(tmp, "srv.ods")
        bridge.save_document(srv._docs[doc_id], p)
        bridge.close_document(srv._docs[doc_id])
        del srv._docs[doc_id]
        doc_id = None

        r2 = srv.open_spreadsheet(p)
        doc_id = r2["doc_id"]
        check("open_spreadsheet", len(doc_id), 8)

    result = srv.close_spreadsheet(doc_id)
    doc_id = None
    check("close_spreadsheet", result, "closed")

except Exception:
    traceback.print_exc()
    if doc_id and doc_id in srv._docs:
        bridge.close_document(srv._docs[doc_id])
        del srv._docs[doc_id]

# ---- error handling -------------------------------------------------------

section("Error handling")
try:
    srv.get_cell("bad_id", "Sheet1", "A1")
    check("bad doc_id raises", False, True)
except (ValueError, RuntimeError):
    check("bad doc_id raises", True, True)

try:
    _parse_address("notanaddress!")
    check("bad address raises", False, True)
except ValueError:
    check("bad address raises", True, True)

# ---- cleanup & summary ----------------------------------------------------

bridge.close_document(doc)
bridge.shutdown()

print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
