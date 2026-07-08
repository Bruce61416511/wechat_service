# -*- coding: utf-8 -*-
"""LLM 改写模块"""

import os
import re
import requests
from datetime import datetime


class Rewriter:
    def __init__(self, config: dict):
        self.llm = config["llm"]
        self.base_url = config["source"]["base_url"].rstrip("/")
        prompt_path = os.path.join(
            os.path.dirname(__file__), config["paths"]["prompt_template"]
        )
        with open(prompt_path, "r", encoding="utf-8") as f:
            self.system_prompt = f.read()

    def _extract_images(self, html: str) -> list[str]:
        """从 HTML 提取图片 URL，跳过带明显水印的头图"""
        urls = re.findall(r'<img[^>]+src="([^"]+)"', html, re.IGNORECASE)
        valid = [u for u in urls if u.startswith("http") and "mmbiz.qpic.cn" in u]
        # 去重
        seen = set()
        result = []
        for u in valid:
            base = u.split("?")[0]
            if base not in seen:
                seen.add(base)
                result.append(u)
                if len(result) >= 8:
                    break
        # 跳过第一张（通常是品牌头图/标题图，logo 最显眼）
        # 跳过太小的 tracking 像素
        result = result[1:] if len(result) > 1 else result
        return result[:6]

    def _call_llm(self, messages: list[dict]) -> str:
        api_key = self.llm["api_key"]
        model = self.llm["model"]
        base_url = self.llm["base_url"]

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": self.llm.get("temperature", 0.8),
            "max_tokens": self.llm.get("max_tokens", 4096),
        }

        resp = requests.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json=payload,
            timeout=120,
        )
        data = resp.json()

        if "choices" not in data:
            raise Exception(f"LLM call failed: {data}")

        return data["choices"][0]["message"]["content"]

    def rewrite(self, article: dict, related: list[dict]) -> dict:
        title = article.get("title", "unknown")
        mp_name = article.get("mp_name", "unknown")
        content = article.get("content", "") or ""

        content_text = re.sub(r"<[^>]+>", "\n", content)
        content_text = re.sub(r"\n{3,}", "\n\n", content_text).strip()[:6000]

        images = self._extract_images(content)

        related_text = ""
        if related:
            related_text = "\n\n---\n## reference articles\n"
            for i, r in enumerate(related):
                r_content = re.sub(r"<[^>]+>", "\n", r.get("content_html", "") or "")
                r_content = re.sub(r"\n{3,}", "\n\n", r_content).strip()[:2000]
                related_text += f"\n### ref{i+1}: {r['title']} (source: {r['mp_name']}, sim: {r['similarity']:.2f})\n{r_content}\n"

        image_text = ""
        if images:
            image_text = "\n\n## available images (use [IMG:n] to insert)\n"
            for i, url in enumerate(images):
                image_text += f"[IMG:{i}] {url}\n"

        user_message = f"""## target article

title: {title}
source: {mp_name}

body:
{content_text}
{related_text}{image_text}"""

        print(f"  [rewriter] rewriting: {title[:40]}...")
        print(f"  [rewriter] images available: {len(images)}")
        result = self._call_llm(
            [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_message},
            ]
        )

        return {
            "original_title": title,
            "original_id": article.get("id", ""),
            "mp_name": mp_name,
            "html": result,
            "images": images,
            "rewritten_at": datetime.now().isoformat(),
            "related_count": len(related),
        }
