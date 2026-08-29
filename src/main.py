import yaml
import os
import sys
import logging
import re
import time
import subprocess
from datetime import datetime

import requests

# === 【关键修复】确保能导入 qx_core ===
# 获取当前脚本所在目录 (src)
current_dir = os.path.dirname(os.path.abspath(__file__))
# 将 src 目录加入 Python 搜索路径
if current_dir not in sys.path:
    sys.path.append(current_dir)

try:
    from qx_core import QXConfigManager, logger
except ImportError as e:
    print(f"❌ 严重错误: 无法导入 qx_core.py。请检查该文件是否在 {current_dir} 目录下。")
    print(f"详细错误: {e}")
    sys.exit(1)

# === 路径定义 ===
# 项目根目录 (src 的上一级)
BASE_DIR = os.path.dirname(current_dir)
CONFIG_PATH = os.path.join(BASE_DIR, "profiles", "config.yaml")
OUTPUT_FILE = os.path.join(BASE_DIR, "MyQuantumultX.conf")
RULES_DIR = os.path.join(BASE_DIR, "rules")
# 底包快照：上游底包站点失效时回退，保证构建永不产出空配置覆盖线上
BASE_SNAPSHOT_FILE = os.path.join(BASE_DIR, "Origin_Quantumultx.conf")

# ==========================================
# 🌐 分发通道配置（前缀可被环境变量覆盖）
# ==========================================
# Local  : GitHub Raw（主通道）
# Mirror : jsDelivr CDN（注意 gh 源是 @分支 路径格式，单文件上限 20MB）
# CF     : Cloudflare Workers 反代（拼接式：https://worker域名/完整原始URL）
DEFAULT_REPO = os.environ.get("GITHUB_REPOSITORY", "suversal/qx-config-sync")


def build_channels():
    return [
        {
            "name": "Local",
            "output": os.path.join(BASE_DIR, "MyQuantumultX_Local.conf"),
            "prefix": os.environ.get("URL_RAW_PREFIX")
            or f"https://raw.githubusercontent.com/{DEFAULT_REPO}/main/rules",
        },
        {
            "name": "Mirror",
            "output": os.path.join(BASE_DIR, "MyQuantumultX_Mirror.conf"),
            "prefix": os.environ.get("URL_MIRROR_PREFIX")
            or f"https://testingcf.jsdelivr.net/gh/{DEFAULT_REPO}@main/rules",
        },
        {
            "name": "CF",
            "output": os.path.join(BASE_DIR, "MyQuantumultX_CF.conf"),
            "prefix": os.environ.get("URL_CF_PREFIX")
            or f"https://proxy.991201.xyz/https://raw.githubusercontent.com/{DEFAULT_REPO}/main/rules",
        },
    ]


# ==========================================
# 📱 Telegram 通知配置 (可选)
# ==========================================
# 优先从环境变量读取，读取不到则使用这里的值
TELEGRAM_BOT_TOKEN = "xxx"
TELEGRAM_CHAT_ID = "xxx"

# KV 类型的节点 (覆盖式)
KV_SECTIONS = {"general", "mitm", "http_backend"}

# 需要特殊处理的节点列表 (在通用循环中跳过)
# local_filters: 有 top/bottom 逻辑；filter_remote: 内容是字典；其余为非节点配置
SKIP_SECTIONS = [
    "base", "patches", "policy_map",
    "local_filters", "remote_filters",
    "filter_remote"
]

# 模拟 QX 客户端的 UA
QX_HEADERS = {"User-Agent": "Quantumult X/1.0.31"}

# 探活用的仓库内已知文件（各通道均应可访问）
PROBE_FILE = "filter_remote/Apple.list"


def check_environment():
    """环境自检"""
    if not os.path.exists(RULES_DIR):
        try:
            os.makedirs(RULES_DIR)
            logger.info(f"📂 [Init] 自动创建规则目录: {RULES_DIR}")
        except Exception:
            pass


