# -*- coding: utf-8 -*-
"""
公众号仿写智能体 - Web 管理页

用法：
  python web_app.py              # 启动 Web 服务（默认 8002 端口）
  python web_app.py --port 8080  # 指定端口

浏览器打开 http://localhost:8002
"""

import os
import sys
import yaml
import json
import asyncio
import argparse
from datetime import datetime
from typing import Optional

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from fetcher import Fetcher
from dedup import Dedup
from scorer import score_articles
from searcher import Searcher
from rewriter import Rewriter
from publisher import Publisher


# ============================================================
# 初始化
# ============================================================

def load_config() -> dict:
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


app = FastAPI(title="公众号仿写智能体")

# 内存 session（单用户工具，够用）
_session: dict = {}


def get_session() -> dict:
    global _session
    if not _session:
        _session = {
            "created_at": datetime.now().isoformat(),
            "candidates": [],
            "rewrite_results": [],
            "publish_results": [],
        }
    return _session


def reset_session():
    global _session
    _session = {
        "created_at": datetime.now().isoformat(),
        "candidates": [],
        "rewrite_results": [],
        "publish_results": [],
    }


@app.post("/api/reset")
async def reset_all():
    """重置会话并清除去重数据库"""
    reset_session()
    config = load_config()
    db_path = os.path.join(os.path.dirname(__file__), config["paths"]["dedup_db"])
    if os.path.exists(db_path):
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.execute("DELETE FROM processed")
        conn.commit()
        conn.close()
    return {"ok": True, "message": "已重置"}


# ============================================================
# 请求体
# ============================================================

class CollectRequest(BaseModel):
    feed_id: Optional[str] = None
    auto_publish: bool = False


class RewriteRequest(BaseModel):
    selected_ids: Optional[list[str]] = None


class PublishRequest(BaseModel):
    auto_publish: bool = False


# ============================================================
# 页面
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def index():
    tpl_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    with open(tpl_path, "r", encoding="utf-8") as f:
        return f.read()


# ============================================================
# Step 1: 采集
# ============================================================

@app.post("/api/step/collect")
async def step_collect(req: CollectRequest = CollectRequest()):
    config = load_config()
    if req.feed_id:
        config["source"]["feeds"] = [req.feed_id]
    if req.auto_publish:
        config["publish"]["auto"] = True

    n_candidates = config["source"]["candidate_count"]

    # 拉取
    fetcher = Fetcher(config)
    articles = await asyncio.to_thread(fetcher.fetch_latest)
    if not articles:
        return {"ok": False, "error": "无新文章"}

    # 去重
    dedup = Dedup(os.path.join(os.path.dirname(__file__), config["paths"]["dedup_db"]))
    new_articles = await asyncio.to_thread(dedup.filter_new, articles, n_candidates * 3)
    if not new_articles:
        return {"ok": False, "error": "所有文章均已处理"}

    # 评分
    candidates = await asyncio.to_thread(score_articles, new_articles, n_candidates)

    # 存入 session
    session = get_session()
    session["candidates"] = candidates
    session["rewrite_results"] = []
    session["publish_results"] = []
    session["auto_publish"] = req.auto_publish

    return {
        "ok": True,
        "total_fetched": len(articles),
        "new_count": len(new_articles),
        "candidates": [
            {
                "id": c.get("id", ""),
                "title": c.get("title", ""),
                "mp_name": c.get("mp_name", ""),
                "score": c.get("score", 0),
                "content_len": c.get("content_len", 0),
                "url": c.get("url", ""),
            }
            for c in candidates
        ],
    }


# ============================================================
# Step 2: 改写
# ============================================================

@app.post("/api/step/rewrite")
async def step_rewrite(req: RewriteRequest = RewriteRequest()):
    session = get_session()
    candidates = session.get("candidates", [])
    if not candidates:
        return {"ok": False, "error": "请先执行采集"}

    selected_ids = req.selected_ids
    if selected_ids:
        to_rewrite = [c for c in candidates if c["id"] in selected_ids]
    else:
        to_rewrite = candidates

    if not to_rewrite:
        return {"ok": False, "error": "没有可改写的文章"}

    config = load_config()
    searcher = Searcher(config)
    rewriter = Rewriter(config)

    results = []
    for c in to_rewrite:
        try:
            related = await asyncio.to_thread(searcher.search, c)
            result = await asyncio.to_thread(rewriter.rewrite, c, related)
            results.append({**result, "status": "success"})
        except Exception as e:
            results.append({
                "original_title": c.get("title", ""),
                "status": "failed",
                "error": str(e),
            })

    session["rewrite_results"] = results
    return {
        "ok": True,
        "results": [
            {
                "title": r.get("original_title", ""),
                "html": r.get("html", "")[:2000],
                "html_full": r.get("html", ""),
                "status": r["status"],
                "error": r.get("error", ""),
                "related_count": r.get("related_count", 0),
            }
            for r in results
        ],
    }


