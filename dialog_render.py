#!/usr/bin/env python3
"""
dialog_render.py
渲染discuss对话YAML，输出：
1. interactive.html 交互式网页(头像+音频base64内嵌，浅色/深色主题切换)
2. output.pdf A4打印PDF(无音频，打印友好)
3. 分页png序列 1080x1920 9:16纵向截图
依赖：pyyaml, jinja2, playwright, Pillow
"""
import json
import os
import base64
import argparse
import yaml
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright
from PIL import Image
# -------------------------- 常量配置 --------------------------
PDF_PAGE_FORMAT = "A4"
PDF_MARGIN_TOP = "15mm"
PDF_MARGIN_BOTTOM = "15mm"
PDF_MARGIN_LEFT = "15mm"
PDF_MARGIN_RIGHT = "15mm"
PNG_VIEWPORT_WIDTH = 1080
PNG_VIEWPORT_HEIGHT = 1920
FALLBACK_BUBBLE_RGBA = "rgba(220,220,220,0.3)"  # 头像读取失败回退气泡颜色
SCRIPT_DIR = os.path.dirname(os.path.abspath(os.path.realpath(__file__)))

def read_file_as_b64(file_path: str, mime_type: str) -> str:
    """读取二进制文件返回 base64 data‑url字符串"""
    with open(file_path, "rb") as f:
        data = f.read()
    b64 = base64.b64encode(data).decode("utf‑8")
    return f"data:{mime_type};base64,{b64}"

def get_image_dominant_rgba(img_path: Path) -> str:
    """
    获取图片占比最高主色，RGB各通道减半，alpha=0.25
    返回 rgba(r,g,b,0.25)；异常返回fallback
    """
    try:
        with Image.open(img_path) as im:
            im = im.convert("RGB")
            im.thumbnail((120, 120))
            pixels = list(im.getdata())
            freq = {}
            for pix in pixels:
                freq[pix] = freq.get(pix, 0) + 1
            dominant_rgb = max(freq, key=freq.get)
            r = int(dominant_rgb[0] * 0.5)
            g = int(dominant_rgb[1] * 0.5)
            b = int(dominant_rgb[2] * 0.5)
            return f"rgba({r},{g},{b},0.25)"
    except Exception as e:
        print(f"[COLOR_EXTRACT_WARN] {img_path}, err:{e}")
        return FALLBACK_BUBBLE_RGBA

def merge_consecutive_speaker(pd_list: list):
    """
    合并连续同一个sp的台词，输出气泡单元列表
    bubble_item = {
        "sp": str,
        "txt_list": [str,...],
    }
    """
    bubbles = []
    if not isinstance(pd_list, list) or len(pd_list) == 0:
        return bubbles
    current_sp = None
    current_texts = []
    for entry in pd_list:
        sp = entry.get("sp", "").strip()
        txt = entry.get("txt", "").strip()
        if not sp or not txt:
            continue
        if sp == current_sp:
            current_texts.append(txt)
        else:
            if current_sp is not None:
                bubbles.append({"sp": current_sp, "txt_list": current_texts})
            current_sp = sp
            current_texts = [txt]
    if current_sp is not None:
        bubbles.append({"sp": current_sp, "txt_list": current_texts})
    return bubbles

def build_group_context(g_raw, group_idx: int, cast_dir: Path, audio_dir: Path):
    """
    处理单个group：合并气泡、加载头像base64+气泡颜色、加载group音频base64
    返回 group_ctx dict，pd为空返回None(该group跳过渲染)
    """
    gt = g_raw.get("gt", "")
    pd_list = g_raw.get("a", {}).get("pd", [])
    bubble_list = merge_consecutive_speaker(pd_list)
    if len(bubble_list) == 0:
        return None

    # 处理每个气泡：头像、气泡背景色
    processed_bubbles = []
    sp_cache = dict()  # sp -> {"avatar_b64":str|None, "bubble_bg":str}

    for b in bubble_list:
        sp = b["sp"]
        if sp not in sp_cache:
            avatar_filename = f"{sp}_00001_.png"
            avatar_path = cast_dir / avatar_filename
            avatar_b64 = None
            bubble_bg = FALLBACK_BUBBLE_RGBA
            if avatar_path.exists():
                try:
                    avatar_b64 = read_file_as_b64(str(avatar_path), "image/png")
                    bubble_bg = get_image_dominant_rgba(avatar_path)
                except Exception as e:
                    print(f"[AVATAR_WARN] sp={sp}, file={avatar_path}, err={e}")
            else:
                print(f"[AVATAR_WARN] sp={sp} avatar not found: {avatar_path}")
            sp_cache[sp] = {"avatar_b64": avatar_b64, "bubble_bg": bubble_bg}
        cache_item = sp_cache[sp]
        processed_bubbles.append({
            "sp": sp,
            "txt_list": b["txt_list"],
            "avatar_b64": cache_item["avatar_b64"],
            "bubble_bg": cache_item["bubble_bg"]
        })

    # 读取group对应音频
    audio_filename = f"_groups_{group_idx}_a.wav"
    audio_path = audio_dir / audio_filename
    group_audio_b64 = None
    if audio_path.exists():
        try:
            group_audio_b64 = read_file_as_b64(str(audio_path), "audio/wav")
        except Exception as e:
            print(f"[AUDIO_WARN] group {group_idx} file={audio_path}, err={e}")
    else:
        print(f"[AUDIO_WARN] group {group_idx} audio not found: {audio_path}")

    return {
        "gt": gt,
        "bubbles": processed_bubbles,
        "group_audio_b64": group_audio_b64
    }

