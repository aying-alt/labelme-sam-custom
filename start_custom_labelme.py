"""启动入口：加载本目录下的定制版 labelme 主窗口。

与 `python -m labelme` 的区别：
  1. 强制把本项目目录放在 sys.path 最前面，保证运行的是本仓库的 labelme，
     而不会是 site-packages 里 pip 装过的其它版本。
  2. 关闭 Qt 的窗口状态记忆、默认使用软件 OpenGL，避免部分显卡驱动下
     切换窗口后画面变黑 / 丢失。
  3. 未捕获异常会弹窗并打印堆栈，而不是静默退出（双击 bat 时窗口不会
     一闪而过）。
  4. 强制把窗口恢复成正常状态并置于前台。
     从终端（或自动化脚本）启动时，Windows 会把 STARTUPINFO 里的
     「最小化显示」传给子进程，导致窗口建在 (-21333, -21333) 这种屏幕外
     坐标上——进程活着、没有报错，但用户什么都看不见。这里先用 Qt 的
     windowState() 清掉 WindowMinimized，再延时用 Win32 的 SW_RESTORE
     兜一次底，最后把窗口摆到主屏中央。
  5. 单实例：若已有 labelme 窗口在运行，直接把它恢复并激活，避免反复
     双击堆出一堆看不见的进程。

用法：
    python start_custom_labelme.py [图片路径]

可选环境变量：
    LABELME_ONTOP=1        窗口强制置顶（默认关闭）
    LABELME_ALLOW_MULTI=1  允许同时开多个窗口（默认复用已开的那一个）
"""

import os
import sys
import threading
import traceback

# ---------------------------------------------------------------------------
# 1. 保证 import 到的是本目录的 labelme
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
if not sys.path or sys.path[0] != _HERE:
    sys.path.insert(0, _HERE)

# ---------------------------------------------------------------------------
# 2. Qt / OpenGL 环境（必须在 QApplication 之前设置）
# ---------------------------------------------------------------------------
os.environ.setdefault("QT_QPA_SAVE_STATE", "0")
os.environ.setdefault("QT_OPENGL", "software")
os.environ.setdefault("QT_DISABLE_GPU_ACCELERATION", "1")

from PyQt5 import QtCore  # noqa: E402

QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_UseSoftwareOpenGL)
QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_ShareOpenGLContexts)

from PyQt5.QtWidgets import QApplication, QMessageBox  # noqa: E402

WINDOW_TITLE = "labelme"  # 与 labelme.app.MainWindow 里的 setWindowTitle 一致


def _excepthook(exc_type, exc_value, exc_tb):
    """把未捕获异常完整打印出来，并弹窗提示，避免窗口无提示消失。"""
    text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    sys.stderr.write(text)
    sys.stderr.flush()
    try:
        box = QMessageBox()
        box.setIcon(QMessageBox.Critical)
        box.setWindowTitle("labelme 启动失败")
        box.setText("程序发生未处理的异常，详细信息如下：")
        box.setDetailedText(text)
        box.exec_()
    except Exception:
        pass


sys.excepthook = _excepthook


def _user32():
    """延迟导入 ctypes，非 Windows 上返回 None，不影响主流程。"""
    if not sys.platform.startswith("win"):
        return None
    try:
        import ctypes

        return ctypes.windll.user32
    except Exception:
        return None


def _find_labelme_window():
    """找已有的 labelme 主窗口。

    标题会随打开的文件变化：`labelme` / `labelme - a.jpg` / `labelme - a.jpg*`
    （见 labelme/app.py 的 setClean / setDirty），所以必须按前缀匹配，
    不能只用 FindWindowW(None, "labelme")。
    只用 EnumWindows，且限定在本进程组之外——反正我们自己还没建窗口。
    """
    u32 = _user32()
    if u32 is None:
        return 0
    try:
        import ctypes

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        u32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
        u32.EnumWindows.argtypes = [WNDENUMPROC, ctypes.c_void_p]

        found = []

        def _cb(hwnd, _lparam):
            buf = ctypes.create_unicode_buffer(512)
            u32.GetWindowTextW(hwnd, buf, 512)
            title = buf.value
            if title == WINDOW_TITLE or title.startswith(WINDOW_TITLE + " - "):
                found.append(hwnd)
            return True

        u32.EnumWindows(WNDENUMPROC(_cb), None)
        return found[0] if found else 0
    except Exception:
        return 0


