# -*- coding: utf-8 -*-
"""去重模块：记录已处理文章，防止重复改写"""

import sqlite3
import os


class Dedup:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS processed (
                    article_id TEXT PRIMARY KEY,
                    title TEXT,
                    rewritten_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

    def is_processed(self, article_id: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM processed WHERE article_id = ?", (article_id,)
            ).fetchone()
            return row is not None

    def mark_processed(self, article_id: str, title: str = ""):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO processed (article_id, title) VALUES (?, ?)",
                (article_id, title),
            )

    def filter_new(self, articles: list[dict], candidate_count: int) -> list[dict]:
        """过滤出未处理的文章，返回最多 candidate_count 篇"""
        new_articles = []
        for art in articles:
            aid = art.get("id", "")
            if not self.is_processed(aid):
                new_articles.append(art)
                if len(new_articles) >= candidate_count:
                    break

        skipped = len(articles) - len(new_articles)
        print(f"[dedup] {len(new_articles)} 篇新文章, 跳过 {skipped} 篇已处理")
        return new_articles