# ==========================================
# 网络下载：重试 + 镜像切换 + 内容校验
# ==========================================
def content_looks_valid(resp):
    """防止把空内容或 HTML 错误页当成规则快照写入仓库"""
    content_type = resp.headers.get("Content-Type", "").lower()
    if "text/html" in content_type:
        return False
    body = resp.content
    if len(body) < 10:
        return False
    head = body[:256].lstrip().lower()
    if head.startswith(b"<!doctype") or head.startswith(b"<html"):
        return False
    return True


def fetch_with_fallback(url, max_attempts=2, timeout=15):
    """下载 URL，带指数退避重试；raw.githubusercontent.com 源失败自动切换 jsDelivr 镜像"""
    candidates = [url]
    m = re.match(
        r"https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/(?:refs/heads/)?([^/]+)/(.+)", url
    )
    if m:
        owner, repo, branch, path = m.groups()
        candidates.append(f"https://testingcf.jsdelivr.net/gh/{owner}/{repo}@{branch}/{path}")

    last_err = None
    for cand in candidates:
        for attempt in range(max_attempts):
            try:
                resp = requests.get(cand, headers=QX_HEADERS, timeout=timeout)
                resp.raise_for_status()
                if not content_looks_valid(resp):
                    raise ValueError("内容校验失败（空内容或 HTML 错误页）")
                if cand != url:
                    logger.info(f"   🔁 镜像生效: {cand}")
                return resp.content
            except Exception as e:
                last_err = e
                logger.warning(f"   ⚠️ 下载失败 ({attempt + 1}/{max_attempts}) {cand}: {e}")
                if attempt < max_attempts - 1:
                    time.sleep(2 * (attempt + 1))
    raise last_err


def load_base_with_fallback(manager, url):
    """底包保护：下载失败回退仓库快照，两者皆不可用则抛异常阻止构建提交。

    返回 (来源标签, 成功时的原始文本)。"""
    try:
        content = fetch_with_fallback(url, max_attempts=2, timeout=30)
        manager.load_from_text(content.decode("utf-8"))
        return "fresh", content.decode("utf-8")
    except Exception as e:
        logger.error(f"❌ [Base] 底包下载失败: {e}")
        if os.path.exists(BASE_SNAPSHOT_FILE):
            logger.warning(f"⚠️ [Base] 回退到底包快照: {BASE_SNAPSHOT_FILE}")
            with open(BASE_SNAPSHOT_FILE, "r", encoding="utf-8") as f:
                manager.load_from_text(f.read())
            return "snapshot", None
        raise RuntimeError(f"底包下载失败且仓库中无可用快照: {e}")


# ==========================================
# 规则处理
# ==========================================
def resolve_rules(manager, raw_rules, mapping=None):
    """递归解析规则 (支持 file:// 和 策略映射)"""
    final_rules = []
    if not raw_rules: return []
    # 兼容单个字符串的情况
    if isinstance(raw_rules, str): raw_rules = [raw_rules]

    for rule in raw_rules:
        # 过滤 None 或空字符串 (防止 YAML 解析出 None 导致崩溃)
        if not rule:
            continue

        # 如果规则是字典 (比如错误地进入了这里)，跳过或报错，防止崩溃
        if isinstance(rule, dict):
            logger.warning(f"⚠️ [Skip] 跳过无法解析的字典规则: {rule}")
            continue

        # 处理文件引用
        if rule.startswith("file://"):
            file_path = rule.replace("file://", "").strip()
            file_content = manager.load_rules_from_file(file_path)
            final_rules.extend(resolve_rules(manager, file_content, mapping))
        else:
            # 处理策略映射
            if mapping:
                for k, v in mapping.items():
                    if f", {k}," in rule:
                        rule = rule.replace(f", {k},", f", {v},")
            final_rules.append(rule)
    return final_rules


def extract_filename(url):
    name = url.split("/")[-1].split("?")[0]
    return name or "unknown.txt"


