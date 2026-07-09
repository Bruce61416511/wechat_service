# 🔄 公众号内容仿写发布流水线

> **创建时间**: 2026-07-08 | **最后更新**: 2026-07-08
> **目标**: 采集对标公众号文章 → AI 改写 → 发布到自有公众号，全链路自动化

---

## 一、整体架构

 + "" + mermaid
flowchart LR
    subgraph 采集层["采集层 ✅"]
        A[we-mp-rss<br/>10个公众号] -->|RSS XML| B[467篇文章<br/>440篇有正文]
        A -->|定时轮询<br/>10min| B
    end

    subgraph Agent层["Agent 改写层 ✅"]
        B -->|Fetcher<br/>拉取最新| C[20篇候选]
        C -->|Dedup<br/>去重| D[未处理文章]
        D -->|Scorer<br/>质量评分| E[Top 5 精选]
        E -->|Searcher<br/>TF-IDF检索| F[关联历史文章]
        F -->|Rewriter<br/>LLM改写| G[HTML文章]
    end

    subgraph 发布层["发布层 ✅"]
        G -->|图片去水印| H[处理图片]
        H -->|baoyu-post-to-wechat| I[(公众号草稿箱)]
    end

    style A fill:#4CAF50,color:#fff
    style G fill:#FF9800,color:#fff
    style I fill:#1890FF,color:#fff
 + "" + 

---

## 二、we-mp-rss 采集规则

### 2.1 部署信息

| 项目 | 详情 |
|------|------|
| 仓库 | https://github.com/rachelos/we-mp-rss |
| Fork 地址 | https://github.com/Bruce61416511/wechat_service |
| 部署路径 | D:\AI workspace\workspace\微信公众号\we-mp-rss-app |
| Python 版本 | 3.14.4 |
| 数据库 | SQLite (data/db.db) |
| 管理界面 | http://localhost:8001 |
| 登录账号 | lin / admin@123 |
| 启动命令 | python main.py -job True -init False |

### 2.2 已订阅公众号（10个）

| # | 公众号 | ID | 文章数 | 正文率 |
|---|--------|-----|--------|--------|
| 1 | 机器之心 | MP_WXS_3073282833 | 55 | 100% |
| 2 | 量子位 | MP_WXS_3236757533 | 59 | 100% |
| 3 | 新智元 | MP_WXS_3271041950 | 90+ | 100% |
| 4 | 36氪 | MP_WXS_3264997043 | 90 | 100% |
| 5 | AI科技评论 | MP_WXS_3098132220 | 50+ | 100% |
| 6 | 夕小瑶科技说 | MP_WXS_3207765945 | 50+ | 100% |
| 7 | AINLP | MP_WXS_2398933301 | 50+ | 100% |
| 8 | PaperWeekly | MP_WXS_3201788143 | 50+ | 100% |
| 9 | Founder Park | MP_WXS_3895742803 | 50+ | 100% |
| 10 | 腾讯研究院 | MP_WXS_2399148061 | 50+ | 100% |

### 2.3 自动更新机制

| 配置项 | 值 | 说明 |
|--------|-----|------|
| enable_job | True | 后台定时任务 |
| interval | 10 分钟 | 新文章检测轮询 |
| gather.content | True | 开启正文采集 |
| gather.model | api | API 模式（比 web 快 10 倍） |
| gather.content_auto_interval | 1 分钟 | 正文自动采集间隔 |
| 微信授权 | 7/12 到期 | 需定期扫码续期 |

### 2.4 对外接口

| 接口 | 用途 | 示例 |
|------|------|------|
| RSS Feed | 文章列表+全文 XML | http://localhost:8001/rss/MP_WXS_3271041950 |
| 文章详情 API | JSON 格式文章 | http://localhost:8001/api/v1/wx/articles/{id} |
| Web 阅读 | 浏览器阅读 | http://localhost:8001/views/article/{id} |

### 2.5 代码修改记录

