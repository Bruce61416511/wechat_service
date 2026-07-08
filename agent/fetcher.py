# -*- coding: utf-8 -*-
"""从 we-mp-rss 拉取文章"""

import requests
import xml.etree.ElementTree as ET
import html as html_lib
from typing import Optional


class Fetcher:
    def __init__(self, config: dict):
        self.base_url = config["source"]["base_url"].rstrip("/")
        self.api_base = config["source"]["api_base"]
        self.fetch_limit = config["source"]["fetch_limit"]
        self.candidate_count = config["source"]["candidate_count"]
        self.feeds = config["source"].get("feeds", [])
        self._feed_ids: Optional[list] = None

    def _get_feed_ids(self) -> list[str]:
        """获取所有监控的公众号ID"""
        if self._feed_ids is not None:
            return self._feed_ids

        if self.feeds:
            self._feed_ids = self.feeds
            return self._feed_ids

        # 从数据库中直接查
        import sqlite3
        import os

        db_path = os.path.join(
            os.path.dirname(__file__), "..", "we-mp-rss-app", "data", "db.db"
        )
        with sqlite3.connect(os.path.abspath(db_path)) as conn:
            rows = conn.execute(
                "SELECT id FROM feeds WHERE status=1 ORDER BY created_at"
            ).fetchall()
            self._feed_ids = [r[0] for r in rows]
        return self._feed_ids

    def _parse_rss_xml(self, xml_text: str) -> list[dict]:
        """解析 RSS XML 提取文章列表"""
        items = []
        try:
            root = ET.fromstring(xml_text)
            channel = root.find("channel")
            if channel is None:
                return items
            for item in channel.findall("item"):
                aid = item.findtext("id", "")
                title = item.findtext("title", "")
                desc = item.findtext("description", "")
                link = item.findtext("link", "") or item.findtext("guid", "")
                pub_date = item.findtext("pubDate", "")
                enclosure = item.find("enclosure")
                pic_url = enclosure.get("url", "") if enclosure is not None else ""

                # content:encoded
                content_elem = item.find(
                    "{http://purl.org/rss/1.0/modules/content/}encoded"
                )
                content = content_elem.text if content_elem is not None else ""

                items.append(
                    {
                        "id": aid,
                        "title": html_lib.unescape(title),
                        "description": html_lib.unescape(desc),
                        "url": link,
                        "pic_url": pic_url,
                        "updated": pub_date,
                        "content": content,
                    }
                )
        except ET.ParseError as e:
            print(f"  [fetcher] XML 解析失败: {e}")
        return items

    def _get_articles_from_feed(self, feed_id: str, mp_name: str = "") -> list[dict]:
        """从 RSS 拉取文章列表"""
        url = f"{self.base_url}/rss/{feed_id}?limit={self.fetch_limit}"
        try:
            resp = requests.get(url, timeout=30)
            resp.encoding = "utf-8"
            items = self._parse_rss_xml(resp.text)
            for item in items:
                item["mp_id"] = feed_id
                item["mp_name"] = mp_name
            return items
        except Exception as e:
            print(f"  [fetcher] 拉取 {feed_id} 失败: {e}")
            return []

    def _get_mp_names(self) -> dict[str, str]:
        """获取公众号ID到名称的映射"""
        import sqlite3
        import os

        db_path = os.path.join(
            os.path.dirname(__file__), "..", "we-mp-rss-app", "data", "db.db"
        )
        with sqlite3.connect(os.path.abspath(db_path)) as conn:
            rows = conn.execute("SELECT id, mp_name FROM feeds WHERE status=1").fetchall()
            return {r[0]: r[1] for r in rows}

    def fetch_latest(self) -> list[dict]:
        """拉取所有监控公众号最新文章，按发布时间倒序"""
        feed_ids = self._get_feed_ids()
        mp_names = self._get_mp_names()

        print(f"[fetcher] 监控 {len(feed_ids)} 个公众号")

        all_items = []
        for fid in feed_ids:
            name = mp_names.get(fid, fid)
            items = self._get_articles_from_feed(fid, name)
            all_items.extend(items)
            print(f"  {name}: {len(items)} 篇")

        all_items.sort(key=lambda x: x.get("updated", ""), reverse=True)
        print(f"[fetcher] 共 {len(all_items)} 篇文章")

        return all_items[:self.candidate_count * 3]
