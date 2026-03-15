"""
Tests for office_automation.py — Office Document Automation

Tests cover:
  - DocType and OperationType enums
  - OperationLog, OperationResult, SheetData dataclasses
  - OfficeClient availability checking
  - Excel operations (read, write, get_sheets)
  - PowerPoint operations (create, read)
  - PDF operations (extract_text, page_count, merge, split)
  - Operation logging
  - Status reporting
  - Error handling (missing files, missing libraries)
  - Thread safety
"""

import os
import sys
import threading
import unittest
from unittest.mock import MagicMock, patch

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from office_automation import (
    DocType,
    OfficeClient,
    OperationLog,
    OperationResult,
    OperationType,
    SheetData,
)


# ---------------------------------------------------------------------------
# Enum Tests
# ---------------------------------------------------------------------------

class TestDocType(unittest.TestCase):
    """Test DocType enum."""

    def test_all_values(self):
        expected = {"excel", "powerpoint", "pdf"}
        actual = {d.value for d in DocType}
        self.assertEqual(actual, expected)


class TestOperationType(unittest.TestCase):
    """Test OperationType enum."""

    def test_all_values(self):
        expected = {"read", "write", "create"}
        actual = {o.value for o in OperationType}
        self.assertEqual(actual, expected)


# ---------------------------------------------------------------------------
# Dataclass Tests
# ---------------------------------------------------------------------------

class TestOperationLog(unittest.TestCase):
    """Test OperationLog dataclass."""

    def test_to_dict(self):
        log = OperationLog(
            timestamp=12345.0,
            doc_type="excel",
            operation="read",
            file_path="/tmp/test.xlsx",
            agent_id="agent1",
            details="Sheet: Sheet1",
        )
        d = log.to_dict()
        self.assertEqual(d["doc_type"], "excel")
        self.assertEqual(d["operation"], "read")
        self.assertEqual(d["file_path"], "/tmp/test.xlsx")
        self.assertEqual(d["agent_id"], "agent1")

    def test_defaults(self):
        log = OperationLog(
            timestamp=0.0, doc_type="pdf",
            operation="read", file_path="/tmp/x.pdf",
        )
        self.assertEqual(log.agent_id, "")
        self.assertEqual(log.details, "")


class TestOperationResult(unittest.TestCase):
    """Test OperationResult dataclass."""

    def test_success(self):
        r = OperationResult(success=True, data={"count": 5})
        d = r.to_dict()
        self.assertTrue(d["success"])
        self.assertEqual(d["data"]["count"], 5)
        self.assertEqual(d["error"], "")

    def test_error(self):
        r = OperationResult(success=False, error="File not found")
        d = r.to_dict()
        self.assertFalse(d["success"])
        self.assertEqual(d["error"], "File not found")

    def test_callable_data(self):
        r = OperationResult(success=True, data=lambda: None)
        d = r.to_dict()
        self.assertIsInstance(d["data"], str)


class TestSheetData(unittest.TestCase):
    """Test SheetData dataclass."""

    def test_to_dict(self):
        sd = SheetData(
            name="Sheet1",
            rows=[[1, 2], [3, 4]],
            headers=["A", "B"],
            row_count=2, col_count=2,
        )
        d = sd.to_dict()
        self.assertEqual(d["name"], "Sheet1")
        self.assertEqual(d["row_count"], 2)
        self.assertEqual(d["col_count"], 2)
        self.assertEqual(len(d["rows"]), 2)

    def test_defaults(self):
        sd = SheetData(name="X")
        self.assertEqual(sd.rows, [])
        self.assertEqual(sd.headers, [])
        self.assertEqual(sd.row_count, 0)


# ---------------------------------------------------------------------------
# Availability Tests
# ---------------------------------------------------------------------------

class TestAvailability(unittest.TestCase):
    """Test format availability checking."""

    def test_available_formats_returns_dict(self):
        client = OfficeClient()
        fmt = client.available_formats()
        self.assertIn("excel", fmt)
        self.assertIn("powerpoint", fmt)
        self.assertIn("pdf", fmt)
        for v in fmt.values():
            self.assertIsInstance(v, bool)


# ---------------------------------------------------------------------------
# Excel Tests (Mocked)
# ---------------------------------------------------------------------------