| 文件 | 修改 | 原因 |
|------|------|------|
| main.py | Python 3.14 asyncio 兼容 + UTF-8 | 废弃 API 修复 |
| driver/wxarticle.py | proxy_images 删除空 img 标签 | 微信编辑器占位符导致破损图 |
| iews/article_detail.py | status 过滤放宽到 [1,6] | 某些文章 status=6 |
| iews/base.py | isProxy=True | 启用图片代理 |
| pis/res.py | 去掉 https→http 强制转换 | 图片 400 错误 |

---

## 三、Agent 处理流程

### 3.1 文件结构

`
agent/
├── config.yaml          # 配置文件（LLM、采集源、发布参数）
├── main.py              # 主入口
├── fetcher.py           # 从 we-mp-rss RSS 拉文章
├── dedup.py             # SQLite 去重
├── scorer.py            # 内容质量评分 + 来源多样性
├── searcher.py          # TF-IDF 语义检索历史文章
├── rewriter.py          # LLM 改写
├── publisher.py         # 图片去水印 + 生成 HTML + 调 wechat-api.ts 发布
├── prompt.md            # 改写 Prompt 模板
└── processed.db         # 去重数据库（自动生成）
`

### 3.2 完整处理链路

`
                     ┌──────────────────────────────────────────┐
Step 1: Fetcher      │  从 10 个公众号 RSS 拉最新 20 篇/号     │
                     │  返回 200 篇，按发布时间倒序             │
                     └──────────────┬───────────────────────────┘
                                    ↓
                     ┌──────────────┴───────────────────────────┐
Step 2: Dedup        │  SQLite 查 processed.db                 │
                     │  跳过已处理，保留未处理文章              │
                     └──────────────┬───────────────────────────┘
                                    ↓
                     ┌──────────────┴───────────────────────────┐
Step 3: Scorer       │  内容质量打分（正文长度 60% + 描述 40%）│
                     │  来源多样性过滤（每号限 1 篇）           │
                     │  → Top 5 精选文章                        │
                     └──────────────┬───────────────────────────┘
                                    ↓
                     ┌──────────────┴───────────────────────────┐
Step 4: Searcher     │  加载 431 篇历史文章库                  │
                     │  jieba 分词 + TF-IDF 向量化              │
                     │  余弦相似度检索 → 每篇 Top 3 关联文章   │
                     └──────────────┬───────────────────────────┘
                                    ↓
                     ┌──────────────┴───────────────────────────┐
Step 5: Rewriter     │  组装 Prompt：目标文章 + 关联文章 + 图片│
                     │  调 LLM API（DeepSeek/OpenAI）           │
                     │  返回 HTML 格式仿写文章                  │
                     └──────────────┬───────────────────────────┘
                                    ↓
                     ┌──────────────┴───────────────────────────┐
Step 6: Publisher    │  下载原文图片 → 裁剪底部 18%+右侧 12%   │
                     │  跳过第一张品牌头图                      │
                     │  插入图片到 HTML                         │
                     │  生成封面图                              │
                     │  调 wechat-api.ts → 公众号草稿箱         │
                     │  标记已处理 → processed.db               │
                     └──────────────────────────────────────────┘
`

### 3.3 内容质量评分规则

| 维度 | 权重 | 评分标准 |
|------|------|----------|
| 正文长度 | 60% | ≥3000字=100分, 1500-3000=85, 800-1500=60, 300-800=30, <300=10 |
| 描述丰富度 | 40% | >80字=100, 30-80=70, 10-30=40, <10=10 |
| 来源多样性 | 过滤 | 同一公众号只取最高分 1 篇 |

### 3.4 语义检索

- **引擎**：TF-IDF + 余弦相似度
- **分词**：jieba 中文分词
- **索引**：431 篇历史文章标题+描述
- **阈值**：相似度 ≥ 0.3
- **返回**：每篇候选最多 3 篇关联文章

### 3.5 LLM 改写

| 配置项 | 值 | 说明 |
|--------|-----|------|
| Provider | DeepSeek | 支持 OpenAI / Ollama |
| Model | deepseek-chat | |
| Temperature | 0.8 | 创造性 |
| Max Tokens | 4096 | |
| 输出格式 | HTML | 微信兼容标签 |
| 是否配图 | 是 | [IMG:n] 占位符 |
| 字数要求 | 1500-2500 字 | |

