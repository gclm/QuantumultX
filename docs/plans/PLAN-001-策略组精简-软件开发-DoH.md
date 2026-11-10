# PLAN-001 策略组精简 + 软件开发组 + DoH

| 状态 | 版本 | 日期 | 上游依据 | 变更摘要 |
|---|---|---|---|---|
| 已完成 | 1.0 | 2026-11-10 | 用户会话决策（plan mode 批准） | 17 组精简为 13 组；新增软件开发组；启用 DoH |

## 目标

1. 精简策略组体系：删除不再使用的组，候选模板统一，全球加速置顶。
2. 新增「软件开发」组收拢开发流量（GitHub/CloudFront/Docker/npm/PyPI/Jetbrains/HuggingFace/Homebrew）。
3. DNS 启用 DoH（加密解析，抗污染）：arkdo 优选 + 阿里 223.5.5.5 回退。

## 旧→新 对照

| 旧组（17） | 去向 |
|---|---|
| 全球加速 | 保留，置顶；候选移除 proxy |
| 苹果服务 | 组删除；Apple.list 规则保留 `force-policy=direct`（行为不变：默认直连） |
| AI服务 | 保留；候选统一模板（美国节点前置） |
| 苹果代理 | 保留；候选统一模板（美国节点前置） |
| TikTok / 交易所 | 组 + 分流规则 + policy_map 映射 + 远程引用 + 快照 全删 |
| 哔哩哔哩 | 组删除（核实零规则引用，空壳残留） |
| Spotify | 组 + 分流规则 + 远程引用 + 快照 全删 |
| 国际媒体 | 保留；候选统一模板（台湾节点前置，移除视频节点/proxy） |
| 兜底分流 | 保留；候选 = 模板 + direct |
| 视频节点 | 组删除（与手动选择成员完全相同，冗余槽位） |
| 新增：软件开发 | GitHub.list、CloudFront.list 迁入 + 新增 Docker/Npmjs/Python/Jetbrains.list + 本地规则 huggingface.co/hf.co/brew.sh/ghcr.io |

新顺序（13 组）：全球加速、软件开发、AI服务、苹果代理、国际媒体、兜底分流、手动选择、美国节点、香港节点、台湾节点、日本节点、狮城节点、自动选择。

## 关键决策

- **proxy 候选全部移除**：proxy 是 App 全局游标，「手动选择」组等价覆盖该能力，组列表更干净。
- **开发远程规则声明收敛在底包** `profiles/base.conf` [filter_remote]（与 GitHub/CloudFront 原声明同层），config.yaml 不重复声明（防产物重复行）。
- **HuggingFace/Homebrew 无 blackmatrix7 上游列表**，走本地规则 `rules/custom.list`（host-suffix 四条）。
- **custom.list 的 `host-keyword,github` 从全球加速改挂软件开发**，与 GitHub.list 目标一致，避免双组指向。
- **DoH**：`doh-server = https://arkdo.ddd.oaifree.com/query-dns, https://223.5.5.5/dns-query`；UDP `server=` 行保留作 DoH 失败回退 + DoH 域名 bootstrap；`no-ipv6` 与微信系 DNSPod 定向不动。
- TG/X 走 Proxy.list → 全球加速（本次不动；blackmatrix7 有 Telegram/Twitter 列表，需要时单独成组）。

## 验证

- 构建零报错（内置 lint [policy]≥5）。
- 产物 grep：六个被删组名零引用（防裸挂）；[dns] 含双 DoH；[filter_remote] 无 Binance/TikTok/Spotify、Apple.list→direct、开发类→软件开发。
- DoH 端点 RFC8484 curl 活性验证。
- 未覆盖：QX 真机导入验证（用户完成）。