class TestExcelRead(unittest.TestCase):
    """Test Excel read operations."""

    def setUp(self):
        self.client = OfficeClient()

    @patch("office_automation.HAS_OPENPYXL", False)
    def test_no_openpyxl(self):
        result = self.client.excel_read("/tmp/test.xlsx")
        self.assertFalse(result.success)
        self.assertIn("openpyxl", result.error)

    @patch("office_automation.HAS_OPENPYXL", True)
    def test_file_not_found(self):
        result = self.client.excel_read("/nonexistent/path.xlsx")
        self.assertFalse(result.success)
        self.assertIn("not found", result.error)

    @patch("office_automation.HAS_OPENPYXL", True)
    @patch("office_automation.openpyxl")
    @patch("os.path.exists", return_value=True)
    def test_read_success(self, mock_exists, mock_openpyxl):
        mock_ws = MagicMock()
        mock_ws.title = "Sheet1"
        mock_ws.iter_rows.return_value = [
            ("Name", "Age"),
            ("Alice", 30),
            ("Bob", 25),
        ]
        mock_wb = MagicMock()
        mock_wb.active = mock_ws
        mock_wb.sheetnames = ["Sheet1"]
        mock_openpyxl.load_workbook.return_value = mock_wb

        result = self.client.excel_read("/tmp/test.xlsx", agent_id="a1")
        self.assertTrue(result.success)
        self.assertIsInstance(result.data, SheetData)
        self.assertEqual(result.data.name, "Sheet1")
        self.assertEqual(result.data.row_count, 3)
        self.assertEqual(result.data.headers, ["Name", "Age"])

    @patch("office_automation.HAS_OPENPYXL", True)
    @patch("office_automation.openpyxl")
    @patch("os.path.exists", return_value=True)
    def test_read_specific_sheet(self, mock_exists, mock_openpyxl):
        mock_ws = MagicMock()
        mock_ws.title = "Data"
        mock_ws.iter_rows.return_value = [("X",)]
        mock_wb = MagicMock()
        mock_wb.__getitem__ = MagicMock(return_value=mock_ws)
        mock_wb.sheetnames = ["Sheet1", "Data"]
        mock_openpyxl.load_workbook.return_value = mock_wb

        result = self.client.excel_read("/tmp/test.xlsx", sheet_name="Data")
        self.assertTrue(result.success)
        mock_wb.__getitem__.assert_called_with("Data")

    @patch("office_automation.HAS_OPENPYXL", True)
    @patch("office_automation.openpyxl")
    @patch("os.path.exists", return_value=True)
    def test_read_exception(self, mock_exists, mock_openpyxl):
        mock_openpyxl.load_workbook.side_effect = Exception("Corrupt file")
        result = self.client.excel_read("/tmp/bad.xlsx")
        self.assertFalse(result.success)
        self.assertIn("Corrupt", result.error)


class TestExcelWrite(unittest.TestCase):
    """Test Excel write operations."""

    def setUp(self):
        self.client = OfficeClient()

    @patch("office_automation.HAS_OPENPYXL", False)
    def test_no_openpyxl(self):
        result = self.client.excel_write("/tmp/out.xlsx", [["a"]])
        self.assertFalse(result.success)

    @patch("office_automation.HAS_OPENPYXL", True)
    @patch("office_automation.openpyxl")
    def test_write_success(self, mock_openpyxl):
        mock_ws = MagicMock()
        mock_ws.title = "Sheet1"
        mock_wb = MagicMock()
        mock_wb.active = mock_ws
        mock_openpyxl.Workbook.return_value = mock_wb

        data = [["Name", "Age"], ["Alice", 30]]
        result = self.client.excel_write("/tmp/out.xlsx", data, agent_id="a1")
        self.assertTrue(result.success)
        self.assertEqual(result.data["rows_written"], 2)
        mock_wb.save.assert_called_once_with("/tmp/out.xlsx")

    @patch("office_automation.HAS_OPENPYXL", True)
    @patch("office_automation.openpyxl")
    def test_write_exception(self, mock_openpyxl):
        mock_openpyxl.Workbook.side_effect = Exception("Permission denied")
        result = self.client.excel_write("/tmp/fail.xlsx", [["a"]])
        self.assertFalse(result.success)
        self.assertIn("Permission", result.error)


