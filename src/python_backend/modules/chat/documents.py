"""有大小限制的 Office/PDF 附件文字解析。"""

import io
import re
import zipfile
from pathlib import Path

from defusedxml import ElementTree
from openpyxl import load_workbook
from pypdf import PdfReader

from python_backend.modules.ai.errors import AIError
from python_backend.modules.chat.attachments import DOCUMENT_MIMES


def extract_document(filename, data):
    suffix = Path(filename).suffix.lower()
    if not 0 < len(data) <= 10 * 1024 * 1024:
        raise AIError("请选择非空文件，单个文件最大 10 MB")
    if suffix not in (".docx", ".xlsx", ".pdf", ".pptx") or len(filename) > 255:
        raise AIError("文档支持 DOCX、XLSX、PDF、PPTX")
    try:
        if suffix == ".pdf":
            if not data.startswith(b"%PDF-"):
                raise ValueError()
            reader = PdfReader(io.BytesIO(data))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        else:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if sum(e.file_size for e in archive.infolist()) > 30 * 1024 * 1024:
                    raise AIError("文档解压后过大，请拆分后上传")
                if suffix == ".docx":
                    doc = ElementTree.fromstring(archive.read("word/document.xml"))
                    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                    text = "\n".join("".join(p.itertext()) for p in doc.findall(".//w:p", ns))
                elif suffix == ".pptx":
                    slides = sorted(
                        [
                            n
                            for n in archive.namelist()
                            if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)
                        ],
                        key=lambda n: int(re.search(r"slide(\d+)", n)[1]),
                    )
                    if not slides:
                        raise ValueError()
                    parts = []
                    for i, name in enumerate(slides):
                        doc = ElementTree.fromstring(archive.read(name))
                        texts = [e.text or "" for e in doc.iter() if e.tag.endswith("}t")]
                        parts.append(f"幻灯片 {i + 1}\n" + "\n".join(texts))
                    text = "\n\n".join(parts)
                else:
                    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
                    try:
                        parts = []
                        cells = 0
                        for sheet in workbook:
                            parts.append(f"工作表：{sheet.title}")
                            for row in sheet.iter_rows(values_only=True):
                                cells += len(row)
                                if cells > 100000:
                                    raise AIError("表格过大，请拆分后上传")
                                parts.append(
                                    "\t".join(
                                        re.sub(r"[\t\r\n]+", " ", str(c)) if c is not None else ""
                                        for c in row
                                    )
                                )
                        text = "\n".join(parts)
                    finally:
                        workbook.close()
        text = text.replace("\0", "").strip()
        if not text:
            raise AIError("未能提取文字；扫描版或纯图片文档请上传截图")
        if len(text.encode()) > 100000:
            raise AIError("提取文字超过 100 KB，请拆分后上传")
        return {"name": filename, "type": "document", "mime": DOCUMENT_MIMES[suffix], "text": text}
    except AIError:
        raise
    except Exception as error:
        raise AIError("文件解析失败，请检查格式、损坏或加密情况") from error
