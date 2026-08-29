# QX-Config-Sync 项目文档

> QuantumultX 配置自动构建与同步工具 V6.1

---

## 目录

- [项目概述](#项目概述)
- [项目结构](#项目结构)
- [技术栈](#技术栈)
- [核心功能](#核心功能)
- [使用指南](#使用指南)
- [配置说明](#配置说明)
- [API 参考](#api-参考)
- [自动化部署](#自动化部署)
- [常见问题](#常见问题)

---

## 项目概述

QX-Config-Sync 是一个用于自动构建 QuantumultX 配置文件的开源工具。它通过 YAML 配置文件管理所有规则和策略，支持底包下载、规则注入、远程引用等功能，并通过 GitHub Actions 实现自动化构建和同步。

### 主要特点

- **模块化配置**：使用 YAML 文件统一管理所有配置
- **增量构建**：基于底包进行增量修改，保留原有配置
- **灵活注入**：支持本地文件引用和远程规则引用
- **策略映射**：支持将外部策略组映射到底包真实策略
- **自动化部署**：集成 GitHub Actions 实现定时自动构建
- **规则清洗**：支持黑名单/白名单模式过滤底包内容
- **规则本地化**：远程规则快照进仓库，下载失败自动用旧快照，支持豁免名单
- **三通道分发**：Raw / jsDelivr 镜像 / Cloudflare Workers 反代三份配置同时产出并探活
- **底包快照保护**：上游失效回退快照，快照失效拒绝提交，杜绝空配置覆盖线上
- **质量校验**：下载内容校验（拒空文件/HTML 错误页）+ 提交前 lint
- **通知可切换**：飞书群机器人（默认，支持加签）/ Telegram / 双通道，凭证缺失自动降级
- **自有底包**：ddgksf2013 V269 固化为 `profiles/base.conf`，清理专属信息，无第三方站点单点依赖

---

## 项目结构

```
QuantumultX/
├── .github/
│   └── workflows/
│       └── build.yml           # GitHub Actions 自动构建配置
├── profiles/
│   ├── base.conf              # 自有底包（ddgksf2013 V269 固化 + 专属信息清理）
│   └── config.yaml             # 主配置文件
├── rules/                      # 规则目录
│   ├── custom.list          # 自定义分流规则（个人规则/番茄小说去广告）
│   ├── dev.list             # 开发者工具分流（Cursor/Trae 等）
│   ├── mitm_hosts.list      # MITM hostname 配置
│   ├── rewrites.list        # 重写规则
│   ├── filter_remote/          # [生成] 本地化后的远程分流规则
│   └── rewrite_remote/         # [生成] 本地化后的远程重写规则
├── src/
│   ├── main.py                 # 主入口文件
│   ├── qx_core.py              # 核心配置管理类
│   └── notify.py               # 通知模块（飞书/Telegram，provider 可切换）
├── requirements.txt            # Python 依赖
├── .gitignore                  # Git 忽略规则
├── QuantumultX.conf          # [生成] 原始远程链接配置（调试参考）
├── QuantumultX_Local.conf    # [生成] Raw 通道配置（主通道）
├── QuantumultX_Mirror.conf   # [生成] jsDelivr 镜像通道配置
└── QuantumultX_CF.conf       # [生成] Cloudflare Workers 反代通道配置
```

---

## 技术栈

| 技术 | 版本 | 说明 |
|------|------|------|
| Python | 3.9+ | 主要开发语言 |
| requests | - | HTTP 请求库，用于下载底包 |
| PyYAML | - | YAML 配置文件解析 |
| GitHub Actions | - | 自动化构建与部署 |

---

## 核心功能

### 1. 底包下载与解析

从指定 URL 下载 QuantumultX 配置底包，并按标准节点解析到内存中。

```python
manager.load_from_url(config['base']['url'])
```

### 2. 配置清洗 (Patches)

在注入新规则前，先过滤掉底包中不需要的内容。

支持两种模式：
- **黑名单模式 (blacklist)**：移除包含指定关键词的规则
- **白名单模式 (whitelist)**：只保留包含指定关键词的规则

```yaml
patches:
  policy:
    keywords:
      - "Hijacking"
      - "广告"
      - "static"
    strategy: "blacklist"
```

### 3. KV 配置覆盖

支持对 General、MITM、HTTP Backend 等节点的 Key-Value 配置进行覆盖。

```yaml
general:
  geoip-url: "https://github.com/Hackl0us/GeoIP2-CN/raw/release/Country.mmdb"
```

### 4. 规则注入

支持将规则注入到指定节点的头部或尾部。

- **追加模式**：注入到节点末尾（默认）
- **头部注入**：注入到节点开头（用于高优先级规则）

```python
manager.add_list_item("filter_local", rule, position="start")
```

### 5. 本地文件引用

支持通过 `file://` 协议引用本地规则文件。

```yaml
local_filters:
  top:
    - "file://rules/custom.list"
```

### 6. 远程规则引用

支持引用 GitHub 上的开源规则库，目前支持：

- **blackmatrix7**：内置源简写，自动拼接 GitHub URL
- **自定义 URL**：直接指定完整的规则 URL

```yaml
filter_remote:
  - name: "TikTok"
    source: "blackmatrix7"
    policy: "us-node"
    tag: "TikTok"
```

### 7. 策略组映射

将外部规则中的策略名称映射到底包的真实策略组名称。

```yaml
policy_map:
  us-node: "美国节点"
  direct: "direct"
  reject: "reject"
```

---

## 使用指南

### 本地运行

1. 安装依赖

```bash
pip install -r requirements.txt
```

2. 修改配置文件

编辑 `profiles/config.yaml`，根据需要调整各项配置。

3. 运行构建

```bash
python src/main.py
```

4. 查看输出

生成的配置文件保存在项目根目录下：

| 文件 | 分发链路 |
|------|---------|
| `QuantumultX.conf` | 上游原始链接（调试参考） |
| `QuantumultX_Local.conf` | GitHub Raw（主通道） |
| `QuantumultX_Mirror.conf` | jsDelivr CDN 镜像 |
| `QuantumultX_CF.conf` | Cloudflare Workers 反代 |

### 在 QuantumultX 中使用

1. 三份本地化配置内容相同、仅链接前缀不同，任选网络可达的一条链路导入
2. 在 QuantumultX 中添加下载配置，输入配置文件的 URL 即可下载使用
3. 节点订阅不随配置分发，请在 QX 的「订阅」区自行添加机场订阅

---

## 配置说明

### config.yaml 完整配置说明

#### 1. 基础设置 (Base)

```yaml
base:
  url: "https://ddgksf2013.top/Profile/QuantumultX.conf"
```

指定底包配置的下载 URL，所有修改都将基于此文件进行。

#### 2. 补丁排除 (Patches)

```yaml
patches:
  policy:
    keywords:
      - "Hijacking"
      - "广告"
      - "static"
    strategy: "blacklist"
```

| 参数 | 类型 | 说明 |
|------|------|------|
| section | string | 要清洗的节点名称 |
| keywords | list | 关键词列表 |
| strategy | string | 策略：blacklist（黑名单）或 whitelist（白名单） |

#### 3. 全局设置 (General)

```yaml
general:
  geoip-url: "https://github.com/Hackl0us/GeoIP2-CN/raw/release/Country.mmdb"
  resource_parser_url: "https://raw.githubusercontent.com/KOP-XIAO/QuantumultX/master/Scripts/resource-parser.js"
  server_check_url: "http://www.gstatic.com/generate_204"
```

#### 4. DNS 配置

```yaml
dns:
  - "server=/example.com/192.168.1.1"
```

#### 5. 策略组映射 (Policy Map)

```yaml
policy_map:
  us-node: "美国节点"
  direct: "direct"
  reject: "reject"
```

将外部规则中的策略名称映射到底包的真实策略组名称。

#### 6. 策略组定义 (Policy)

```yaml
policy:
  - "static=苹果服务, direct, 香港节点, 台湾节点, 美国节点, 日本节点, 狮城节点, proxy, 手动选择, img-url=https://raw.githubusercontent.com/Koolson/Qure/master/IconSet/Color/Apple.png"
```

支持以下策略类型：

| 类型 | 说明 |
|------|------|
| static | 静态策略组，固定节点顺序 |
| url-latency-benchmark | URL 测速策略组，自动选择最快节点 |
| server-tag-regex | 正则匹配服务器标签 |

#### 7. 远程服务器 (Server Remote)

```yaml
server_remote:
  - "https://我的机场.com, tag=机场, enabled=true"
```

#### 8. 本地分流规则 (Local Filters)

```yaml
local_filters:
  top:
    - "file://rules/custom.list"
    - "ip6-cidr,::/0,direct"
  bottom:
    - "geoip,cn,direct"
```

- **top**：注入到分流规则最前面（优先级最高）
- **bottom**：注入到分流规则最后面（优先级最低）

#### 9. 远程分流规则 (Filter Remote)

```yaml
filter_remote:
  - name: "TikTok"
    source: "blackmatrix7"
    policy: "us-node"
    tag: "TikTok"
```

| 参数 | 类型 | 说明 |
|------|------|------|
| name | string | 规则名称（仅用于 blackmatrix7 源） |
| source | string | 源类型：blackmatrix7 或自定义 URL |
| policy | string | 使用的策略组名称 |
| tag | string | 规则标签 |
| url | string | 完整规则 URL（自定义源时使用） |

#### 10. 重写规则 (Rewrite)

```yaml
rewrite_local:
  - "file://rules/rewrites.list"
  - "^https://google.cn url 302 https://google.com"

rewrite_remote:
  - "https://limbopro.com/Adblock4limbo.conf, tag=毒奶特供(去网页广告计划), enabled=true"
```

#### 11. MITM 配置

```yaml
mitm:
  hostname: "file://rules/mitm_hosts.list"
```

MITM hostname 必须是一行，用逗号分隔：

```
*.google.com, *.googleapis.com, *.apple.com, *.icloud.com, *.instagram.com
```

---

## API 参考

### QXConfigManager 类

核心配置管理类，提供所有配置操作接口。

#### 方法列表

| 方法 | 说明 |
|------|------|
| `load_from_url(url)` | 从 URL 下载并解析底包 |
| `load_rules_from_file(path)` | 从本地文件加载规则 |
| `patch_section(section, keywords, strategy)` | 清洗指定节点内容 |
| `set_kv(section, key, value)` | 设置 KV 配置 |
| `add_list_item(section, item, position)` | 添加列表项到指定位置 |
| `add_remote_rule(url, tag, policy)` | 添加远程规则引用 |
| `save(filename)` | 保存配置到文件 |

#### load_from_url(url)

从指定 URL 下载底包配置。

```python
manager.load_from_url("https://example.com/config.conf")
```

#### patch_section(section, keywords, strategy)

清洗指定节点的规则。

```python
# 黑名单模式：移除包含关键词的规则
manager.patch_section("policy", ["广告", "Hijacking"], "blacklist")

# 白名单模式：只保留包含关键词的规则
manager.patch_section("dns", ["google"], "whitelist")
```

#### set_kv(section, key, value)

设置 KV 配置，支持覆盖和追加模式。

```python
# 覆盖模式
manager.set_kv("general", "geoip-url", "https://example.com/GeoIP.mmdb")

# 追加模式（hostname 特殊处理）
manager.set_kv("mitm", "hostname", "*.example.com")
```

#### add_list_item(section, item, position)

向列表节点添加规则。

```python
# 追加到末尾
manager.add_list_item("filter_local", "host-suffix,google.com,direct")

# 插入到开头
manager.add_list_item("filter_local", "ip6-cidr,::/0,direct", position="start")
```

---

## 自动化部署

### GitHub Actions 配置

项目已配置 GitHub Actions 实现自动化构建和部署。

#### 触发机制

| 触发方式 | 说明 |
|---------|------|
| 定时执行 | 每天北京时间 06:00 自动运行 |
| 手动触发 | 在 GitHub 网页上点击 "Run workflow" 按钮 |
| 代码推送 | 当 profiles/、rules/、src/ 目录文件变更时触发 |

#### 构建流程

1. 拉取最新代码
2. 设置 Python 3.12 环境（带并发保护，防止构建重叠提交）
3. 安装项目依赖
4. 运行构建脚本：加载底包（本地 `profiles/base.conf`，url 模式带快照回退）→ 清洗注入 → lint 校验 → 快照远程规则 → 生成四份配置 → 三通道探活 → 推送通知（飞书/Telegram）
5. 构建成功提交产物；构建失败以非零码退出，不提交，线上配置不受影响

#### 配置文件位置

`.github/workflows/build.yml`

---

## V6 可靠性设计

### 底包加载（本地优先）

```
config.yaml base:
  file（默认）→ 直接加载 profiles/base.conf（自有底包，随仓库版本管理，无外部依赖）
  url（可选） → 下载底包（重试 2 次）
                 ├─ 成功 → 使用最新底包，构建完成后刷新 Origin_Quantumultx.conf 快照
                 └─ 失败 → 回退仓库快照 Origin_Quantumultx.conf（通知日报标注）
                             └─ 快照也不存在 → 抛异常 exit 1，workflow 不提交 + 告警
```

`profiles/base.conf` 来源：ddgksf2013 小白配置 2.0（V269）固化。固化时的清理项：原作者水印与全部更新日志注释、tag 中的 `@ddgksf2013` 后缀、其个人域名的代理分流行、免费公共订阅行、两条空壳规则（GoogleVoice 42B / StreamingSE 295B）；唯一功能改动为恢复 `udp_whitelist=1-442, 444-65535`。`patches.mitm`（keywords: passphrase/p12）保证任何底包中的证书数据都会被清洗，配置永不携带 MITM 证书。

### 构建通知

统一走 `src/notify.py`，`config.yaml notify.provider`（或 env `NOTIFY_PROVIDER`）切换：

| provider | 通道 | 凭证 |
|----------|------|------|
| feishu（默认） | 飞书群自定义机器人 Webhook，text 消息（HTML 报告自动转纯文本），支持加签 | `FEISHU_WEBHOOK_URL` / `FEISHU_SECRET`（可选） |
| telegram | Bot API，HTML 消息 | `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` |
| both | 双通道同发 | 两套凭证 |

所选通道凭证缺失或发送失败时自动降级另一通道并记录日志。

### 远程规则下载

- 每个文件最多 `2 次尝试 × 2 个候选源`（原始 URL + jsDelivr 镜像，仅 raw.githubusercontent.com 源自动切换），指数退避
- 内容校验：拒绝空内容、`text/html` 响应与 HTML 错误页，防止坏内容覆盖好快照
- 失败分级：
  - 本地有旧快照 → 继续使用本地化链接（旧快照仍可用），计入 `download_stale`
  - 无任何快照 → 保留原始链接，计入 `download_failed` 并列入异常清单
  - URL 命中 `localize_skip` 豁免名单（如 kelee.one 的 CF 防火墙源）→ 保持原链，计入 `skipped`

### 三通道分发

构建时对同一份内存配置按通道前缀重建 `filter_remote`/`rewrite_remote` 链接后分别输出，互不污染：

| 通道 | 前缀（环境变量覆盖） | 产物 |
|------|--------------------|------|
| Local | `URL_RAW_PREFIX`，默认 `https://raw.githubusercontent.com/{repo}/main/rules` | `QuantumultX_Local.conf` |
| Mirror | `URL_MIRROR_PREFIX`，默认 `https://testingcf.jsdelivr.net/gh/{repo}@main/rules` | `QuantumultX_Mirror.conf` |
| CF | `URL_CF_PREFIX`，默认 `https://proxy.991201.xyz/https://raw.githubusercontent.com/{repo}/main/rules` | `QuantumultX_CF.conf` |

构建末尾对三条链路各探测一次（带一次重试），结果随通知日报推送。探活验证的是服务存活，不等价于国内可达性。

### 输出 lint

提交前校验输出配置段落行数阈值（policy ≥5、general ≥1、filter_local ≥5、filter_remote ≥3、rewrite_remote ≥3），不达标则构建失败，防止残缺配置进入仓库。

---

## 常见问题

### Q1: 如何添加自己的自定义规则？

**A:** 在 `rules/` 目录下创建新的 `.list` 文件，然后在 `config.yaml` 中引用：

```yaml
local_filters:
  top:
    - "file://rules/your_custom.list"
```

### Q2: 如何引用其他开源规则库？

**A:** 使用 `filter_remote` 配置：

```yaml
filter_remote:
  - source: "blackmatrix7"
    name: "Netflix"
    policy: "us-node"
    tag: "Netflix"
```

或者使用自定义 URL：

```yaml
filter_remote:
  - url: "https://raw.githubusercontent.com/xxx/rules/main/list.list"
    policy: "us-node"
    tag: "Custom"
```

### Q3: 如何修改策略组的节点顺序？

**A:** 在 `config.yaml` 的 `policy` 部分修改策略组定义：

```yaml
policy:
  - "static=全球加速, 自动选择, direct, 香港节点, 台湾节点..."
```

### Q4: MITM hostname 如何配置？

**A:** 在 `rules/mitm_hosts.list` 中配置（注意必须是一行，逗号分隔）：

```
*.google.com, *.googleapis.com, *.apple.com
```

然后在 `config.yaml` 中引用：

```yaml
mitm:
  hostname: "file://rules/mitm_hosts.list"
```

### Q5: 如何删除底包中的某些配置？

**A:** 使用 `patches` 配置进行清洗：

```yaml
patches:
  policy:
    keywords:
      - "要删除的策略组名称"
    strategy: "blacklist"
```

### Q6: 为什么某些规则没有生效？

**A:** 检查以下几点：

1. 规则文件路径是否正确
2. 策略组名称是否在 `policy_map` 中正确映射
3. 规则优先级是否正确（top/bottom）
4. 底包清洗是否误删除了相关配置

---

## 版本历史

### V5.1 (Fixed)

- 修复 `filter_remote` 字段处理问题
- 优化策略映射逻辑
- 改进日志输出

### V5.0

- 重构核心架构
- 支持远程规则引用
- 新增策略组映射功能
- 优化 MITM hostname 处理

---

## 贡献指南

欢迎提交 Issue 和 Pull Request！

---

## 许可证

本项目采用 MIT 许可证。

---

## 联系方式

如有问题或建议，请在 GitHub Issues 中提出。

---

**文档生成日期**: 2026-03-01