class TestExcelGetSheets(unittest.TestCase):
    """Test Excel sheet listing."""

    def setUp(self):
        self.client = OfficeClient()

    @patch("office_automation.HAS_OPENPYXL", False)
    def test_no_openpyxl(self):
        result = self.client.excel_get_sheets("/tmp/test.xlsx")
        self.assertFalse(result.success)

    @patch("office_automation.HAS_OPENPYXL", True)
    def test_file_not_found(self):
        result = self.client.excel_get_sheets("/nonexistent.xlsx")
        self.assertFalse(result.success)

    @patch("office_automation.HAS_OPENPYXL", True)
    @patch("office_automation.openpyxl")
    @patch("os.path.exists", return_value=True)
    def test_get_sheets(self, mock_exists, mock_openpyxl):
        mock_wb = MagicMock()
        mock_wb.sheetnames = ["Sheet1", "Data", "Summary"]
        mock_openpyxl.load_workbook.return_value = mock_wb

        result = self.client.excel_get_sheets("/tmp/test.xlsx")
        self.assertTrue(result.success)
        self.assertEqual(result.data, ["Sheet1", "Data", "Summary"])


# ---------------------------------------------------------------------------
# PowerPoint Tests (Mocked)
# ---------------------------------------------------------------------------

class TestPptxCreate(unittest.TestCase):
    """Test PowerPoint creation."""

    def setUp(self):
        self.client = OfficeClient()

    @patch("office_automation.HAS_PPTX", False)
    def test_no_pptx(self):
        result = self.client.pptx_create("/tmp/out.pptx", [])
        self.assertFalse(result.success)
        self.assertIn("python-pptx", result.error)

    @patch("office_automation.HAS_PPTX", True)
    @patch("office_automation.pptx")
    def test_create_success(self, mock_pptx):
        mock_slide = MagicMock()
        mock_slide.placeholders = {0: MagicMock(), 1: MagicMock()}
        mock_presentation = MagicMock()
        mock_presentation.slide_layouts = [MagicMock(), MagicMock()]
        mock_presentation.slides.add_slide.return_value = mock_slide
        mock_pptx.Presentation.return_value = mock_presentation

        slides = [
            {"title": "Intro", "content": "Welcome"},
            {"title": "Data"},
        ]
        result = self.client.pptx_create("/tmp/out.pptx", slides, agent_id="a1")
        self.assertTrue(result.success)
        self.assertEqual(result.data["slides_created"], 2)
        mock_presentation.save.assert_called_once()

    @patch("office_automation.HAS_PPTX", True)
    @patch("office_automation.pptx")
    def test_create_exception(self, mock_pptx):
        mock_pptx.Presentation.side_effect = Exception("Error")
        result = self.client.pptx_create("/tmp/fail.pptx", [{"title": "X"}])
        self.assertFalse(result.success)


class TestPptxRead(unittest.TestCase):
    """Test PowerPoint reading."""

    def setUp(self):
        self.client = OfficeClient()

    @patch("office_automation.HAS_PPTX", False)
    def test_no_pptx(self):
        result = self.client.pptx_read("/tmp/test.pptx")
        self.assertFalse(result.success)

    @patch("office_automation.HAS_PPTX", True)
    def test_file_not_found(self):
        result = self.client.pptx_read("/nonexistent.pptx")
        self.assertFalse(result.success)

    @patch("office_automation.HAS_PPTX", True)
    @patch("office_automation.pptx")
    @patch("os.path.exists", return_value=True)
    def test_read_success(self, mock_exists, mock_pptx):
        # Build mock slide with text frames
        mock_shape1 = MagicMock()
        mock_shape1.has_text_frame = True
        mock_shape1.text_frame.text = "Title Text"
        mock_shape2 = MagicMock()
        mock_shape2.has_text_frame = True
        mock_shape2.text_frame.text = "Body Text"
        mock_shape3 = MagicMock()
        mock_shape3.has_text_frame = False

        mock_slide = MagicMock()
        mock_slide.shapes = [mock_shape1, mock_shape2, mock_shape3]

        mock_presentation = MagicMock()
        mock_presentation.slides = [mock_slide]
        mock_pptx.Presentation.return_value = mock_presentation

        result = self.client.pptx_read("/tmp/test.pptx")
        self.assertTrue(result.success)
        self.assertEqual(len(result.data), 1)
        self.assertEqual(result.data[0]["slide_number"], 1)
        self.assertIn("Title Text", result.data[0]["texts"])
        self.assertIn("Body Text", result.data[0]["texts"])

    @patch("office_automation.HAS_PPTX", True)
    @patch("office_automation.pptx")
    @patch("os.path.exists", return_value=True)
    def test_read_exception(self, mock_exists, mock_pptx):
        mock_pptx.Presentation.side_effect = Exception("Bad file")
        result = self.client.pptx_read("/tmp/bad.pptx")
        self.assertFalse(result.success)


