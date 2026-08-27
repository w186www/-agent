"""OCR 兜底：PyMuPDF 渲染 PDF 页面 → base64 → 火山引擎 OCRNormal → 按行拼接全文。

对外只暴露 ocr_pdf(path)。供 kb_ingest 提取到空文本（扫描版 PDF）时降级使用，
电子版 PDF 直接走文本抽取，不消耗 OCR 成本。凭证走 settings（VOLC_ACCESS_KEY /
VOLC_SECRET_KEY / VOLC_REGION），未配置时抛出友好错误由调用方降级处理。

说明：与早期 agent-backend 项目的 ocr.py 实现等价，但 PDF 渲染使用 PyMuPDF
（本项目已有依赖），不额外引入 pypdfium2。
"""

import base64
import io
import logging
from pathlib import Path

import fitz  # PyMuPDF
from volcengine.visual.VisualService import VisualService

from ..config import settings

logger = logging.getLogger("app.ocr")

# 渲染 DPI（150 DPI 保障识别精度）
RENDER_DPI = 150
# 单页 OCR 行数上限（异常防御）
MAX_LINES_PER_PAGE = 500

_visual: VisualService | None = None


def _get_visual() -> VisualService:
    """懒加载 VisualService；未配置 Key 时抛错，避免无 Key 空跑。"""
    global _visual
    if _visual is None:
        if not settings.volc_access_key or not settings.volc_secret_key:
            raise ValueError("未配置 VOLC_ACCESS_KEY / VOLC_SECRET_KEY，无法执行 OCR")
        svc = VisualService()
        svc.set_ak(settings.volc_access_key)
        svc.set_sk(settings.volc_secret_key)
        svc.set_host(settings.volc_host)
        svc.set_scheme("https")
        svc.service_info.credentials.region = settings.volc_region
        _visual = svc
    return _visual


def _page_to_base64(pdf: fitz.Document, index: int) -> str:
    """PyMuPDF 按 150 DPI 渲染第 index 页为 PNG，返回 base64。"""
    pix = pdf[index].get_pixmap(dpi=RENDER_DPI)
    buf = io.BytesIO(pix.tobytes("png"))
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _ocr_page(image_base64: str) -> list[str]:
    """单页 base64 → OCRNormal → 行文本列表。"""
    resp = _get_visual().ocr_normal({"image_base64": image_base64})
    meta = (resp or {}).get("ResponseMetadata", {})
    if meta.get("Error"):
        err = meta["Error"]
        raise RuntimeError(f"火山 OCR 失败: {err.get('Code')} {err.get('Message')}")
    lines = (resp or {}).get("data", {}).get("line_texts", [])
    return [line for line in lines[:MAX_LINES_PER_PAGE] if line]


def ocr_pdf(path: str | Path) -> str:
    """整份 PDF 走 OCR：逐页渲染 → 识别 → 按行拼接为全文。"""
    doc = fitz.open(str(path))
    all_lines: list[str] = []
    try:
        total = doc.page_count
        for i in range(total):
            lines = _ocr_page(_page_to_base64(doc, i))
            all_lines.extend(lines)
            logger.info("OCR 第 %d/%d 页完成: %d 行", i + 1, total, len(lines))
    finally:
        doc.close()
    text = "\n".join(all_lines)
    if not text.strip():
        raise ValueError(f"OCR 未识别到文本: {Path(path).name}")
    return text
