# -*- coding: utf-8 -*-
"""内容质量评分：正文长度 + 来源多样性"""

import re


def score_articles(articles: list[dict], top_k: int = 5) -> list[dict]:
    """对文章打分并返回 Top K，确保来源多样性"""
    if not articles:
        return []

    scored = []
    for art in articles:
        content = art.get("content", "") or ""
        title = art.get("title", "") or ""
        desc = art.get("description", "") or ""

        # 正文长度分 (60%)
        text = re.sub(r"<[^>]+>", "", content).strip()
        content_len = len(text)
        if content_len >= 3000:
            len_score = 100
        elif content_len >= 1500:
            len_score = 85
        elif content_len >= 800:
            len_score = 60
        elif content_len >= 300:
            len_score = 30
        else:
            len_score = 10

        # 标题+描述丰富度分 (40%)
        title_len = len(title)
        desc_len = len(desc)
        if desc_len > 80:
            meta_score = 100
        elif desc_len > 30:
            meta_score = 70
        elif desc_len > 10:
            meta_score = 40
        else:
            meta_score = 10

        total = len_score * 0.6 + meta_score * 0.4
        scored.append({**art, "score": round(total, 1), "content_len": content_len})

    # 按分数排序
    scored.sort(key=lambda x: x["score"], reverse=True)

    # 来源多样性：每个公众号只取最高分一篇
    seen_sources = set()
    diverse = []
    for art in scored:
        mp_id = art.get("mp_id", art.get("id", ""))
        if mp_id not in seen_sources:
            diverse.append(art)
            seen_sources.add(mp_id)
            if len(diverse) >= top_k:
                break

    # 如果不够 top_k，从剩余中补齐
    if len(diverse) < top_k:
        for art in scored:
            if art not in diverse:
                diverse.append(art)
                if len(diverse) >= top_k:
                    break

    return diverse[:top_k]