# ---------------------------------------------------------------------------
# PDF Tests (Mocked)
# ---------------------------------------------------------------------------

class TestPdfExtractText(unittest.TestCase):
    """Test PDF text extraction."""

    def setUp(self):
        self.client = OfficeClient()

    @patch("office_automation.HAS_PYPDF", False)
    def test_no_pypdf(self):
        result = self.client.pdf_extract_text("/tmp/test.pdf")
        self.assertFalse(result.success)
        self.assertIn("pypdf", result.error)

    @patch("office_automation.HAS_PYPDF", True)
    def test_file_not_found(self):
        result = self.client.pdf_extract_text("/nonexistent.pdf")
        self.assertFalse(result.success)

    @patch("office_automation.HAS_PYPDF", True)
    @patch("office_automation.pypdf")
    @patch("os.path.exists", return_value=True)
    def test_extract_all(self, mock_exists, mock_pypdf):
        mock_page1 = MagicMock()
        mock_page1.extract_text.return_value = "Page 1 text"
        mock_page2 = MagicMock()
        mock_page2.extract_text.return_value = "Page 2 text"

        mock_reader = MagicMock()
        mock_reader.pages = [mock_page1, mock_page2]
        mock_pypdf.PdfReader.return_value = mock_reader

        result = self.client.pdf_extract_text("/tmp/test.pdf", agent_id="a1")
        self.assertTrue(result.success)
        self.assertEqual(result.data["total_pages"], 2)
        self.assertEqual(len(result.data["pages"]), 2)
        self.assertEqual(result.data["pages"][0]["text"], "Page 1 text")

    @patch("office_automation.HAS_PYPDF", True)
    @patch("office_automation.pypdf")
    @patch("os.path.exists", return_value=True)
    def test_extract_specific_pages(self, mock_exists, mock_pypdf):
        pages = [MagicMock() for _ in range(5)]
        for i, p in enumerate(pages):
            p.extract_text.return_value = f"Text {i}"

        mock_reader = MagicMock()
        mock_reader.pages = pages
        mock_pypdf.PdfReader.return_value = mock_reader

        result = self.client.pdf_extract_text("/tmp/test.pdf", pages=[1, 3])
        self.assertTrue(result.success)
        self.assertEqual(len(result.data["pages"]), 2)
        self.assertEqual(result.data["pages"][0]["page"], 1)
        self.assertEqual(result.data["pages"][1]["page"], 3)

    @patch("office_automation.HAS_PYPDF", True)
    @patch("office_automation.pypdf")
    @patch("os.path.exists", return_value=True)
    def test_extract_out_of_range(self, mock_exists, mock_pypdf):
        mock_reader = MagicMock()
        mock_reader.pages = [MagicMock()]
        mock_reader.pages[0].extract_text.return_value = "Text"
        mock_pypdf.PdfReader.return_value = mock_reader

        result = self.client.pdf_extract_text("/tmp/test.pdf", pages=[0, 99])
        self.assertTrue(result.success)
        self.assertEqual(len(result.data["pages"]), 1)


class TestPdfPageCount(unittest.TestCase):
    """Test PDF page counting."""

    def setUp(self):
        self.client = OfficeClient()

    @patch("office_automation.HAS_PYPDF", False)
    def test_no_pypdf(self):
        result = self.client.pdf_page_count("/tmp/test.pdf")
        self.assertFalse(result.success)

    @patch("office_automation.HAS_PYPDF", True)
    def test_file_not_found(self):
        result = self.client.pdf_page_count("/nonexistent.pdf")
        self.assertFalse(result.success)

    @patch("office_automation.HAS_PYPDF", True)
    @patch("office_automation.pypdf")
    @patch("os.path.exists", return_value=True)
    def test_count(self, mock_exists, mock_pypdf):
        mock_reader = MagicMock()
        mock_reader.pages = [MagicMock()] * 7
        mock_pypdf.PdfReader.return_value = mock_reader

        result = self.client.pdf_page_count("/tmp/test.pdf")
        self.assertTrue(result.success)
        self.assertEqual(result.data["page_count"], 7)


