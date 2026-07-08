# -*- coding: utf-8 -*-
"""发布模块：生成HTML → 处理图片 → 调 wechat-api.ts 发布"""

import os
import re
import subprocess
import requests
from datetime import datetime
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont


class Publisher:
    def __init__(self, config: dict):
        self.config = config
        self.skill_dir = config["publish"]["skill_dir"]
        self.auto = config["publish"]["auto"]
        self.output_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), config["paths"]["output_dir"])
        )

    def _crop_watermark(self, url: str, output_path: str) -> str:
        """下载图片，裁掉底部 10% 水印区域，保存为本地文件"""
        try:
            resp = requests.get(url, timeout=15, headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://mp.weixin.qq.com/"
            })
            resp.raise_for_status()
            img = Image.open(BytesIO(resp.content))
            w, h = img.size
            # 裁掉底部 10%（水印通常在底部条中）
            crop_h = int(h * 0.82); crop_w = int(w * 0.88)
            if img.mode in ('RGBA', 'P', 'LA'):
                img = img.convert('RGB')
            cropped = img.crop((0, 0, crop_w, crop_h))
            cropped.save(output_path)
            print(f"    crop: {os.path.basename(output_path)} ({w}x{h} -> {w}x{crop_h})")
            return output_path
        except Exception as e:
            print(f"    crop failed for {url[:60]}: {e}")
            return url  # fallback to original URL

    def _insert_images(self, html: str, images: list[str], slug: str) -> str:
        """将 [IMG:n] 替换为处理后的图片标签"""
        date_str = datetime.now().strftime("%Y-%m-%d")
        img_dir = os.path.join(self.output_dir, date_str, f"imgs_{slug}")
        os.makedirs(img_dir, exist_ok=True)

        for i, url in enumerate(images):
            # 下载 + 裁水印
            local_path = os.path.join(img_dir, f"img_{i}.jpg")
            clean_url = self._crop_watermark(url, local_path)
            img_tag = f'<p style="text-align:center;"><img src="{clean_url}" style="max-width:100%;height:auto;" alt="配图"/></p>'
            html = html.replace(f"[IMG:{i}]", img_tag)
        html = re.sub(r"\[IMG:\d+\]", "", html)
        return html

    def _extract_title_from_html(self, html: str) -> str:
        m = re.search(r"<h2[^>]*>(.*?)</h2>", html, re.IGNORECASE | re.DOTALL)
        if m:
            return re.sub(r"<[^>]+>", "", m.group(1)).strip()
        return "未命名文章"

    def _extract_summary(self, html: str) -> str:
        m = re.search(r"<p[^>]*>(.*?)</p>", html, re.IGNORECASE | re.DOTALL)
        if m:
            text = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            return text[:120]
        return ""

    def _generate_cover(self, title: str, output_path: str):
        cover_cfg = self.config["publish"]["cover"]
        w, h = cover_cfg["width"], cover_cfg["height"]
        bg = cover_cfg["bg_color"]

        img = Image.new("RGB", (w, h), bg)
        draw = ImageDraw.Draw(img)

        font = None
        for fp in ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"]:
            if os.path.exists(fp):
                try:
                    font = ImageFont.truetype(fp, cover_cfg["title_font_size"])
                    break
                except Exception:
                    pass
        if font is None:
            font = ImageFont.load_default()

        lines = []
        line = ""
        for char in title:
            if len(line) >= 14:
                lines.append(line)
                line = char
            else:
                line += char
        if line:
            lines.append(line)

        line_height = cover_cfg["title_font_size"] + 10
        total_h = len(lines) * line_height
        y_start = (h - total_h) // 2

        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=font)
            tw = bbox[2] - bbox[0]
            x = (w - tw) // 2
            draw.text((x, y_start + i * line_height), line, fill="white", font=font)

        img.save(output_path)
        return output_path

    def save_html(self, rewritten: dict) -> str:
        date_str = datetime.now().strftime("%Y-%m-%d")
        slug = re.sub(r"[^\w\u4e00-\u9fff]", "_", rewritten["original_title"][:20])
        date_dir = os.path.join(self.output_dir, date_str)
        os.makedirs(date_dir, exist_ok=True)

        html = self._insert_images(rewritten["html"], rewritten.get("images", []), slug)

        html_path = os.path.join(date_dir, f"{slug}.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)

        print(f"  [publisher] HTML saved: {html_path}")
        return html_path

    def publish(self, rewritten: dict) -> dict:
        html_path = self.save_html(rewritten)
        title = self._extract_title_from_html(rewritten["html"])
        summary = self._extract_summary(rewritten["html"])

        date_str = datetime.now().strftime("%Y-%m-%d")
        slug = re.sub(r"[^\w\u4e00-\u9fff]", "_", rewritten["original_title"][:20])
        cover_dir = os.path.join(self.output_dir, date_str)
        os.makedirs(cover_dir, exist_ok=True)
        cover_path = self._generate_cover(
            title, os.path.join(cover_dir, f"cover_{date_str}_{slug}.png")
        )

        if not self.auto:
            print(f"  [publisher] HTML only (auto=False)")
            print(f'  [publisher] manual:')
            print(f'    npx bun "{self.skill_dir}\\scripts\\wechat-api.ts" "{html_path}" --title "{title}" --summary "{summary}" --cover "{cover_path}"')
            return {"status": "draft", "html_path": html_path, "cover_path": cover_path}

        script = os.path.join(self.skill_dir, "scripts", "wechat-api.ts")
        cmd = [
            "npx", "-y", "bun", script,
            html_path, "--title", title,
            "--summary", summary, "--cover", cover_path,
        ]

        print(f"  [publisher] publishing: {title[:40]}...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=os.path.dirname(html_path))

        if result.returncode == 0:
            print(f"  [publisher] published OK")
            return {"status": "published", "html_path": html_path, "output": result.stdout}
        else:
            print(f"  [publisher] publish FAILED: {result.stderr}")
            return {"status": "failed", "error": result.stderr}