def localize_remote_rules(manager, skip_keywords=None):
    """下载远程规则快照到 rules/ 目录。

    不直接修改 manager 内的链接行，而是返回记录，
    由各分发通道按自己的前缀重建链接，保证三份产物互不污染。
    记录 kind: localized(可用本地化链接) / keep(保留原始行)
    skip_keywords: URL 命中即保持原链（CF 防火墙源等无法服务器端抓取的场景），不计失败"""
    skip_keywords = skip_keywords or []
    stats = {
        "download_success": 0, "download_stale": 0,
        "download_failed": 0, "skipped": 0, "failed_files": []
    }
    records_by_section = {}

    for sec in ["filter_remote", "rewrite_remote"]:
        if sec not in manager.sections:
            continue

        sec_dir = os.path.join(RULES_DIR, sec)
        os.makedirs(sec_dir, exist_ok=True)
        records = []

        for line in manager.sections[sec]:
            if not line or line.startswith("#") or line.startswith(";"):
                records.append({"kind": "keep", "line": line})
                continue

            match = re.match(r"^(https?://[^,]+)(.*)$", line.strip())
            if not match:
                records.append({"kind": "keep", "line": line})
                continue

            original_url, rest = match.group(1), match.group(2)

            # 豁免源：保持原链，由 QX 客户端直接拉取
            if any(k in original_url for k in skip_keywords):
                logger.info(f"⏭️ [Localize] 豁免（保持原链）: {original_url}")
                records.append({"kind": "keep", "line": line})
                stats["skipped"] += 1
                continue

            filename = extract_filename(original_url)
            local_path = os.path.join(sec_dir, filename)
            has_snapshot = os.path.exists(local_path)

            logger.info(f"⬇️ 正在下载: {filename}")
            logger.info(f"   🔗 源地址: {original_url}")

            try:
                content = fetch_with_fallback(original_url)
                with open(local_path, "wb") as f:
                    f.write(content)
                logger.info(f"   ✅ 下载成功! 文件大小: {len(content) / 1024:.2f} KB")
                records.append({"kind": "localized", "filename": filename, "rest": rest})
                stats["download_success"] += 1
            except Exception as e:
                if has_snapshot:
                    # 本地旧快照仍可用：继续使用本地化链接，不回退原链
                    logger.error(f"   ⚠️ 下载失败，继续使用本地旧快照: {filename} ({e})")
                    records.append({"kind": "localized", "filename": filename, "rest": rest})
                    stats["download_stale"] += 1
                    stats["failed_files"].append(f"{filename}（使用旧快照）")
                else:
                    logger.error(f"   ❌ 下载失败且无旧快照，保留原链接: {original_url} ({e})")
                    records.append({"kind": "keep", "line": line})
                    stats["download_failed"] += 1
                    stats["failed_files"].append(f"{filename}（保留原链）")

            # 间隔1秒避免风控
            time.sleep(1)

        records_by_section[sec] = records
        logger.info(
            f"📊 [Localize] [{sec}] 完成: {stats['download_success']} 成功 / "
            f"{stats['download_stale']} 旧快照 / {stats['download_failed']} 失败 / {stats['skipped']} 豁免"
        )

    return records_by_section, stats


def write_channel(manager, records_by_section, prefix):
    """按通道前缀重建 [filter_remote]/[rewrite_remote] 中的链接（可重复调用，互不污染）"""
    for sec, records in records_by_section.items():
        new_lines = []
        for r in records:
            if r["kind"] == "localized":
                new_lines.append(f"{prefix}/{sec}/{r['filename']}{r['rest']}")
            else:
                new_lines.append(r["line"])
        manager.sections[sec] = new_lines


# ==========================================
# 质量校验
# ==========================================
def lint_output(manager):
    """提交前基础校验，防止残缺配置覆盖线上（如底包快照损坏、注入逻辑回归）"""
    def active_lines(sec):
        return len([l for l in manager.sections.get(sec, []) if l and not l.startswith("#") and not l.startswith(";")])

    checks = [
        ("policy", 5, "[policy] 策略组数量异常"),
        ("general", 1, "[general] 全局配置为空"),
        ("filter_local", 5, "[filter_local] 本地分流数量异常"),
        ("filter_remote", 3, "[filter_remote] 远程分流引用数量异常"),
        ("rewrite_remote", 3, "[rewrite_remote] 远程重写引用数量异常"),
    ]
    problems = [msg for sec, minimum, msg in checks if active_lines(sec) < minimum]
    if problems:
        raise RuntimeError("输出配置 lint 未通过: " + "; ".join(problems))
    logger.info("✅ [Lint] 输出配置校验通过")


