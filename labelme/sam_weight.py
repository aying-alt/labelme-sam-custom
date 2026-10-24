"""HQ-SAM 权重文件的定位、下载与校验。

单独抽成一个模块，是因为「权重找不到 / 下不下来」是这个项目里新人最容易卡住的一步：
  - 权重可能放在三个不同位置（项目 models/、历史手动目录、appdirs 缓存）
  - 国内直连 huggingface.co 基本必然超时，必须能自动换镜像
  - 2~3 GB 的文件下一半断掉，必须有进度、必须能续传、必须能一眼看出是不是残缺
  - 下载彻底失败时，不能只抛个英文异常，要直接告诉用户「点哪个链接、放到哪个目录」

对外只用两个函数：
    find_weight(model_key)          找到合格文件就返回路径，否则 None（不联网、不抛异常）
    ensure_weight(model_key, ...)   找到就直接返回；找不到就下载；实在不行抛 SamWeightError

model_key 支持 `vit_h` / `vit-h` / `VIT_H` 这几种写法，内部统一成下划线小写。
"""

import os
import sys
import threading
import time

from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


# ensure_weight 的串行锁：启动预热线程和「切到 SAM 模式」可能同时进来，
# 两边都往同一个 .part 文件写会把 2~3 GB 的文件写坏。
_EW_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# 模型信息
# ---------------------------------------------------------------------------

# 归一化后的 key -> 权重文件名
WEIGHT_FILES = {
    "vit_h": "sam_hq_vit_h.pth",
    "vit_l": "sam_hq_vit_l.pth",
    "vit_b": "sam_hq_vit_b.pth",
}

# 归一化后的 key -> (约略大小, 视为「完整」的最小字节数)
# 最小字节数故意取得比实际小一截，避免不同发布版本差几 MB 就被判成残缺。
# 实测自 hf-mirror.com（2026-10，Content-Length），下限取约 90%：
# 只要明显小于它，就说明是下到一半的残骸，不能拿去加载。
EXPECTED_SIZE = {
    "vit_h": (2570940653, 2300000000),  # 2451.8 MB
    "vit_l": (1254865805, 1120000000),  # 1196.7 MB
    "vit_b": (379335069, 340000000),    # 361.8 MB
}

# 下载源，按顺序尝试。
# 国内直连 huggingface.co 几乎不可用，所以镜像放第一位；
# 镜像本身也是全量同步的，海外用户同样能跑通。
MIRRORS = (
    "https://hf-mirror.com/lkeab/hq-sam/resolve/main/{name}",
    "https://huggingface.co/lkeab/hq-sam/resolve/main/{name}",
)

# 官方/镜像之外的补充说明（写进错误提示里）
WEIGHT_PAGE = "https://huggingface.co/lkeab/hq-sam/tree/main"
OFFICIAL_REPO = "https://github.com/SysCV/sam-hq"

_CHUNK = 1024 * 512  # 512 KB


class SamWeightError(RuntimeError):
    """权重缺失且无法自动获取。消息是给最终用户看的中文多行文本。"""


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def _out(msg=""):
    """安全地往控制台写一行。

    pythonw.exe 启动时 sys.stdout 可能是 None，此时静默跳过，不能因此崩掉。
    """
    stream = sys.stdout
    if stream is None:
        return
    try:
        stream.write(msg + "\n")
        stream.flush()
    except Exception:
        pass


def _err(msg=""):
    stream = sys.stderr or sys.stdout
    if stream is None:
        return
    try:
        stream.write(msg + "\n")
        stream.flush()
    except Exception:
        pass


def _interactive():
    """当前 stdout 是不是一个真终端（决定进度是原地刷新还是逐行打印）。"""
    try:
        return bool(sys.stdout) and sys.stdout.isatty()
    except Exception:
        return False


def fmt_size(num):
    """1536 -> '1.5 KB'；人类可读。"""
    if num is None:
        return "?"
    num = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num) < 1024.0 or unit == "GB":
            if unit == "B":
                return "{:.0f} B".format(num)
            return "{:.1f} {}".format(num, unit)
        num /= 1024.0
    return "{:.1f} GB".format(num)


