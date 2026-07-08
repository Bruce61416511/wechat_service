# -*- coding: utf-8 -*-
"""
公众号仿写智能体 主入口

用法：
  python main.py                     # 手动触发
  python main.py --auto              # 自动发布
  python main.py --feed-id MP_WXS_3271041950
"""

import os
import sys
import yaml
import argparse
from datetime import datetime

# Windows 终端 UTF-8
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from fetcher import Fetcher
from dedup import Dedup
from searcher import Searcher
from rewriter import Rewriter
from publisher import Publisher


def load_config(config_path: str) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(description="公众号仿写智能体")
    parser.add_argument("--auto", action="store_true", help="自动发布到公众号草稿箱")
    parser.add_argument("--feed-id", type=str, help="仅监控指定公众号")
    parser.add_argument("--config", type=str, default="config.yaml", help="配置文件路径")
    args = parser.parse_args()

    config_path = os.path.join(os.path.dirname(__file__), args.config)
    config = load_config(config_path)
    if args.auto:
        config["publish"]["auto"] = True
    if args.feed_id:
        config["source"]["feeds"] = [args.feed_id]

    print("=" * 50)
    print(f"  [Agent] 公众号仿写智能体")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    mode = "自动发布" if config["publish"]["auto"] else "仅生成HTML"
    print(f"  模式: {mode}")
    print("=" * 50)

    # 1. 拉取
    print("\n[1/5] 拉取最新文章...")
    fetcher = Fetcher(config)
    articles = fetcher.fetch_latest()

    if not articles:
        print("  无新文章，退出")
        return

    # 2. 去重
    print("\n[2/5] 去重...")
    dedup = Dedup(os.path.join(os.path.dirname(__file__), config["paths"]["dedup_db"]))
    candidates = dedup.filter_new(articles, config["source"]["candidate_count"])

    if not candidates:
        print("  所有文章均已处理，退出")
        return

    print(f"  候选文章: {len(candidates)} 篇")
    for c in candidates:
        print(f"    - {c.get('title', '?')[:50]}")

    # 3. 检索 + 改写 + 发布
    print("\n[3/5] 语义检索历史文章...")
    searcher = Searcher(config)
    rewriter = Rewriter(config)
    publisher = Publisher(config)

    for i, candidate in enumerate(candidates):
        print(f"\n--- 处理 {i+1}/{len(candidates)} ---")

        related = searcher.search(candidate)
        if related:
            print(f"  找到 {len(related)} 篇相关历史文章:")
            for r in related:
                print(f"    [{r['similarity']:.2f}] {r['title'][:40]} ({r['mp_name']})")
        else:
            print("  无相关历史文章")

        # 4. 改写
        print(f"\n[4/5] AI 改写...")
        try:
            result = rewriter.rewrite(candidate, related)
        except Exception as e:
            print(f"  [ERROR] 改写失败: {e}")
            continue

        # 5. 发布
        print(f"\n[5/5] 生成并发布...")
        pub_result = publisher.publish(result)

        dedup.mark_processed(candidate.get("id", ""), candidate.get("title", ""))

    print("\n" + "=" * 50)
    print("  [Agent] 完成")
    print("=" * 50)


if __name__ == "__main__":
    main()
