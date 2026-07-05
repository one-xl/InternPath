import os
import shutil
import logging
from typing import Any, List
from config import Config
from backend.agents.tools.docx_tools import convert_docx_to_pdf

logger = logging.getLogger(__name__)

def check_layout_dependencies() -> tuple[bool, str]:
    """
    检查系统 Path 下是否存在 LibreOffice 的 soffice/libreoffice 可执行文件，
    以及 Poppler 的 pdftoppm 可执行文件。

    返回:
        tuple[bool, str]: (是否全部存在, 缺少的组件描述)
    """
    soffice_path = shutil.which("soffice") or shutil.which("libreoffice")
    pdftoppm_path = shutil.which("pdftoppm")

    missing = []
    if not soffice_path:
        missing.append("LibreOffice (soffice/libreoffice)")
    if not pdftoppm_path:
        missing.append("Poppler (pdftoppm)")

    if missing:
        return False, " & ".join(missing)
    return True, ""

def render_docx_to_images(user_id: Any, task_id: str, docx_path: str) -> List[str]:
    """
    将 DOCX 转换为 PDF，再将 PDF 的每一页转化为图片，
    图片保存在 workspace/layout_pages/ 目录下。

    返回:
        List[str]: 生成的图片的绝对物理路径列表。
    """
    # 通过 Config.USER_DB_DIR 获取隔离的工作区目录
    pdf_dir = os.path.abspath(
        os.path.join(Config.USER_DB_DIR, "workspaces", f"user_{user_id}", f"task_{task_id}")
    )
    os.makedirs(pdf_dir, exist_ok=True)

    # 转换 DOCX 为 PDF
    success = convert_docx_to_pdf(user_id, task_id, docx_path, pdf_dir)
    if not success:
        raise RuntimeError(f"DOCX 转换为 PDF 失败: {docx_path}")

    # 寻找生成的 PDF 文件，优选匹配 DOCX 文件名对应的 PDF 文件名
    pdf_name = os.path.splitext(os.path.basename(docx_path))[0] + ".pdf"
    pdf_path = os.path.join(pdf_dir, pdf_name)
    if not os.path.exists(pdf_path):
        # 兜底寻找 optimized_resume.pdf
        pdf_path = os.path.join(pdf_dir, "optimized_resume.pdf")

    if not os.path.exists(pdf_path):
        # 如果依然找不到，在 pdf_dir 目录下扫描任何以 .pdf 结尾的文件
        pdf_files = [f for f in os.listdir(pdf_dir) if f.endswith(".pdf")]
        if pdf_files:
            pdf_path = os.path.join(pdf_dir, pdf_files[0])
        else:
            raise FileNotFoundError(f"未找到生成的 PDF 文件，目录: {pdf_dir}")

    # 创建图片的保存目录，置于 Config.USER_DB_DIR 隔离工作区下
    layout_pages_dir = os.path.abspath(
        os.path.join(Config.USER_DB_DIR, "workspaces", "layout_pages")
    )
    os.makedirs(layout_pages_dir, exist_ok=True)

    # 使用 pdf2image.convert_from_path 转换 PDF 每一页为 PIL Image 对象
    try:
        from pdf2image import convert_from_path
    except ImportError as e:
        raise RuntimeError("未检测到本地安装 python 包 'pdf2image'。请使用 pip install pdf2image 安装！") from e

    images = convert_from_path(pdf_path)

    image_paths = []
    for i, image in enumerate(images):
        # 命名格式，如: page_{user_id}_{task_id}_{i}.png
        image_name = f"page_{user_id}_{task_id}_{i}.png"
        image_path = os.path.join(layout_pages_dir, image_name)
        image.save(image_path, "PNG")
        image_paths.append(os.path.abspath(image_path))

    logger.info(f"成功将 PDF 渲染为图片，生成了 {len(image_paths)} 张页面图片。")
    return image_paths