def render_html(tpl_env, tpl_name: str, context: dict) -> str:
    tpl = tpl_env.get_template(tpl_name)
    return tpl.render(**context)

def html_to_pdf(html_content: str, output_pdf_path: str):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html_content)
        page.wait_for_load_state("networkidle")
        pdf_opts = {
            "format": PDF_PAGE_FORMAT,
            "margin": {
                "top": PDF_MARGIN_TOP,
                "bottom": PDF_MARGIN_BOTTOM,
                "left": PDF_MARGIN_LEFT,
                "right": PDF_MARGIN_RIGHT,
            },
            "print_background": True
        }
        page.pdf(path=output_pdf_path, **pdf_opts)
        browser.close()

def html_to_paginated_png(html_content: str, out_prefix: str):
    """
    固定视口1080*1920，滚动分页截图
    out_prefix: 输出文件前缀，生成 prefix_000.png, prefix_001.png ...
    """
    out_files = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": PNG_VIEWPORT_WIDTH, "height": PNG_VIEWPORT_HEIGHT})
        page.set_content(html_content)
        page.wait_for_load_state("networkidle")
        scroll_height = page.evaluate("document.body.scrollHeight")
        view_h = PNG_VIEWPORT_HEIGHT
        page_idx = 0
        offset = 0
        while offset < scroll_height:
            page.evaluate(f"window.scrollTo(0, {offset})")
            page.wait_for_timeout(80)
            out_path = f"{out_prefix}_{page_idx:03d}.png"
            page.screenshot(path=out_path, full_page=False)
            out_files.append(out_path)
            offset += view_h
            page_idx += 1
        browser.close()
    return out_files

def main():
    parser = argparse.ArgumentParser(description="Dialog YAML render: interactive.html / output.pdf / 分页png")
    parser.add_argument("discuss_yaml", help="path to discuss dialog yaml file")
    parser.add_argument("-c", "--cast_dir", required=True, help="角色头像资源目录，存放 {sp}_00001_.png")
    parser.add_argument("-a", "--audio_dir", required=True, help="group合成wav音频目录 _groups_{idx}_a.wav")
    parser.add_argument("--template_dir", default=SCRIPT_DIR, help="jinja2模板文件夹路径")
    args = parser.parse_args()

    yaml_abs = Path(args.discuss_yaml).resolve()
    yaml_base_dir = yaml_abs.parent
    cast_dir = Path(args.cast_dir).resolve()
    audio_dir = Path(args.audio_dir).resolve()

    with open(yaml_abs, "r", encoding="utf‑8") as f:
        raw_data = yaml.safe_load(f)

    # 提取元信息
    quiz_meta = raw_data.get("quiz_meta", {})
    groups_raw = raw_data.get("groups", [])

    # 预处理所有group
    group_ctx_list = []
    for g_idx, g_raw in enumerate(groups_raw):
        g_ctx = build_group_context(g_raw, g_idx, cast_dir, audio_dir)
        if g_ctx is not None:
            group_ctx_list.append(g_ctx)
        else:
            print(f"[GROUP_SKIP] group idx={g_idx} pd为空，跳过该组渲染")

    # jinja环境
    jinja_env = Environment(loader=FileSystemLoader(args.template_dir), autoescape=True)
    def json_filter(val):
        return json.dumps(val, ensure_ascii=False)
    jinja_env.filters["tojson"] = json_filter

    render_ctx = {
        "quiz_meta": quiz_meta,
        "groups": group_ctx_list
    }

    basename_stem = yaml_abs.stem
    # 1.交互式HTML(带主题切换、audio播放器)
    html_interactive = render_html(jinja_env, "dialog_interactive.html.j2", render_ctx)
    html_interactive_path = yaml_base_dir / f"{basename_stem}_interactive.html"
    with open(html_interactive_path, "w", encoding="utf‑8") as f:
        f.write(html_interactive)
    print(f"✅ 生成交互式网页: {html_interactive_path}")

    # 2.PDF打印版HTML，无js无audio
    html_pdf_content = render_html(jinja_env, "dialog_print_pdf.html.j2", render_ctx)
    pdf_out_path = yaml_base_dir / f"{basename_stem}.pdf"
    html_to_pdf(html_pdf_content, str(pdf_out_path))
    print(f"✅ 生成PDF: {pdf_out_path}")

    # 3.PNG分页截图，使用png专用模板
    html_png_content = render_html(jinja_env, "dialog_snapshot_png.html.j2", render_ctx)
    png_prefix = str(yaml_base_dir / f"{basename_stem}_snap")
    png_files = html_to_paginated_png(html_png_content, png_prefix)
    for fpath in png_files:
        print(f"✅ 生成PNG分片: {fpath}")

if __name__ == "__main__":
    main()