def fmt_eta(seconds):
    """剩余时间：'3 分 52 秒' / '12 秒'。"""
    if seconds is None or seconds <= 0 or seconds != seconds:
        return "--"
    seconds = int(seconds)
    if seconds < 60:
        return "{} 秒".format(seconds)
    if seconds < 3600:
        return "{} 分 {} 秒".format(seconds // 60, seconds % 60)
    return "{} 小时 {} 分".format(seconds // 3600, seconds % 3600 // 60)


def normalize_key(model_key):
    """'vit-h' / 'VIT_H' / 'vit_h' -> 'vit_h'。不认识的直接报错。"""
    key = str(model_key or "").strip().lower().replace("-", "_")
    if key not in WEIGHT_FILES:
        raise ValueError(
            "不支持的模型档位: {!r}（可选: {}）".format(
                model_key, " / ".join(sorted(WEIGHT_FILES))
            )
        )
    return key


def weight_filename(model_key):
    return WEIGHT_FILES[normalize_key(model_key)]


# ---------------------------------------------------------------------------
# 候选目录
# ---------------------------------------------------------------------------

def project_root():
    """本文件位于 <项目根>/labelme/sam_weight.py，往上两层就是项目根。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def candidate_dirs():
    """所有可能放权重的地方，按优先级从高到低。

    1. 环境变量 LABELME_MODEL_DIR（自己指定，最高优先级）
    2. <项目根>/models/            —— 最直观，README 让新人放这里
    3. %LOCALAPPDATA%\\labelme\\labelme\\Cache\\  —— 历史版本手动放置的位置
    4. appdirs 的 user_cache_dir("labelme")       —— pip 版 labelme 的默认缓存
    """
    dirs = []

    env_dir = os.environ.get("LABELME_MODEL_DIR")
    if env_dir:
        dirs.append(os.path.abspath(os.path.expanduser(env_dir)))

    dirs.append(os.path.join(project_root(), "models"))

    # 优先用真实的 %LOCALAPPDATA%：企业环境 / 系统盘搬迁时它未必是 ~/AppData/Local
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata and os.path.isabs(local_appdata):
        dirs.append(os.path.join(local_appdata, "labelme", "labelme", "Cache"))
    dirs.append(
        os.path.join(
            os.path.expanduser("~"),
            "AppData",
            "Local",
            "labelme",
            "labelme",
            "Cache",
        )
    )

    try:
        import appdirs  # labelme 的依赖里本来就有

        dirs.append(appdirs.user_cache_dir("labelme"))
    except Exception:
        pass

    # 去重，保持顺序
    seen = set()
    unique = []
    for d in dirs:
        if not d:
            continue
        # appdirs 在 HOME / USERPROFILE 不可用时可能返回相对路径（如 .\labelme\...），
        # 这种路径的含义取决于当前工作目录，放进来只会误报「目录不存在」。
        if not os.path.isabs(d):
            continue
        key = os.path.normcase(os.path.abspath(d))
        if key in seen:
            continue
        seen.add(key)
        unique.append(d)
    return unique


def download_dir():
    """自动下载存放的位置：优先项目根 models/，让用户一眼能找到、也能手动替换。"""
    env_dir = os.environ.get("LABELME_MODEL_DIR")
    if env_dir:
        return os.path.abspath(os.path.expanduser(env_dir))
    return os.path.join(project_root(), "models")


# ---------------------------------------------------------------------------
# 查找
# ---------------------------------------------------------------------------

def _file_ok(path, model_key):
    """文件存在且大小达到「完整」阈值。"""
    try:
        if not os.path.isfile(path):
            return False
        return os.path.getsize(path) >= EXPECTED_SIZE[normalize_key(model_key)][1]
    except Exception:
        return False


def find_weight(model_key, verbose=False):
    """在候选目录里找权重。找到返回绝对路径，找不到返回 None。

    不会联网、不会抛异常（model_key 非法时抛 ValueError）。
    """
    name = weight_filename(model_key)
    for d in candidate_dirs():
        path = os.path.join(d, name)
        if _file_ok(path, model_key):
            if verbose:
                _out("[模型] 已找到: {}".format(path))
            return path
        # 文件在但明显偏小：多半是上次下载中断留下的残骸，提示一下
        if os.path.isfile(path):
            size = os.path.getsize(path)
            if verbose and size > 0:
                _out(
                    "[模型] 忽略不完整的文件（{}，仅有 {}）: {}".format(
                        name, fmt_size(size), path
                    )
                )
    return None


def describe_search(model_key):
    """给错误提示用：列出找过哪些目录、各自状态。"""
    name = weight_filename(model_key)
    lines = []
    for d in candidate_dirs():
        path = os.path.join(d, name)
        if os.path.isfile(path):
            if _file_ok(path, model_key):
                state = "已就绪（{}）".format(fmt_size(os.path.getsize(path)))
            else:
                state = "存在但只有 {}，不完整".format(fmt_size(os.path.getsize(path)))
        elif os.path.isdir(d):
            state = "目录存在，没有该文件"
        else:
            state = "目录不存在"
        lines.append("    {}    [{}]".format(path, state))
    return lines


# ---------------------------------------------------------------------------
# 下载
# ---------------------------------------------------------------------------

def _progress_printer(total, quiet):
    """返回一个 (done) -> None 的进度回调，内部自己节流。

    - 终端里：同一行原地刷新，形如
        已下载 512.0 MB / 2.4 GB (20.8%)  8.4 MB/s  剩余 2 分 40 秒
    - 重定向到文件/管道时：每 5% 打一整行，避免日志被 \r 搅乱
    """
    interactive = _interactive() and not quiet
    tty_last = [0.0]
    pct_step = [-5]
    last_emit = [time.time()]

    def show(done):
        if quiet:
            return
        t = max(total, done) if total else done
        ratio = (done / t) if t else 0.0
        pct = ratio * 100.0

        if interactive:
            now = time.time()
            if now - tty_last[0] < 0.2 and done < t:
                return
            tty_last[0] = now
            elapsed = now - t0[0]
            # 刚开始不到 0.5 秒时算出来的速度没有意义（分母接近 0），先不显示
            if elapsed >= 0.5:
                speed = done / elapsed
                speed_txt = fmt_size(speed) + "/s"
                eta = (t - done) / speed if t else None
            else:
                speed_txt = "--/s"
                eta = None
            line = "[模型] 已下载 {} / {}  ({:.1f}%)  {}  剩余 {}".format(
                fmt_size(done),
                fmt_size(t),
                pct,
                speed_txt,
                fmt_eta(eta),
            )
            try:
                sys.stdout.write("\r" + line + "   ")
                sys.stdout.flush()
            except Exception:
                pass
            if done >= t:
                try:
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                except Exception:
                    pass
            return

        # 非终端（输出被重定向到文件）：按行打印，不做 \r 覆盖。
        # 触发条件二选一，避免慢网络下长时间一行都不出、让人以为卡死：
        #   1) 每涨 5%
        #   2) 距上次输出已过 5 秒
        now = time.time()
        by_pct = bool(t) and pct >= pct_step[0] + 5
        by_time = (now - last_emit[0]) >= 5.0
        if not (by_pct or by_time):
            return
        if by_pct:
            pct_step[0] = int(pct // 5) * 5
        last_emit[0] = now
        elapsed = now - t0[0]
        if elapsed >= 0.5:
            speed_txt = "{}/s".format(fmt_size(done / elapsed))
            eta = (t - done) / (done / elapsed) if done else None
            eta_txt = "  剩余 {}".format(fmt_eta(eta))
        else:
            speed_txt = "--/s"
            eta_txt = ""
        print(
            "[模型] {:.0f}%  {} / {}  {}{}".format(
                pct, fmt_size(done), fmt_size(t), speed_txt, eta_txt
            )
        )

    t0 = [time.time()]
    return show


def _download_one(url, dest, hint_total=0, quiet=False):
    """从单个 URL 下载到 dest，支持 .part 断点续传。成功返回最终字节数。

    hint_total 只在服务器不给 Content-Length 时用来给进度条一个参考总量。
    """
    part = dest + ".part"
    resume_from = 0
    if os.path.isfile(part):
        resume_from = os.path.getsize(part)
        if resume_from > 0:
            _out("[模型] 发现未完成的下载，从 {} 处续传".format(fmt_size(resume_from)))

    req = Request(url)
    req.add_header("User-Agent", "labelme-sam-custom/1.0")
    if resume_from > 0:
        req.add_header("Range", "bytes={}-".format(resume_from))

    try:
        resp = urlopen(req, timeout=60)
    except HTTPError as exc:
        # 服务器不认 Range 会返回 200 或 416；416 说明 .part 已经等于全文件
        if exc.code == 416 and resume_from > 0:
            os.replace(part, dest)
            return os.path.getsize(dest)
        raise

    with resp:
        status = getattr(resp, "status", 200)
        length = int(resp.headers.get("Content-Length") or 0)

        if resume_from > 0 and status != 206:
            # 服务器忽略了 Range，从头来，先清掉旧残片
            _out("[模型] 服务器不支持续传，重新开始下载")
            resume_from = 0
            length = length or 0

        total = resume_from + length if length else hint_total

        show = None
        done = resume_from
        mode = "ab" if resume_from > 0 else "wb"
        with open(part, mode) as fp:
            while True:
                chunk = resp.read(_CHUNK)
                if not chunk:
                    break
                fp.write(chunk)
                done += len(chunk)
                if show is None:
                    # total 只有拿到第一条数据后才知道准不准，这里延迟建回调
                    show = _progress_printer(total, quiet)
                    show(done)
                else:
                    show(done)

    if show is not None:
        # 收尾补一次 100%
        try:
            show(done if not total else max(done, total))
        except Exception:
            pass

    if length and done - resume_from < length:
        raise IOError(
            "连接提前中断：只收到 {} / {}".format(
                fmt_size(done - resume_from), fmt_size(length)
            )
        )

    os.replace(part, dest)
    return os.path.getsize(dest)


def ensure_weight(model_key, allow_download=True, quiet=False, verbose=True):
    """确保权重可用，返回其绝对路径。

    顺序：先找（三个目录）→ 找不到就按 MIRRORS 逐个源下载到 <项目根>/models/。
    全部失败时抛 SamWeightError，消息里带完整的「手动怎么放」指引。

    加锁串行：启动预热线程（start_custom_labelme.py）和切 SAM 模式
    （canvas.loadSamPredictor）可能并发调到这里，两边同时写同一个 .part
    会把文件写坏。后到的那个在这里等前一个下完，之后 find_weight 直接命中，
    不会重复下载。
    """
    with _EW_LOCK:
        return _ensure_weight(model_key, allow_download, quiet, verbose)


def _ensure_weight(model_key, allow_download=True, quiet=False, verbose=True):
    key = normalize_key(model_key)
    name = WEIGHT_FILES[key]

    found = find_weight(key, verbose=verbose)
    if found:
        return found

    if not allow_download or os.environ.get("LABELME_NO_AUTO_DOWNLOAD") == "1":
        # 环境变量判断放在这里而不是只写在启动脚本里，
        # 是为了让 `python -m labelme` 这条原版入口也认这个开关。
        disabled = os.environ.get("LABELME_NO_AUTO_DOWNLOAD") == "1"
        raise SamWeightError(
            _manual_help(
                key,
                name,
                [],
                reason=(
                    "已设置 LABELME_NO_AUTO_DOWNLOAD=1，跳过自动下载"
                    if disabled
                    else None
                ),
            )
        )

    dest_dir = download_dir()
    try:
        os.makedirs(dest_dir, exist_ok=True)
    except Exception as exc:
        raise SamWeightError(
            "无法创建权重目录 {}：{}\n{}".format(dest_dir, exc, "\n".join(_manual_help(key, name, [])))
        )

    dest = os.path.join(dest_dir, name)

    if verbose:
        _out("")
        _out("=" * 62)
        _out("[模型] 未找到 HQ-SAM 权重: {}".format(name))
        _out("[模型] 档位: {}  ({})".format(key, " / ".join(sorted(WEIGHT_FILES))))
        _out("[模型] 需要下载约 {}".format(fmt_size(EXPECTED_SIZE[key][0])))
        _out("[模型] 保存到: {}".format(dest))
        _out("=" * 62)

    errors = []
    for tpl in MIRRORS:
        url = tpl.format(name=name)
        if verbose:
            _out("[模型] 尝试下载源: {}".format(url))
        started = time.time()
        try:
            size = _download_one(url, dest, hint_total=EXPECTED_SIZE[key][0], quiet=quiet)
        except Exception as exc:
            errors.append((url, exc))
            _err("[模型] 该源失败: {}".format(exc))
            continue

        if size < EXPECTED_SIZE[key][1]:
            errors.append((url, "下载完成但文件偏小（{}），判定为不完整".format(fmt_size(size))))
            try:
                os.remove(dest)
            except OSError:
                pass
            continue

        if verbose:
            _out(
                "[模型] 下载完成: {}  ({})".format(
                    fmt_size(size), fmt_eta(time.time() - started)
                )
            )
            _out("[模型] 已保存到: {}".format(dest))
            _out("")
        return dest

    raise SamWeightError(_manual_help(key, name, errors))


def _manual_help(model_key, name, errors, reason=None):
    """构造一段用户能照着做的手动处理说明。

    reason 用来替换标题行：下载失败和「用户主动禁用下载」是两回事，
    标题得说实话。
    """
    dest_dir = download_dir()
    url = MIRRORS[0].format(name=name)

    lines = ["", "=" * 62, reason or "HQ-SAM 权重自动下载失败", "=" * 62]
    if errors:
        lines.append("已尝试的下载源及失败原因：")
        for u, e in errors:
            lines.append("  - {}".format(u))
            lines.append("      {}".format(e))
        lines.append("")
    lines.append("不影响纯手工标注：不装权重也能画多边形，只是用不了 SAM 半自动。")
    lines.append("")
    lines.append("手动解决（任选一种）：")
    lines.append("")
    lines.append("  1) 换个网络环境再自动下一次（最省事）")
    lines.append("         python download_model.py --model {}".format(model_key))
    lines.append("")
    lines.append("  2) 用浏览器/下载工具直接下，然后放进 models 目录")
    lines.append("         下载: {}".format(url))
    lines.append("         备选: {}".format(MIRRORS[1].format(name=name)))
    lines.append("         放到: {}".format(os.path.join(dest_dir, name)))
    lines.append("")
    lines.append("  3) 用命令行下（Windows PowerShell）")
    lines.append(
        '         curl.exe -L "{}" -o "{}"'.format(
            url, os.path.join(dest_dir, name)
        )
    )
    lines.append("")
    lines.append("  4) 从官方仓库获取权重链接")
    lines.append("         {}".format(OFFICIAL_REPO))
    lines.append("         {}".format(WEIGHT_PAGE))
    lines.append("")
    lines.append("文件大小参考（明显小于它说明没下完）：")
    for k in ("vit_b", "vit_l", "vit_h"):
        lines.append(
            "    {}  {}   {}".format(
                WEIGHT_FILES[k], fmt_size(EXPECTED_SIZE[k][0]), k
            )
        )
    lines.append("")
    lines.append("当前查找过的目录：")
    lines.extend(describe_search(model_key))
    lines.append("=" * 62)
    return "\n".join(lines)


def human_report(model_key):
    """给 download_model.py --check 用的状态报告。"""
    key = normalize_key(model_key)
    name = WEIGHT_FILES[key]
    path = find_weight(key)
    lines = ["模型档位: {}    文件: {}".format(key, name)]
    lines.append("状态: {}".format("已就绪 -> " + path if path else "未找到"))
    lines.extend(describe_search(key))
    return "\n".join(lines)


__all__ = [
    "SamWeightError",
    "WEIGHT_FILES",
    "EXPECTED_SIZE",
    "candidate_dirs",
    "describe_search",
    "download_dir",
    "ensure_weight",
    "find_weight",
    "fmt_size",
    "human_report",
    "normalize_key",
    "project_root",
    "weight_filename",
]