def _restore_existing_window():
    """若已有一个 labelme 窗口（可能是最小化/被挡住），恢复并激活它。

    返回 True 表示复用成功，调用方应直接退出。
    """
    if os.environ.get("LABELME_ALLOW_MULTI") == "1":
        return False
    hwnd = _find_labelme_window()
    if not hwnd:
        return False
    if not _win32_activate(hwnd):
        return False
    print("[labelme] 已有一个窗口在运行，已把它恢复并切到前台。")
    print("          想同时开多个窗口，先设 LABELME_ALLOW_MULTI=1 再启动。")
    return True


def _win32_activate(hwnd):
    """把窗口恢复并抢到前台，返回是否成功。

    Windows 有「前台锁」(foreground lock)：在 SetForegroundWindow 之前的
    一小段时间内，不是当前前台进程的窗口调用它会被系统**静默忽略**。
    从终端双击启动时正是这种情况——窗口建好了、位置也对，就是被终端
    盖在下面，用户以为没开。

    实测在本机：SetForegroundWindow、AttachThreadInput 附加输入队列都会
    返回 False，只有「先最小化再恢复」(SW_MINIMIZE → SW_RESTORE) 能拿到
    前台。所以这里以它为主，其余手段作兜底。
    """
    u32 = _user32()
    if u32 is None:
        return False
    try:
        import ctypes
        from ctypes import wintypes as wt

        u32.GetForegroundWindow.restype = wt.HWND
        u32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
        u32.BringWindowToTop.argtypes = [wt.HWND]
        u32.SetForegroundWindow.argtypes = [wt.HWND]

        hwnd = wt.HWND(hwnd)

        # 常规路径（窗口刚创建时通常就成功了，不会闪）
        u32.ShowWindow(hwnd, 9)  # SW_RESTORE
        u32.BringWindowToTop(hwnd)
        u32.SetForegroundWindow(hwnd)
        if u32.GetForegroundWindow() == hwnd:
            return True

        # 前台锁绕行：最小化再恢复
        u32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
        u32.ShowWindow(hwnd, 9)  # SW_RESTORE
        u32.BringWindowToTop(hwnd)
        u32.SetForegroundWindow(hwnd)
        if u32.GetForegroundWindow() == hwnd:
            return True

        # 最后的兜底：闪一下任务栏，至少让人知道窗口在哪
        try:
            u32.FlashWindow(hwnd, True)
        except Exception:
            pass
        return False
    except Exception:
        return False


def _force_foreground(win):
    """清掉最小化状态，并在窗口真正建起来之后抢前台。

    分三次尝试：窗口刚 show 出来的瞬间 Qt 还没拿到 native handle 的最终
    状态，单靠一次调用经常扑空；间隔重试可以把「终端又把焦点抢回去」
    这类情况也盖住。
    """

    def _qt_restore():
        try:
            state = win.windowState()
            win.setWindowState((state & ~QtCore.Qt.WindowMinimized) | QtCore.Qt.WindowActive)
            win.showNormal()
            win.raise_()
            win.activateWindow()
        except Exception:
            traceback.print_exc()

    def _win32_restore():
        try:
            _win32_activate(int(win.winId()))
        except Exception:
            pass

    _qt_restore()
    QtCore.QTimer.singleShot(120, _win32_restore)
    QtCore.QTimer.singleShot(600, _win32_restore)
    QtCore.QTimer.singleShot(1500, _win32_restore)