class TestPdfMerge(unittest.TestCase):
    """Test PDF merging."""

    def setUp(self):
        self.client = OfficeClient()

    @patch("office_automation.HAS_PYPDF", False)
    def test_no_pypdf(self):
        result = self.client.pdf_merge(["/a.pdf"], "/out.pdf")
        self.assertFalse(result.success)

    @patch("office_automation.HAS_PYPDF", True)
    def test_file_not_found(self):
        result = self.client.pdf_merge(["/nonexistent.pdf"], "/out.pdf")
        self.assertFalse(result.success)

    @patch("office_automation.HAS_PYPDF", True)
    @patch("office_automation.pypdf")
    @patch("os.path.exists", return_value=True)
    def test_merge_success(self, mock_exists, mock_pypdf):
        mock_merger = MagicMock()
        mock_pypdf.PdfMerger.return_value = mock_merger

        result = self.client.pdf_merge(
            ["/a.pdf", "/b.pdf", "/c.pdf"],
            "/out.pdf", agent_id="a1",
        )
        self.assertTrue(result.success)
        self.assertEqual(result.data["files_merged"], 3)
        self.assertEqual(mock_merger.append.call_count, 3)
        mock_merger.write.assert_called_once_with("/out.pdf")

    @patch("office_automation.HAS_PYPDF", True)
    @patch("office_automation.pypdf")
    @patch("os.path.exists", return_value=True)
    def test_merge_exception(self, mock_exists, mock_pypdf):
        mock_pypdf.PdfMerger.side_effect = Exception("Error")
        result = self.client.pdf_merge(["/a.pdf"], "/out.pdf")
        self.assertFalse(result.success)


class TestPdfSplit(unittest.TestCase):
    """Test PDF splitting."""

    def setUp(self):
        self.client = OfficeClient()

    @patch("office_automation.HAS_PYPDF", False)
    def test_no_pypdf(self):
        result = self.client.pdf_split("/tmp/test.pdf", "/tmp/out")
        self.assertFalse(result.success)

    @patch("office_automation.HAS_PYPDF", True)
    def test_file_not_found(self):
        result = self.client.pdf_split("/nonexistent.pdf", "/tmp/out")
        self.assertFalse(result.success)

    @patch("office_automation.HAS_PYPDF", True)
    @patch("office_automation.pypdf")
    @patch("os.path.exists", return_value=True)
    @patch("os.makedirs")
    @patch("builtins.open", create=True)
    def test_split_success(self, mock_open, mock_makedirs, mock_exists, mock_pypdf):
        mock_page1 = MagicMock()
        mock_page2 = MagicMock()
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page1, mock_page2]
        mock_pypdf.PdfReader.return_value = mock_reader
        mock_pypdf.PdfWriter.return_value = MagicMock()

        result = self.client.pdf_split("/tmp/report.pdf", "/tmp/out")
        self.assertTrue(result.success)
        self.assertEqual(result.data["pages"], 2)
        self.assertEqual(len(result.data["files"]), 2)

    @patch("office_automation.HAS_PYPDF", True)
    @patch("office_automation.pypdf")
    @patch("os.path.exists", return_value=True)
    def test_split_exception(self, mock_exists, mock_pypdf):
        mock_pypdf.PdfReader.side_effect = Exception("Bad PDF")
        result = self.client.pdf_split("/tmp/bad.pdf", "/tmp/out")
        self.assertFalse(result.success)


# ---------------------------------------------------------------------------
# Operation Log Tests
# ---------------------------------------------------------------------------