### 3.6 图片处理

| 策略 | 说明 |
|------|------|
| 跳过第一张 | 第一张通常是品牌头图，logo 最明显 |
| 底部裁剪 | 裁掉 18%，去除底部水印条 |
| 右侧裁剪 | 裁掉 12%，去除右下角 logo |
| RGBA 兼容 | PNG 透明通道转 RGB 后再存 JPEG |
| 本地缓存 | 处理后图片存 output/imgs_*/ |

### 3.7 发布工具

| 项目 | 详情 |
|------|------|
| 工具 | baoyu-post-to-wechat |
| 仓库 | https://github.com/macrochen/baoyu-post-to-wechat |
| 安装路径 | C:\Users\lin\.codex\skills\baoyu-post-to-wechat\ |
| 发布脚本 | scripts/wechat-api.ts |
| 方式 | API 模式（调微信公众平台 API） |
| 凭证 | C:\Users\lin\.baoyu-skills\.env |

---

## 四、使用方式

### 4.1 命令行

`powershell
# 进入工作目录
cd "D:\AI workspace\workspace\微信公众号"

# 仅生成 HTML（不发布，先看效果）
python agent/main.py

# 生成 + 自动发布到公众号草稿箱
python agent/main.py --auto

# 只关注新智元
python agent/main.py --feed-id MP_WXS_3271041950 --auto

# 只关注机器之心
python agent/main.py --feed-id MP_WXS_3073282833 --auto
`

### 4.2 定时自动（云端部署后）

`ash
# crontab 每 30 分钟跑一轮
*/30 * * * * cd /app && python agent/main.py --auto >> logs/agent.log 2>&1
`

### 4.3 手动发布已有 HTML

`powershell
npx bun "C:\Users\lin\.codex\skills\baoyu-post-to-wechat\scripts\wechat-api.ts" 
  "output\2026-07-08\文章.html" 
  --title "标题" --summary "摘要" 
  --cover "output\2026-07-08\cover_xxx.png"
`

---

## 五、配置清单

### 5.1 公众号凭证

| 配置项 | 值 |
|--------|-----|
| AppID | wx89ad7debfda55a8d |
| AppSecret | ab31daf203889373b3e29478285830ee |
| IP 白名单 | 动态 IP，发布前需确认 |

### 5.2 LLM 配置

| 配置项 | 值 |
|--------|-----|
| Provider | deepseek |
| API Key | 已配置（gent/config.yaml） |
| Model | deepseek-chat |
| Base URL | https://api.deepseek.com/v1 |

### 5.3 路径清单

| 路径 | 用途 |
|------|------|
| we-mp-rss-app/ | 采集服务 |
| gent/ | 改写 Agent |
| output/ | 输出目录（HTML + 图片） |
| gent/processed.db | 去重库 |

---

## 六、风险与注意事项

| 风险 | 应对 |
|------|------|
| 微信授权 7/12 到期 | 提前续期，否则抓取停止 |
| 动态 IP 变动 | 发布前检查 IP，添加到白名单 |
| 公众号 API 调用限制 | 控制发布频率 |
| AI 改写查重风险 | 确保改写率 > 70%，保留审核环节 |
| GitHub 被墙 | 开 VPN 后 push |

---

## 七、版本记录

| 日期 | 更新 |
|------|------|
| 2026-07-08 | 初始部署 we-mp-rss，订阅 10 个公众号 |
| 2026-07-08 | 修复图片渲染、Python 3.14 兼容性 |
| 2026-07-08 | 安装 baoyu-post-to-wechat，打通发布链路 |
| 2026-07-08 | 完成 Agent 全链路：采集→去重→评分→检索→改写→发布 |
| 2026-07-08 | 图片去水印（裁剪底部+右侧、跳过品牌头图） |
| 2026-07-08 | 内容质量评分 + 来源多样性筛选 |