def probe_channels(channels):
    """对三条分发通道各探测一次（验证服务存活；不代表国内可达性），带一次重试防误报"""
    results = {}
    for ch in channels:
        url = f"{ch['prefix']}/{PROBE_FILE}"
        ok = False
        for attempt in range(2):
            try:
                resp = requests.head(url, timeout=10, allow_redirects=True)
                if resp.status_code >= 400:
                    # 部分服务不支持 HEAD，回退 GET
                    resp = requests.get(url, timeout=10, stream=True)
                ok = resp.status_code < 400
                resp.close()
                if ok:
                    break
            except Exception as e:
                logger.warning(f"🌐 [Probe] {ch['name']} 探活失败: {e}")
                ok = False
            if attempt == 0:
                time.sleep(2)
        results[ch["name"]] = ok
        status = "✅" if ok else "❌"
        logger.info(f"🌐 [Probe] {ch['name']}: {status} ({url})")
        time.sleep(0.5)
    return results


# ==========================================
# 通知
# ==========================================
def send_telegram_message(bot_token, chat_id, message):
    """发送 Telegram 消息通知"""
    if not bot_token or not chat_id or bot_token == "xxx":
        logger.debug("⚠️ 未配置 Telegram，跳过通知")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:
        response = requests.post(url, data=data, timeout=10)
        response.raise_for_status()
        logger.info("📤 [Telegram] 通知发送成功")
        return True
    except Exception as e:
        logger.error(f"❌ [Telegram] 通知发送失败: {e}")
        return False


def check_file_changed(file_path):
    """检查文件是否与之前版本有变化"""
    if not os.path.exists(file_path):
        return True  # 新文件肯定变化

    import subprocess
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", str(file_path)],
            capture_output=True,
            text=True
        )
        output = result.stdout.strip()
        return bool(output)
    except Exception as e:
        logger.debug(f"⚠️ Git 检查失败，使用哈希对比: {e}")
        return True


