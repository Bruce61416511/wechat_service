# -*- coding: utf-8 -*-
"""语义检索：用 TF-IDF + 余弦相似度搜历史文章"""

import os
import sqlite3
import re
import jieba
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from typing import Optional


class Searcher:
    def __init__(self, config: dict):
        raw_path = config["search"]["db_path"]
        if os.path.isabs(raw_path):
            self.db_path = raw_path
        else:
            self.db_path = os.path.abspath(
                os.path.join(os.path.dirname(__file__), raw_path)
            )

        self.threshold = config["search"]["similarity_threshold"]
        self.top_k = config["search"]["top_k"]
        self.vectorizer: Optional[TfidfVectorizer] = None
        self.articles: list[dict] = []
        self.tfidf_matrix = None
        self._loaded = False

    def _load_articles(self):
        """加载历史文章库"""
        if self._loaded:
            return

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT a.id, a.title, a.description, a.content_html, f.mp_name "
                "FROM articles a JOIN feeds f ON a.mp_id = f.id "
                "WHERE a.status IN (1,6) AND a.content_html IS NOT NULL AND a.content_html != ''"
            ).fetchall()

        self.articles = [
            {
                "id": r[0],
                "title": r[1],
                "description": r[2] or "",
                "content_html": r[3] or "",
                "mp_name": r[4],
            }
            for r in rows
        ]
        print(f"[searcher] 加载 {len(self.articles)} 篇历史文章")

    def _preprocess(self, text: str) -> str:
        """中文文本预处理：去HTML标签 + 分词"""
        text = re.sub(r"<[^>]+>", " ", text or "")
        text = re.sub(r"\s+", " ", text).strip()
        words = jieba.cut(text)
        return " ".join(words)

    def _build_index(self):
        """构建 TF-IDF 索引"""
        if self._loaded:
            return

        self._load_articles()
        docs = [
            self._preprocess(a["title"] + " " + a["description"])
            for a in self.articles
        ]

        self.vectorizer = TfidfVectorizer(max_features=5000)
        self.tfidf_matrix = self.vectorizer.fit_transform(docs)
        self._loaded = True
        print(
            f"[searcher] 索引构建完成, 词汇量: {len(self.vectorizer.vocabulary_)}"
        )

    def search(self, article: dict) -> list[dict]:
        """搜与目标文章相似的历史文章"""
        self._build_index()

        query_text = (
            (article.get("title", "") or "")
            + " "
            + (article.get("description", "") or "")
        )
        query_vec = self.vectorizer.transform([self._preprocess(query_text)])
        similarities = cosine_similarity(query_vec, self.tfidf_matrix)[0]

        results = []
        for i, score in enumerate(similarities):
            if (
                score >= self.threshold
                and self.articles[i]["id"] != article.get("id", "")
            ):
                results.append({**self.articles[i], "similarity": float(score)})

        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[: self.top_k]
