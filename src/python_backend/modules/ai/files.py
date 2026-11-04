"""文件工具定义、受限参数及 Office 文件生成，不执行模型提供的代码。"""

import json
import re
from io import BytesIO
from typing import Literal

from docx import Document
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from pydantic import BaseModel, ConfigDict, Field, model_validator

from python_backend.modules.ai.errors import AIError
from python_backend.modules.chat.attachments import DOCUMENT_MIMES


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Sheet(Input):
    name: str = Field(min_length=1, max_length=31, pattern=r"^[^\\/?*\[\]:]+$")
    rows: list[list[str | int | float | bool | None]] = Field(min_length=1, max_length=2000)


class ExcelInput(Input):
    filename: str = Field(min_length=1, max_length=180)
    sheets: list[Sheet] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def limits(self):
        if len({s.name.lower() for s in self.sheets}) != len(self.sheets):
            raise ValueError("工作表名称重复")
        if any(len(row) > 100 for sheet in self.sheets for row in sheet.rows):
            raise ValueError("列数超限")
        if sum(len(row) for sheet in self.sheets for row in sheet.rows) > 20000:
            raise ValueError("单元格超限")
        return self


class Block(Input):
    type: Literal["heading", "paragraph", "bullet", "table"]
    text: str = Field(default="", max_length=10000)
    level: int = Field(default=1, ge=1, le=3)
    rows: list[list[str]] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def limits(self):
        if self.type == "table" and (not self.rows or any(not r or len(r) > 20 for r in self.rows)):
            raise ValueError("表格无效")
        return self


class WordInput(Input):
    filename: str = Field(min_length=1, max_length=180)
    title: str = Field(default="", max_length=500)
    blocks: list[Block] = Field(min_length=1, max_length=300)


FILE_INPUTS = {"generate_excel": ExcelInput, "generate_word": WordInput}
FILE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": schema.model_json_schema(),
        },
    }
    for name, schema, description in [
        (
            "generate_excel",
            ExcelInput,
            "用户要求 Excel/xlsx 文件时调用，提供真实数据生成可下载文件。"
            "单元格为普通值，不支持公式。",
        ),
        (
            "generate_word",
            WordInput,
            "用户要求 Word/docx 文件时调用，提供标题、段落、标题块、列表或表格，生成可下载文件。",
        ),
    ]
]


def generate_file(name, arguments):
    try:
        if len(json.dumps(arguments, ensure_ascii=False).encode()) > 200000:
            raise ValueError("文件内容过大")
        body = FILE_INPUTS[name].model_validate(arguments)
        suffix = ".xlsx" if name == "generate_excel" else ".docx"
        filename = re.sub(r'[\\/<>:"|?*\x00-\x1f\x7f]', "_", body.filename).strip(" .")
        if not filename:
            filename = "文件"
        if not filename.lower().endswith(suffix):
            filename += suffix
        buffer = BytesIO()
        if name == "generate_excel":
            doc = Workbook()
            doc.remove(doc.active)
            for sheet in body.sheets:
                ws = doc.create_sheet(sheet.name)
                for row in sheet.rows:
                    ws.append(row)
                for row in ws:
                    for cell in row:
                        # 将模型输出当作数据，禁止自动转为 Excel 公式或错误类型。
                        if isinstance(cell.value, str):
                            cell.data_type = "s"
                        cell.font = Font(name="Arial", size=11, bold=cell.row == 1)
                        if cell.row == 1:
                            cell.fill = PatternFill("solid", fgColor="E8EEF6")
                ws.freeze_panes = "A2"
                for column in ws.columns:
                    ws.column_dimensions[column[0].column_letter].width = min(
                        50, max(12, max(len(str(c.value or "")) for c in column) + 2)
                    )
        else:
            doc = Document()
            if body.title:
                doc.add_heading(body.title, 0)
            for block in body.blocks:
                if block.type == "heading":
                    doc.add_heading(block.text, block.level)
                elif block.type == "table":
                    table = doc.add_table(rows=0, cols=max(map(len, block.rows)))
                    table.style = "Table Grid"
                    for row in block.rows:
                        cells = table.add_row().cells
                        for cell, value in zip(cells, row):
                            cell.text = value
                else:
                    doc.add_paragraph(block.text, "List Bullet" if block.type == "bullet" else None)
        doc.save(buffer)
        data = buffer.getvalue()
        if len(data) > 5 * 1024 * 1024:
            raise ValueError("文件过大")
        return {"name": filename, "mimeType": DOCUMENT_MIMES[suffix], "data": data}
    except (ValueError, KeyError, TypeError) as error:
        raise AIError("文件工具参数无效，请缩小内容范围后重试", 502) from error