# ============================================================
# Step 3: 发布
# ============================================================

@app.post("/api/step/publish")
async def step_publish(req: PublishRequest = PublishRequest()):
    config = load_config()
    session = get_session()

    # 优先用请求参数，否则从 session 读取（一键发布时存进去的）
    auto_publish = req.auto_publish or session.get("auto_publish", False)
    if auto_publish:
        config["publish"]["auto"] = True

    rewrite_results = session.get("rewrite_results", [])
    if not rewrite_results:
        return {"ok": False, "error": "请先执行改写"}

    publisher = Publisher(config)
    dedup = Dedup(os.path.join(os.path.dirname(__file__), config["paths"]["dedup_db"]))

    results = []
    for r in rewrite_results:
        if r.get("status") != "success":
            continue
        try:
            pub_result = await asyncio.to_thread(publisher.publish, r)
            dedup.mark_processed(r.get("original_id", ""), r.get("original_title", ""))
            results.append({
                "title": r.get("original_title", ""),
                **pub_result,
            })
        except Exception as e:
            results.append({
                "title": r.get("original_title", ""),
                "status": "failed",
                "error": str(e),
            })

    session["publish_results"] = results
    return {"ok": True, "results": results}


# ============================================================
# 清理临时文件
# ============================================================

class CleanupRequest(BaseModel):
    days: int = 7  # 保留最近 N 天的输出


@app.post("/api/cleanup")
async def cleanup(req: CleanupRequest = CleanupRequest()):
    """清理 output 目录下 N 天前的临时文件（图片、HTML、封面等）"""
    config = load_config()
    output_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), config["paths"]["output_dir"])
    )

    if not os.path.isdir(output_dir):
        return {"ok": False, "error": "输出目录不存在"}

    import shutil
    from datetime import timedelta

    # days=0 表示全部清理，不保留任何文件
    if req.days == 0:
        cutoff = datetime.max  # 所有文件都早于这个时间
    else:
        cutoff = datetime.now() - timedelta(days=req.days)
    deleted = []
    kept = []

    for entry in os.listdir(output_dir):
        entry_path = os.path.join(output_dir, entry)
        if not os.path.isdir(entry_path):
            # 根目录下的文件（如 cover_*.png），按修改时间判断
            mtime = datetime.fromtimestamp(os.path.getmtime(entry_path))
            if mtime < cutoff:
                os.remove(entry_path)
                deleted.append({"name": entry, "type": "file"})
            else:
                kept.append(entry)
            continue

        # 日期目录（如 2026-07-08），按目录名解析日期
        try:
            dir_date = datetime.strptime(entry, "%Y-%m-%d")
            if dir_date < cutoff:
                shutil.rmtree(entry_path)
                deleted.append({"name": entry, "type": "dir"})
            else:
                kept.append(entry)
        except ValueError:
            # 非日期格式的目录，按修改时间判断
            mtime = datetime.fromtimestamp(os.path.getmtime(entry_path))
            if mtime < cutoff:
                shutil.rmtree(entry_path)
                deleted.append({"name": entry, "type": "dir"})
            else:
                kept.append(entry)

    return {
        "ok": True,
        "deleted": deleted,
        "deleted_count": len(deleted),
        "kept": kept,
        "retention_days": req.days,
    }


# ============================================================
# 管理采集接口
# ============================================================

WE_MP_RSS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "we-mp-rss-app"))
WE_MP_RSS_DB = os.path.join(WE_MP_RSS_DIR, "data", "db.db")
WE_MP_RSS_CONFIG = os.path.join(WE_MP_RSS_DIR, "config.yaml")
WE_MP_RSS_PORT = 8001


def _check_service_running() -> bool:
    """检查 we-mp-rss 服务是否在运行"""
    import requests
    try:
        resp = requests.get(f"http://127.0.0.1:{WE_MP_RSS_PORT}/", timeout=3)
        return resp.status_code < 500
    except Exception:
        return False


