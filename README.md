# 公众号仿写发布流水线

> 本地 Windows 部署版 | 重启后的完整操作指南

---

## 一、电脑重启后启动服务

### Step 1: 启动 we-mp-rss 采集服务

打开 PowerShell，运行：

`powershell
cd "D:\AI workspace\workspace\微信公众号\we-mp-rss-app"

Start-Process -WindowStyle Hidden -FilePath "python" 
  -ArgumentList "-W", "ignore::DeprecationWarning", "main.py", "-job", "True", "-init", "False" 
  -RedirectStandardError "C:\Users\lin\AppData\Local\Temp\werss-stderr.log" 
  -RedirectStandardOutput "C:\Users\lin\AppData\Local\Temp\werss-stdout.log"
`

验证服务是否启动：

`powershell
Start-Sleep 3
curl.exe -s -o NUL -w "%{http_code}" http://localhost:8001/views/home
# 返回 200 = 成功
`

### Step 2: 检查微信授权是否过期

浏览器打开 http://localhost:8001 登录（lin / admin@123），检查是否需要重新扫码授权。

> ⚠️ 当前授权有效期至 **2026-07-12**，过期后文章抓取会停止。

### Step 3: 确认 IP 白名单

发布到公众号前，确认当前公网 IP 已加入微信 IP 白名单：

`powershell
# 查看当前公网 IP
curl.exe -s ifconfig.me
`

如果 IP 变了，去 [mp.weixin.qq.com](https://mp.weixin.qq.com) → **设置与开发** → **基本配置** → **IP 白名单** 添加。

---

## 二、运行改写 Agent

`powershell
cd "D:\AI workspace\workspace\微信公众号"

# 仅生成 HTML（先看效果，不发布）
python agent/main.py

# 生成 + 自动发布到公众号草稿箱
python agent/main.py --auto
`

Agent 会自动完成：拉取文章 → 去重 → 评分 → 检索 → 改写 → 发布。

---

## 三、登录公众号发表

1. 打开 [mp.weixin.qq.com](https://mp.weixin.qq.com)
2. 左侧菜单 → **内容管理** → **草稿箱**
3. 找到 AI 改写生成的文章（封面是蓝底白字）
4. 检查内容、预览效果
5. 点击 **发表**

---

## 四、常用命令速查

| 操作 | 命令 |
|------|------|
| 启动采集 | Start-Process ... main.py -job True -init False |
| 只生成不改写 | python agent/main.py |
| 改写+发草稿 | python agent/main.py --auto |
| 只看新智元 | python agent/main.py --auto --feed-id MP_WXS_3271041950 |
| 手发已有 HTML | 
px bun ... wechat-api.ts article.html --title "xxx" --cover cover.png |
| 查日志 | Get-Content "C:\Users\lin\AppData\Local\Temp\werss-stdout.log" -Tail 20 |
| 查公网 IP | curl.exe -s ifconfig.me |
| 停止服务 | Get-Process python* \| Stop-Process -Force |

---

## 五、目录结构

`
D:\AI workspace\workspace\微信公众号\
├── README.md                 ← 你在这里
├── 公众号仿写发布流水线.md    ← 完整架构文档
├── .gitignore
├── agent/                    ← 改写 Agent
│   ├── main.py               ← 入口
│   ├── config.yaml           ← LLM 配置
│   ├── prompt.md             ← 改写 Prompt
│   └── ...
├── output/                   ← 改写输出
│   └── 2026-07-08/           ← 按日期分组
└── we-mp-rss-app/            ← 采集服务
`

---

## 六、关键提醒

| 事项 | 周期 | 操作 |
|------|------|------|
| 微信授权续期 | ~3 天 | 登录 http://localhost:8001 扫码 |
| IP 白名单更新 | 每次重启后 | 新增 IP 到 mp.weixin.qq.com |
| 草稿检查 | 每次发布后 | mp.weixin.qq.com → 草稿箱 |
| Git 推送 | 代码修改后 | 开 VPN 手动 push |
