"""生成 PDF 缩略图网格 — 用于测试 VLM 锚点检测。"""

import sys
import math
import pymupdf


def render_thumbnail_grid(
    file_path: str,
    output_path: str,
    cols: int = 8,
    thumb_width: int = 200,
    thumb_height: int = 280,
    padding: int = 10,
    label_height: int = 20,
):
    """把 PDF 所有页面渲染成缩略图网格。

    Args:
        file_path: PDF 文件路径
        output_path: 输出图片路径 (.png)
        cols: 每行列数
        thumb_width: 每个缩略图宽度
        thumb_height: 每个缩略图高度
        padding: 缩略图间距
        label_height: 页码标签高度
    """
    doc = pymupdf.open(file_path)
    page_count = len(doc)
    rows = math.ceil(page_count / cols)

    # 计算画布尺寸
    canvas_width = cols * (thumb_width + padding) + padding
    canvas_height = rows * (thumb_height + label_height + padding) + padding

    # 创建白色画布
    from PIL import Image, ImageDraw, ImageFont

    canvas = Image.new("RGB", (canvas_width, canvas_height), "white")
    draw = ImageDraw.Draw(canvas)

    # 尝试加载字体
    try:
        font = ImageFont.truetype("arial.ttf", 14)
    except Exception:
        font = ImageFont.load_default()

    for i in range(page_count):
        row = i // cols
        col = i % cols

        x = padding + col * (thumb_width + padding)
        y = padding + row * (thumb_height + label_height + padding)

        # 渲染缩略图
        page = doc[i]
        # 计算缩放比例使页面适合缩略图区域
        page_rect = page.rect
        scale_x = thumb_width / page_rect.width
        scale_y = thumb_height / page_rect.height
        scale = min(scale_x, scale_y)
        mat = pymupdf.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=mat)

        # 转为 PIL Image
        img_data = pix.tobytes("png")
        import io

        thumb_img = Image.open(io.BytesIO(img_data))

        # 居中放置缩略图
        offset_x = (thumb_width - thumb_img.width) // 2
        offset_y = (thumb_height - thumb_img.height) // 2
        canvas.paste(thumb_img, (x + offset_x, y + label_height + offset_y))

        # 画边框
        draw.rectangle(
            [x, y + label_height, x + thumb_width, y + label_height + thumb_height],
            outline="#cccccc",
            width=1,
        )

        # 标注页码
        label = f"p.{i + 1}"
        draw.text((x + 5, y + 2), label, fill="black", font=font)

    doc.close()

    canvas.save(output_path, "PNG")
    print(f"Saved thumbnail grid: {output_path}")
    print(
        f"  Pages: {page_count}, Grid: {cols}x{rows}, Size: {canvas_width}x{canvas_height}"
    )


def render_thumbnail_grids(
    file_path: str,
    output_dir: str,
    pages_per_grid: int = 24,
    cols: int = 6,
    thumb_width: int = 250,
    thumb_height: int = 350,
    padding: int = 12,
    label_height: int = 22,
):
    """把 PDF 页面分批渲染成多张缩略图网格。

    Args:
        file_path: PDF 文件路径
        output_dir: 输出目录
        pages_per_grid: 每张网格最多包含的页数
        cols: 每行列数

    Returns:
        输出文件路径列表
    """
    import os
    from PIL import Image, ImageDraw, ImageFont

    doc = pymupdf.open(file_path)
    page_count = len(doc)
    os.makedirs(output_dir, exist_ok=True)

    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except Exception:
        font = ImageFont.load_default()

    output_files = []
    grid_idx = 0

    for start in range(0, page_count, pages_per_grid):
        end = min(start + pages_per_grid, page_count)
        n_pages = end - start
        rows = math.ceil(n_pages / cols)

        canvas_width = cols * (thumb_width + padding) + padding
        canvas_height = rows * (thumb_height + label_height + padding) + padding

        canvas = Image.new("RGB", (canvas_width, canvas_height), "white")
        draw = ImageDraw.Draw(canvas)

        for i in range(n_pages):
            page_num = start + i
            row = i // cols
            col = i % cols

            x = padding + col * (thumb_width + padding)
            y = padding + row * (thumb_height + label_height + padding)

            page = doc[page_num]
            page_rect = page.rect
            scale_x = thumb_width / page_rect.width
            scale_y = thumb_height / page_rect.height
            scale = min(scale_x, scale_y)
            mat = pymupdf.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=mat)

            import io

            thumb_img = Image.open(io.BytesIO(pix.tobytes("png")))

            offset_x = (thumb_width - thumb_img.width) // 2
            offset_y = (thumb_height - thumb_img.height) // 2
            canvas.paste(thumb_img, (x + offset_x, y + label_height + offset_y))

            draw.rectangle(
                [x, y + label_height, x + thumb_width, y + label_height + thumb_height],
                outline="#999999",
                width=1,
            )

            label = f"p.{page_num + 1}"
            draw.text((x + 4, y + 2), label, fill="black", font=font)

        grid_idx += 1
        out_path = os.path.join(output_dir, f"grid_{grid_idx}_p{start + 1}-{end}.png")
        canvas.save(out_path, "PNG")
        output_files.append(out_path)
        print(f"  Grid {grid_idx}: p.{start + 1}-{end} ({n_pages} pages) → {out_path}")

    doc.close()
    print(f"Done: {len(output_files)} grid images")
    return output_files


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate PDF thumbnail grids")
    parser.add_argument("pdf_path", help="Path to PDF file")
    parser.add_argument(
        "output_dir", nargs="?", default="thumbnail_grids", help="Output directory"
    )
    parser.add_argument("--cols", type=int, default=6, help="Columns per grid")
    parser.add_argument("--pages", type=int, default=24, help="Pages per grid")
    args = parser.parse_args()
    render_thumbnail_grids(
        args.pdf_path, args.output_dir, pages_per_grid=args.pages, cols=args.cols
    )