def _get_we_mp_rss_pid() -> Optional[int]:
    """获取 we-mp-rss 进程 PID"""
    import subprocess
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             f"Get-Process python -ErrorAction SilentlyContinue | Where-Object {{ $_.MainWindowTitle -eq '' }} | Select-Object Id, CommandLine -ErrorAction SilentlyContinue"],
            capture_output=True, text=True, timeout=5
        )
        # 简单方式：查找监听 8001 端口的进程
        result2 = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, timeout=5
        )
        for line in result2.stdout.splitlines():
            if f":{WE_MP_RSS_PORT}" in line and "LISTENING" in line:
                parts = line.strip().split()
                if parts:
                    return int(parts[-1])
    except Exception:
        pass
    return None


class ServiceAction(BaseModel):
    action: str  # "start" or "stop"


@app.post("/api/admin/service")
async def manage_service(req: ServiceAction):
    """启动或停止 we-mp-rss 采集服务"""
    if req.action == "status":
        running = _check_service_running()
        pid = _get_we_mp_rss_pid() if running else None
        return {"ok": True, "running": running, "pid": pid}

    if req.action == "start":
        if _check_service_running():
            return {"ok": False, "error": "服务已在运行中"}
        try:
            import subprocess
            # 使用 Start-Process 隐藏窗口启动
            startup_script = f'''
Start-Process -WindowStyle Hidden -FilePath "python" -ArgumentList "-W", "ignore::DeprecationWarning", "main.py", "-job", "True", "-init", "False" -WorkingDirectory "{WE_MP_RSS_DIR}"
'''
            subprocess.run(
                ["powershell", "-Command", startup_script],
                capture_output=True, text=True, timeout=10
            )
            # 等待几秒检查是否启动成功
            import time
            time.sleep(3)
            if _check_service_running():
                return {"ok": True, "message": "服务已启动"}
            else:
                return {"ok": False, "error": "服务启动失败，请检查日志"}
        except Exception as e:
            return {"ok": False, "error": f"启动失败: {str(e)}"}

    if req.action == "stop":
        pid = _get_we_mp_rss_pid()
        if not pid:
            return {"ok": False, "error": "未找到运行中的服务"}
        try:
            import subprocess
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                          capture_output=True, text=True, timeout=5)
            import time
            time.sleep(2)
            if not _check_service_running():
                return {"ok": True, "message": f"服务已停止 (PID: {pid})"}
            else:
                return {"ok": False, "error": "停止失败，进程仍存在"}
        except Exception as e:
            return {"ok": False, "error": f"停止失败: {str(e)}"}

    return {"ok": False, "error": "未知操作"}