class TestOperationLog2(unittest.TestCase):
    """Test operation logging."""

    def setUp(self):
        self.client = OfficeClient()

    @patch("office_automation.HAS_OPENPYXL", True)
    @patch("office_automation.openpyxl")
    @patch("os.path.exists", return_value=True)
    def test_log_populated(self, mock_exists, mock_openpyxl):
        mock_ws = MagicMock()
        mock_ws.title = "S1"
        mock_ws.iter_rows.return_value = [("a",)]
        mock_wb = MagicMock()
        mock_wb.active = mock_ws
        mock_wb.sheetnames = ["S1"]
        mock_openpyxl.load_workbook.return_value = mock_wb

        self.client.excel_read("/tmp/test.xlsx", agent_id="a1")
        self.client.excel_read("/tmp/test2.xlsx", agent_id="a2")

        log = self.client.get_operation_log()
        self.assertEqual(len(log), 2)
        # Newest first
        self.assertEqual(log[0].agent_id, "a2")

    @patch("office_automation.HAS_OPENPYXL", True)
    @patch("office_automation.openpyxl")
    @patch("os.path.exists", return_value=True)
    def test_log_filter_by_type(self, mock_exists, mock_openpyxl):
        mock_ws = MagicMock()
        mock_ws.title = "S1"
        mock_ws.iter_rows.return_value = [("a",)]
        mock_wb = MagicMock()
        mock_wb.active = mock_ws
        mock_wb.sheetnames = ["S1"]
        mock_openpyxl.load_workbook.return_value = mock_wb
        mock_openpyxl.Workbook.return_value = mock_wb

        self.client.excel_read("/tmp/r.xlsx")
        self.client.excel_write("/tmp/w.xlsx", [["a"]])

        log = self.client.get_operation_log(doc_type="excel")
        self.assertEqual(len(log), 2)

    @patch("office_automation.HAS_OPENPYXL", True)
    @patch("office_automation.openpyxl")
    @patch("os.path.exists", return_value=True)
    def test_log_filter_by_agent(self, mock_exists, mock_openpyxl):
        mock_ws = MagicMock()
        mock_ws.title = "S1"
        mock_ws.iter_rows.return_value = [("a",)]
        mock_wb = MagicMock()
        mock_wb.active = mock_ws
        mock_wb.sheetnames = ["S1"]
        mock_openpyxl.load_workbook.return_value = mock_wb

        self.client.excel_read("/tmp/a.xlsx", agent_id="a1")
        self.client.excel_read("/tmp/b.xlsx", agent_id="a2")
        self.client.excel_read("/tmp/c.xlsx", agent_id="a1")

        log = self.client.get_operation_log(agent_id="a1")
        self.assertEqual(len(log), 2)

    @patch("office_automation.HAS_OPENPYXL", True)
    @patch("office_automation.openpyxl")
    @patch("os.path.exists", return_value=True)
    def test_log_limit(self, mock_exists, mock_openpyxl):
        mock_ws = MagicMock()
        mock_ws.title = "S1"
        mock_ws.iter_rows.return_value = [("a",)]
        mock_wb = MagicMock()
        mock_wb.active = mock_ws
        mock_wb.sheetnames = ["S1"]
        mock_openpyxl.load_workbook.return_value = mock_wb

        for i in range(10):
            self.client.excel_read(f"/tmp/f{i}.xlsx")

        log = self.client.get_operation_log(limit=3)
        self.assertEqual(len(log), 3)

    def test_log_empty(self):
        log = self.client.get_operation_log()
        self.assertEqual(log, [])


# ---------------------------------------------------------------------------
# Status Tests
# ---------------------------------------------------------------------------

class TestStatus(unittest.TestCase):
    """Test status reporting."""

    def test_status(self):
        client = OfficeClient()
        s = client.status()
        self.assertIn("available_formats", s)
        self.assertIn("total_operations", s)
        self.assertEqual(s["total_operations"], 0)
        self.assertIn("excel", s["supported_extensions"])
        self.assertEqual(s["supported_extensions"]["excel"], [".xlsx"])
        self.assertEqual(s["supported_extensions"]["powerpoint"], [".pptx"])
        self.assertEqual(s["supported_extensions"]["pdf"], [".pdf"])


# ---------------------------------------------------------------------------
# Thread Safety Tests
# ---------------------------------------------------------------------------

class TestThreadSafety(unittest.TestCase):
    """Test thread safety."""

    @patch("office_automation.HAS_OPENPYXL", True)
    @patch("office_automation.openpyxl")
    @patch("os.path.exists", return_value=True)
    def test_concurrent_operations(self, mock_exists, mock_openpyxl):
        mock_ws = MagicMock()
        mock_ws.title = "S"
        mock_ws.iter_rows.return_value = [("x",)]
        mock_wb = MagicMock()
        mock_wb.active = mock_ws
        mock_wb.sheetnames = ["S"]
        mock_openpyxl.load_workbook.return_value = mock_wb

        client = OfficeClient()
        errors = []

        def reader(agent_id):
            try:
                for _ in range(20):
                    client.excel_read("/tmp/x.xlsx", agent_id=agent_id)
            except Exception as e:
                errors.append(str(e))

        threads = [
            threading.Thread(target=reader, args=(f"a{i}",))
            for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        log = client.get_operation_log(limit=200)
        self.assertEqual(len(log), 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