def _prepare_sam_weight(win):
    """窗口出来之后，在后台确认 HQ-SAM 权重；缺失就自动下载。

    设计要点：
      - 先做一次纯本地检查（不联网、毫秒级），已就绪就只打一行日志；
      - 缺失时开一个 daemon 线程下载，**不挡窗口**——用户可以立刻开始手工标注；
      - 进度直接写控制台（百分比 / 已下载 / 速度 / 剩余时间），由
        labelme.sam_weight 负责渲染；
      - 下载结果通过轮询回填到状态栏，避免跨线程碰 UI；
      - LABELME_NO_AUTO_DOWNLOAD=1 可完全关掉这个行为（离线环境用）。
    """
    if os.environ.get("LABELME_NO_AUTO_DOWNLOAD") == "1":
        print("[模型] 已设置 LABELME_NO_AUTO_DOWNLOAD=1，跳过权重检查。")
        return

    try:
        from labelme.sam_weight import SamWeightError, ensure_weight, find_weight
    except Exception as exc:  # 包不全时不要影响主流程
        print(f"[模型] 无法加载权重模块: {exc}")
        return

    try:
        model_key = win._config["sam"]["weights"]
    except Exception:
        model_key = "vit_h"

    print("")
    print("[模型] 检查 HQ-SAM 权重（档位 {}）...".format(model_key))

    existing = find_weight(model_key, verbose=True)
    if existing:
        print("[模型] 权重已就绪，SAM 半自动标注可用。")
        return

    print("[模型] 本地没有找到权重，开始在后台下载。")
    print("[模型] 下载期间窗口可以正常使用，只是 SAM 模式要等它下完。")
    print("[模型] 不想自动下载：关掉窗口，设 LABELME_NO_AUTO_DOWNLOAD=1 再启动。")

    result = {"path": None, "error": None, "done": False}

    def _worker():
        try:
            result["path"] = ensure_weight(model_key, allow_download=True)
        except SamWeightError as exc:
            result["error"] = str(exc)
            print(str(exc))
        except Exception as exc:
            result["error"] = str(exc)
            print(f"[模型] 下载过程出错: {exc}")
        finally:
            result["done"] = True

    threading.Thread(target=_worker, name="sam-weight-download", daemon=True).start()

    poll = QtCore.QTimer(win)
    poll.setInterval(800)

    def _tick():
        if not result["done"]:
            return
        poll.stop()
        try:
            if result["path"]:
                win.statusBar().showMessage(
                    "HQ-SAM 权重已就绪，可使用 SAM 半自动标注", 15000
                )
                print("[模型] 完成，切到 SAM 模式即可使用。")
            else:
                win.statusBar().showMessage(
                    "HQ-SAM 权重下载失败：SAM 不可用，纯手工标注不受影响", 30000
                )
                print("[模型] 权重未就绪，SAM 模式会自动退回普通多边形。")
        except Exception:
            pass

    poll.timeout.connect(_tick)
    poll.start()


def _center_on_primary(win, width=1280, height=820):
    """把窗口摆到主屏可用区域中央，并保证尺寸不超过屏幕。"""
    try:
        screen = QApplication.primaryScreen()
        avail = screen.availableGeometry()
        w = min(width, max(640, avail.width() - 60))
        h = min(height, max(480, avail.height() - 60))
        win.resize(w, h)
        x = avail.x() + (avail.width() - w) // 2
        y = avail.y() + (avail.height() - h) // 2
        win.move(x, y)
    except Exception:
        win.resize(width, height)


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)

    # 已经被开过一次了：把那个（可能最小化的）窗口叫回来，不再堆新进程
    if _restore_existing_window():
        return 0

    try:
        from labelme.app import MainWindow
    except Exception:
        traceback.print_exc()
        QMessageBox.critical(
            None,
            "labelme",
            "无法导入 labelme 模块。\n\n"
            "请先安装依赖：\n"
            "    python -m pip install -r requirements.txt\n\n"
            "详细报错见命令行窗口输出。",
        )
        return 1

    # 支持传入图片路径：python start_custom_labelme.py some.jpg
    filename = None
    for arg in sys.argv[1:]:
        if not arg.startswith("-") and os.path.isfile(arg):
            filename = arg
            break

    win = MainWindow(filename=filename)

    if os.environ.get("LABELME_ONTOP") == "1":
        win.setWindowFlags(win.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)

    _center_on_primary(win)
    win.show()
    _force_foreground(win)

    # 窗口先出来，权重检查和下载放到后台，不挡用户
    _prepare_sam_weight(win)

    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