def build_notification_message(build_success, stats, changed_files):
    """构建通知消息"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    github_repo = os.environ.get('GITHUB_REPOSITORY', '')
    github_sha = os.environ.get('GITHUB_SHA', '')[:7]

    status_emoji = "✅" if build_success else "❌"
    status_text = "构建成功" if build_success else "构建失败"

    message = (
        f"{status_emoji} <b>Quantumult X 配置自动构建完成</b>\n\n"
        f"⏰ <b>构建时间:</b> {now}\n"
    )

    if github_repo:
        repo_url = f"https://github.com/{github_repo}"
        message += f"📦 <b>仓库:</b> <a href=\"{repo_url}\">{github_repo}</a>\n"
        if github_sha:
            commit_url = f"{repo_url}/commit/{github_sha}"
            message += f"🔖 <b>最新提交:</b> <a href=\"{commit_url}\">{github_sha}</a>\n"

    message += (
        f"\n📊 <b>构建统计</b>\n"
        f"• 远程规则下载: {stats['download_success']} 成功, "
        f"{stats.get('download_stale', 0)} 用旧快照, {stats['download_failed']} 失败, "
        f"{stats.get('skipped', 0)} 豁免\n"
        f"• 注入自定义规则: {stats['rules_added']} 条\n"
    )

    # 底包来源（fresh=上游最新 / snapshot=仓库快照回退）
    if stats.get("base_source") == "snapshot":
        message += "⚠️ <b>底包使用仓库快照</b>（上游站点不可达）\n"

    # 分发通道探活
    channels = stats.get("channels", {})
    if channels:
        channel_line = " / ".join(f"{k} {'✅' if v else '❌'}" for k, v in channels.items())
        message += f"🌐 <b>分发通道:</b> {channel_line}\n"

    # 下载异常的具体文件
    failed_files = stats.get("failed_files", [])
    if failed_files:
        message += "\n⚠️ <b>下载异常清单:</b>\n"
        for f in failed_files[:10]:
            message += f"  • {f}\n"
        if len(failed_files) > 10:
            message += f"  • ...等共 {len(failed_files)} 个\n"

    if changed_files:
        message += f"\n🔄 <b>检测到配置更新:</b>\n"
        for f in changed_files:
            message += f"  • {os.path.basename(f)}\n"
    else:
        message += f"\n✓ <b>配置文件无变化</b>\n"

    message += f"\n#QXConfig #AutoSync"
    return message


def main():
    logger.info("🚀 === QX Builder V6 Started ===")
    check_environment()

    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN', TELEGRAM_BOT_TOKEN)
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', TELEGRAM_CHAT_ID)
    stats = {"channels": {}, "base_source": "unknown", "failed_files": []}

    try:
        if not os.path.exists(CONFIG_PATH):
            logger.error(f"❌ 找不到配置文件: {CONFIG_PATH}")
            raise FileNotFoundError(f"配置文件不存在: {CONFIG_PATH}")

        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        manager = QXConfigManager()

        # 1. 下载底包（失败自动回退仓库快照；两者皆失败则中止构建）
        fresh_content = None
        if config and 'base' in config:
            stats["base_source"], fresh_content = load_base_with_fallback(manager, config['base']['url'])
            logger.info(f"📦 [Base] 底包来源: {stats['base_source']}")

        # 2. 全局清洗 (Patches)
        if config and 'patches' in config:
            logger.info("🧹 [Step] 执行配置清洗 (Patches)...")
            for section, rules in config['patches'].items():
                manager.patch_section(section, rules.get('keywords', []), rules.get('strategy', 'blacklist'))

        # 3. 动态处理大部分节点 (General, DNS, Policy, Rewrite...)
        policy_map = config.get('policy_map', {}) if config else {}

        if config:
            for section_name, content in config.items():
                if section_name in SKIP_SECTIONS:
                    continue

                # 处理 KV 节点 (General, MITM) - 覆盖模式
                if section_name in KV_SECTIONS:
                    if isinstance(content, dict):
                        for k, v in content.items():
                            # 支持 mitm hostname 引用文件
                            if isinstance(v, str) and v.startswith("file://"):
                                resolved = resolve_rules(manager, [v], None)
                                v = resolved[0] if resolved else ""
                            manager.set_kv(section_name, k, str(v))

                # 处理 List 节点 (DNS, Policy, Server...) - 追加模式
                else:
                    if isinstance(content, list):
                        rules = resolve_rules(manager, content, policy_map)
                        if rules:
                            logger.info(f"⚡️ [Inject] 向 [{section_name}] 注入 {len(rules)} 条规则")
                            for rule in rules:
                                if section_name == "rewrite_remote":
                                    manager.add_list_item(section_name, rule, position="start")
                                else:
                                    manager.add_list_item(section_name, rule)

        # 4. 专门处理本地分流 (Local Filters - 支持 top/bottom)
        if config and 'local_filters' in config:
            logger.info("🌪 [Step] 处理本地分流 (Local Filters)...")
            if 'top' in config['local_filters']:
                rules = resolve_rules(manager, config['local_filters']['top'], policy_map)
                logger.info(f"   └── 注入 Top 规则: {len(rules)} 条")
                for r in rules: manager.add_list_item("filter_local", r, "start")

            if 'bottom' in config['local_filters']:
                rules = resolve_rules(manager, config['local_filters']['bottom'], policy_map)
                logger.info(f"   └── 注入 Bottom 规则: {len(rules)} 条")
                for r in rules: manager.add_list_item("filter_local", r, "end")

        # 5. 专门处理远程分流 (Remote Filters / filter_remote)
        remote_conf = config.get('filter_remote') or config.get('remote_filters')

        if remote_conf:
            logger.info("☁️ [Step] 处理远程引用 (Remote Filters)...")
            for item in remote_conf:
                if not isinstance(item, dict):
                    continue

                source = item.get('source')
                if source == 'blackmatrix7':
                    name = item['name']
                    url = f"https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/QuantumultX/{name}/{name}.list"
                else:
                    url = item.get('url')

                if url:
                    manager.add_remote_rule(url, item.get('tag', 'Remote'), policy_map.get(item.get('policy'), item.get('policy')))

        # 6. 提交前 lint，通过后保存原链版（调试/参考用）
        logger.info(f"💾 [Step] 生成原始配置文件 -> {os.path.basename(OUTPUT_FILE)}")
        lint_output(manager)
        manager.save(OUTPUT_FILE)

        # 7. 抓取远程规则快照到 rules/（不改动内存中的链接行）
        channels = build_channels()
        logger.info("🌐 [Localize] 开始抓取并本地化远程规则...")
        records_by_section, localize_stats = localize_remote_rules(manager, config.get('localize_skip', []) if config else [])
        stats.update(localize_stats)

        # 8. 三条分发通道各自按前缀重建链接并输出
        for ch in channels:
            logger.info(f"💾 [Step] 生成 [{ch['name']}] 通道配置 -> {os.path.basename(ch['output'])}")
            write_channel(manager, records_by_section, ch["prefix"])
            manager.save(ch["output"])

        # 9. 底包快照维护：上游可达时刷新 Origin_Quantumultx.conf
        if fresh_content is not None:
            try:
                old_text = ""
                if os.path.exists(BASE_SNAPSHOT_FILE):
                    with open(BASE_SNAPSHOT_FILE, "r", encoding="utf-8") as f:
                        old_text = f.read()
                if old_text != fresh_content:
                    with open(BASE_SNAPSHOT_FILE, "w", encoding="utf-8") as f:
                        f.write(fresh_content)
                    logger.info("📦 [Base] 底包快照已刷新 (Origin_Quantumultx.conf)")
            except Exception as e:
                logger.warning(f"⚠️ [Base] 快照刷新失败（不影响本次构建）: {e}")

        # 检查文件变化 (全部产物 + 快照 + 规则目录)
        logger.info("🔍 [Check] 检查配置文件和规则是否有变化...")
        changed_files = []
        monitor_files = [OUTPUT_FILE] + [ch["output"] for ch in channels] + [BASE_SNAPSHOT_FILE]
        for f in monitor_files:
            if check_file_changed(f):
                changed_files.append(f)

        import subprocess
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain", "rules/filter_remote/", "rules/rewrite_remote/"],
                capture_output=True,
                text=True
            )
            output = result.stdout.strip()
            if output:
                for line in output.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split(None, 1)
                    if len(parts) == 2:
                        changed_files.append(parts[1])
        except Exception as e:
            logger.debug(f"⚠️ 检查规则目录变化失败: {e}")

        if changed_files:
            changed_names = [os.path.basename(f) for f in changed_files]
            logger.info(f"📢 检测到有文件变化: {', '.join(changed_names)}")
        else:
            logger.info("✓ 无文件变化")

        # 10. 分发通道探活
        stats["channels"] = probe_channels(channels)

        logger.info("✨ === Build Complete ===")

        # Telegram 通知 - 构建成功
        if bot_token and chat_id:
            stats["rules_added"] = manager.stats["rules_added"]
            message = build_notification_message(True, stats, changed_files)
            send_telegram_message(bot_token, chat_id, message)

        sys.exit(0)

    except Exception as e:
        # 构建失败，发送 Telegram 通知（workflow 因非零退出码不会提交，线上配置不受影响）
        logger.error(f"❌ 构建失败: {e}")
        if bot_token and chat_id:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            github_repo = os.environ.get('GITHUB_REPOSITORY', '')

            message = (
                f"❌ <b>Quantumult X 配置构建失败</b>\n\n"
                f"⏰ <b>失败时间:</b> {now}\n"
            )
            if github_repo:
                repo_url = f"https://github.com/{github_repo}"
                message += f"📦 <b>仓库:</b> <a href=\"{repo_url}\">{github_repo}</a>\n"

            message += (
                f"\n⚠️ <b>错误信息:</b>\n"
                f"<code>{str(e)}</code>\n\n"
                f"请前往 GitHub Action 查看完整日志\n\n"
                f"#QXConfig #BuildFailed"
            )
            send_telegram_message(bot_token, chat_id, message)

        sys.exit(1)


if __name__ == "__main__":
    main()