@app.get("/api/admin/config")
async def get_config():
    """获取 we-mp-rss 配置（隐藏敏感信息）"""
    try:
        with open(WE_MP_RSS_CONFIG, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        # 隐藏敏感信息
        hide_keys = ["secret", "db", "redis", "notice", "safe", "cascade"]
        for key in hide_keys:
            if key in config:
                config[key] = "***"
        return {"ok": True, "config": config}
    except Exception as e:
        return {"ok": False, "error": str(e)}


class UpdateConfigRequest(BaseModel):
    key: str
    value: str


@app.post("/api/admin/config")
async def update_config(req: UpdateConfigRequest):
    """更新 we-mp-rss 配置项"""
    try:
        with open(WE_MP_RSS_CONFIG, "r", encoding="utf-8") as f:
            content = f.read()

        # 简单的键值替换（适用于顶层配置）
        import re
        # 匹配 key: value 或 key: ${ENV:-default} 格式
        pattern = rf'^(\s*{re.escape(req.key)}\s*:\s*).*$'
        replacement = rf'\g<1>{req.value}'
        new_content = re.sub(pattern, replacement, content, flags=re.MULTILINE)

        if new_content == content:
            return {"ok": False, "error": f"未找到配置项: {req.key}"}

        with open(WE_MP_RSS_CONFIG, "w", encoding="utf-8") as f:
            f.write(new_content)

        return {"ok": True, "message": f"已更新 {req.key} = {req.value}，重启服务后生效"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/admin/feeds")
async def get_feeds_detail():
    """获取公众号列表（含文章数）"""
    import sqlite3
    try:
        with sqlite3.connect(WE_MP_RSS_DB) as conn:
            feeds = conn.execute(
                "SELECT f.id, f.mp_name, f.mp_cover, f.status, f.sync_time, "
                "COUNT(a.id) as article_count "
                "FROM feeds f LEFT JOIN articles a ON f.id = a.mp_id "
                "GROUP BY f.id ORDER BY f.mp_name"
            ).fetchall()
        return {
            "ok": True,
            "feeds": [
                {
                    "id": r[0],
                    "mp_name": r[1],
                    "mp_cover": r[2],
                    "status": r[3],
                    "sync_time": r[4],
                    "article_count": r[5],
                }
                for r in feeds
            ]
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


class DeleteFeedRequest(BaseModel):
    feed_id: str


@app.post("/api/admin/feeds/delete")
async def delete_feed(req: DeleteFeedRequest):
    """删除公众号订阅"""
    import sqlite3
    try:
        with sqlite3.connect(WE_MP_RSS_DB) as conn:
            conn.execute("DELETE FROM feeds WHERE id = ?", (req.feed_id,))
            conn.execute("DELETE FROM articles WHERE mp_id = ?", (req.feed_id,))
        return {"ok": True, "message": f"已删除公众号: {req.feed_id}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/admin/auth-status")
async def get_auth_status():
    """获取微信授权状态"""
    import sqlite3
    try:
        with open(WE_MP_RSS_CONFIG, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        token_expire_minutes = config.get("token_expire_minutes", 4320)
        # 处理 ${ENV:-default} 格式的环境变量占位符
        if isinstance(token_expire_minutes, str):
            import re
            m = re.search(r':-(\d+)', token_expire_minutes)
            token_expire_minutes = int(m.group(1)) if m else 4320

        with sqlite3.connect(WE_MP_RSS_DB) as conn:
            # 检查 users 表中的授权信息
            users = conn.execute(
                "SELECT username, mp_name, status, sync_time, update_time FROM users WHERE status IS NOT NULL"
            ).fetchall()

            # 检查最新的文章同步时间来判断授权是否有效
            latest_sync = conn.execute(
                "SELECT MAX(sync_time) FROM feeds WHERE status = 1"
            ).fetchone()[0]

        now = datetime.now().timestamp()
        auth_info = []
        for u in users:
            auth_info.append({
                "username": u[0],
                "mp_name": u[1],
                "status": u[2],
                "sync_time": u[3],
                "update_time": u[4],
            })

        # 判断授权是否过期（如果最新同步时间超过 3 天，可能已过期）
        auth_expired = False
        if latest_sync:
            hours_since_sync = (now - latest_sync) / 3600
            if hours_since_sync > 72:  # 3 天
                auth_expired = True

        return {
            "ok": True,
            "auth_info": auth_info,
            "token_expire_minutes": token_expire_minutes,
            "latest_sync_time": latest_sync,
            "auth_expired": auth_expired,
            "manage_url": f"http://127.0.0.1:{WE_MP_RSS_PORT}",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/admin/auto-login")
async def auto_login(request: Request):
    """自动登录 we-mp-rss 并跳转到管理页面（免输入密码）"""
    import requests as req
    try:
        resp = req.post(
            f"http://127.0.0.1:{WE_MP_RSS_PORT}/api/v1/wx/auth/login",
            data={"username": "lin", "password": "admin@123"},
            timeout=5,
        )
        body = resp.json()
        token = body.get("data", {}).get("access_token")
        if not token:
            return {"ok": False, "error": "登录失败，未获取到令牌"}
        # 使用请求的主机地址，支持云端部署
        host = request.headers.get("host", f"127.0.0.1:{WE_MP_RSS_PORT}")
        relay_url = f"http://{host.split(':')[0]}:8001/static/relay.html?token={token}"
        return RedirectResponse(url=relay_url)
    except Exception as e:
        return {"ok": False, "error": f"自动登录失败: {str(e)}"}


# ============================================================
# 辅助接口
# ============================================================

@app.get("/api/status")
async def get_status():
    session = get_session()
    return {
        "ok": True,
        "has_candidates": len(session.get("candidates", [])) > 0,
        "has_rewrites": len(session.get("rewrite_results", [])) > 0,
        "has_publishes": len(session.get("publish_results", [])) > 0,
        "candidate_count": len(session.get("candidates", [])),
        "rewrite_count": len(session.get("rewrite_results", [])),
        "publish_count": len(session.get("publish_results", [])),
        "created_at": session.get("created_at", ""),
    }


@app.get("/api/feeds")
async def get_feeds():
    import sqlite3
    db_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "we-mp-rss-app", "data", "db.db")
    )
    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT id, mp_name FROM feeds WHERE status=1 ORDER BY mp_name"
            ).fetchall()
        return {"ok": True, "feeds": [{"id": r[0], "name": r[1]} for r in rows]}
    except Exception as e:
        return {"ok": False, "feeds": [], "error": str(e)}


# ============================================================
# 启动
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="公众号仿写智能体 Web 管理")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8002)
    args = parser.parse_args()

    print("=" * 50)
    print("  公众号仿写智能体 - Web 管理")
    print(f"  http://{args.host}:{args.port}")
    print("=" * 50)

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port)
