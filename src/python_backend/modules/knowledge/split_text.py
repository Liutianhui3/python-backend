"""按 Unicode 字符切片，保留相邻片段重叠。"""

from python_backend.modules.ai.errors import AIError


def split_text(text, size=500, overlap=50):
    if not 100 <= size <= 2000 or not 0 <= overlap < size:
        raise AIError("切片长度需为 100–2000，重叠长度需小于切片长度")
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff").strip()
    if not text or "\0" in text:
        raise AIError("文件内容为空或包含二进制内容")
    chunks = []
    for start in range(0, len(text), size - overlap):
        content = text[start : start + size]
        chunks.append({"position": len(chunks) + 1, "content": content, "char_count": len(content)})
        if start + size >= len(text):
            break
    return chunks
