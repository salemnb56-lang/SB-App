import threading
import socket
import datetime
import os
import time

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.core.window import Window
from kivy.clock import Clock
from kivy.utils import platform
from kivy.metrics import dp, sp

Window.clearcolor = (0.08, 0.09, 0.12, 1)

COLOR_BG_DARK      = (0.08, 0.09, 0.12, 1)
COLOR_BG_CARD      = (0.11, 0.13, 0.18, 1)
COLOR_BG_FIELD     = (0.06, 0.07, 0.10, 1)
COLOR_ACCENT_BLUE  = (0.13, 0.35, 0.65, 1)
COLOR_STATUS_ACTIVE = (0.18, 0.65, 0.40, 1)
COLOR_STATUS_IDLE   = (0.70, 0.20, 0.20, 1)
COLOR_TEXT_PRIMARY  = (0.88, 0.90, 0.95, 1)
COLOR_TEXT_DIM      = (0.45, 0.50, 0.60, 1)
COLOR_BORDER        = (0.18, 0.22, 0.30, 1)
COLOR_STOP_BTN      = (0.60, 0.12, 0.12, 1)
COLOR_QUICK_BTN     = (0.14, 0.18, 0.26, 1)

QUICK_PORTS = [
    ("VNC  5900", "5900"),
    ("VNC  5901", "5901"),
    ("خاص  1212", "1212"),
    ("ADB  5555", "5555"),
]

# ─── مسارات IPC المشتركة مع service.py ───────────────────────────────
def _ipc_base():
    if platform == "android":
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            ctx = PythonActivity.mActivity
            return ctx.getFilesDir().getAbsolutePath()
        except Exception:
            pass
    return os.path.expanduser("~")

_BASE = _ipc_base()
_CFG_FILE    = os.path.join(_BASE, "socket_config.txt")
_STATUS_FILE = os.path.join(_BASE, "socket_status.txt")
_LOG_FILE    = os.path.join(_BASE, "socket_log.txt")
_CMD_FILE    = os.path.join(_BASE, "socket_cmd.txt")


def _write_file(path, content):
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception:
        pass


def _read_file(path, default=""):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return default


def get_timestamp():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "غير متاح"


# ─── مدير الخدمة الخلفية ──────────────────────────────────────────────
class AndroidServiceManager:
    """يطلق service.py كخدمة أندرويد حقيقية أو يعود لـ threading خارج أندرويد."""

    def __init__(self):
        self._service = None
        self._use_android = platform == "android"

    def start(self, port):
        _write_file(_CFG_FILE, str(port))
        if self._use_android:
            try:
                from android import AndroidService
                svc = AndroidService(
                    "NetSocket Utility",
                    "مستمع TCP نشط على المنفذ {}".format(port),
                )
                svc.start("start")
                self._service = svc
                return True
            except Exception as e:
                return False
        return False

    def stop(self):
        _write_file(_CMD_FILE, "STOP")
        if self._use_android and self._service:
            try:
                self._service.stop()
            except Exception:
                pass
            self._service = None

    def is_android(self):
        return self._use_android


# ─── خيط الاستماع المحلي (احتياطي لغير أندرويد) ─────────────────────
class SocketListenerThread(threading.Thread):
    def __init__(self, port, log_cb, error_cb, stopped_cb):
        super().__init__(daemon=True)
        self.port = port
        self._log_cb    = log_cb
        self._error_cb  = error_cb
        self._stopped_cb = stopped_cb
        self._stop_event = threading.Event()
        self._sock = None

    def run(self):
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.settimeout(1.0)
            self._sock.bind(("0.0.0.0", self.port))
            self._sock.listen(5)
            ip = get_local_ip()
            Clock.schedule_once(
                lambda dt: self._log_cb(
                    "INFO: مستمع TCP نشط على {}:{}.".format(ip, self.port)
                ), 0
            )
            while not self._stop_event.is_set():
                try:
                    conn, addr = self._sock.accept()
                    Clock.schedule_once(
                        lambda dt, a=addr: self._log_cb(
                            "INFO: اتصال وارد من {}:{}.".format(a[0], a[1])
                        ), 0
                    )
                    conn.close()
                except socket.timeout:
                    continue
                except OSError:
                    break
        except PermissionError:
            Clock.schedule_once(
                lambda dt: self._error_cb(
                    "رفض الإذن. المنفذ {} يتطلب صلاحيات الجذر.".format(self.port)
                ), 0
            )
        except OSError as e:
            Clock.schedule_once(
                lambda dt: self._error_cb(
                    "فشل ربط المنفذ {}. قد يكون مقيداً أو قيد الاستخدام. [{}]".format(
                        self.port, getattr(e, "errno", "")
                    )
                ), 0
            )
        finally:
            self._cleanup()
            Clock.schedule_once(lambda dt: self._stopped_cb(), 0)

    def _cleanup(self):
        try:
            if self._sock:
                self._sock.close()
        except Exception:
            pass

    def stop(self):
        self._stop_event.set()
        self._cleanup()


# ─── لوحة السجل ──────────────────────────────────────────────────────
class LogPanel(ScrollView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.size_hint_y = None
        self.height = dp(180)
        self.bar_width = dp(4)
        self.bar_color = list(COLOR_ACCENT_BLUE)
        self.bar_inactive_color = list(COLOR_BORDER)
        self.effect_cls = "ScrollEffect"

        self._label = Label(
            text="",
            font_name="Roboto",
            font_size=sp(11),
            color=list(COLOR_TEXT_DIM),
            halign="right",
            valign="top",
            size_hint_y=None,
            markup=True,
        )
        self._label.bind(
            texture_size=lambda inst, val: setattr(inst, "height", val[1])
        )
        self._label.bind(
            width=lambda inst, val: setattr(inst, "text_size", (val, None))
        )
        self.add_widget(self._label)
        self._entries = []

    def append(self, message):
        ts = get_timestamp()
        entry = "[color=#6b7a99][{}][/color] {}".format(ts, message)
        self._entries.append(entry)
        if len(self._entries) > 200:
            self._entries = self._entries[-200:]
        self._label.text = "\n".join(self._entries)
        Clock.schedule_once(lambda dt: setattr(self, "scroll_y", 0), 0.05)

    def load_from_file(self):
        """تحميل السجل من ملف IPC الخاص بالخدمة الخلفية."""
        raw = _read_file(_LOG_FILE)
        if raw:
            self._entries = raw.strip().split("\n")[-200:]
            self._label.text = "\n".join(self._entries)
            Clock.schedule_once(lambda dt: setattr(self, "scroll_y", 0), 0.05)

    def clear(self):
        self._entries = []
        self._label.text = ""


class SectionLabel(Label):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.font_name = "Roboto"
        self.font_size = sp(10)
        self.color = list(COLOR_TEXT_DIM)
        self.halign = "right"
        self.valign = "middle"
        self.size_hint_y = None
        self.height = dp(22)
        self.bind(width=lambda inst, val: setattr(inst, "text_size", (val, None)))


# ─── الواجهة الرئيسية ─────────────────────────────────────────────────
class NetSocketRoot(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "vertical"
        self.padding = [dp(14), dp(10), dp(14), dp(10)]
        self.spacing = dp(8)

        self._is_running = False
        self._listener_thread = None
        self._svc_mgr = AndroidServiceManager()
        self._poll_event = None

        self._build_header()
        self._build_status_bar()
        self._build_port_section()
        self._build_quick_ports()
        self._build_action_button()
        self._build_log_section()

    # ── بناء الواجهة ──────────────────────────────────────────────────

    def _build_header(self):
        header = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(46))
        title = Label(
            text="NetSocket Utility",
            font_name="Roboto", font_size=sp(17), bold=True,
            color=list(COLOR_TEXT_PRIMARY), halign="right", valign="middle",
        )
        title.bind(size=lambda i, v: setattr(i, "text_size", v))
        subtitle = Label(
            text="أداة الشبكة المحلية",
            font_name="Roboto", font_size=sp(11),
            color=list(COLOR_TEXT_DIM), halign="left", valign="middle",
        )
        subtitle.bind(size=lambda i, v: setattr(i, "text_size", v))
        header.add_widget(subtitle)
        header.add_widget(title)
        self.add_widget(header)

    def _build_status_bar(self):
        from kivy.graphics import Color, RoundedRectangle
        bar = BoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(38),
            padding=[dp(10), dp(6), dp(10), dp(6)], spacing=dp(8),
        )
        with bar.canvas.before:
            Color(*COLOR_BG_CARD)
            bar._rect = RoundedRectangle(pos=bar.pos, size=bar.size, radius=[dp(6)])
        bar.bind(
            pos=lambda i, v: setattr(i._rect, "pos", v),
            size=lambda i, v: setattr(i._rect, "size", v),
        )
        self._status_dot = Label(
            text="●", font_size=sp(14), color=list(COLOR_STATUS_IDLE),
            size_hint_x=None, width=dp(20),
        )
        self._status_label = Label(
            text="خامل", font_name="Roboto", font_size=sp(13),
            color=list(COLOR_STATUS_IDLE), halign="right", valign="middle", bold=True,
        )
        self._status_label.bind(size=lambda i, v: setattr(i, "text_size", v))
        self._addr_label = Label(
            text="—", font_name="Roboto", font_size=sp(12),
            color=list(COLOR_TEXT_DIM), halign="left", valign="middle",
        )
        self._addr_label.bind(size=lambda i, v: setattr(i, "text_size", v))
        bar.add_widget(self._addr_label)
        bar.add_widget(self._status_label)
        bar.add_widget(self._status_dot)
        self.add_widget(bar)

    def _build_port_section(self):
        self.add_widget(SectionLabel(text="رقم المنفذ"))
        row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(44), spacing=dp(8))
        self._port_input = TextInput(
            hint_text="أدخل رقم المنفذ (1–65535)", text="5900",
            font_name="Roboto", font_size=sp(14), input_filter="int",
            multiline=False, foreground_color=list(COLOR_TEXT_PRIMARY),
            background_color=list(COLOR_BG_FIELD),
            cursor_color=list(COLOR_ACCENT_BLUE),
            padding=[dp(10), dp(10)], halign="center",
        )
        row.add_widget(self._port_input)
        self.add_widget(row)

    def _build_quick_ports(self):
        self.add_widget(SectionLabel(text="اختيار سريع للمنافذ"))
        grid = GridLayout(cols=4, size_hint_y=None, height=dp(44), spacing=dp(6))
        for label, port in QUICK_PORTS:
            btn = Button(
                text=label, font_name="Roboto", font_size=sp(11),
                background_color=list(COLOR_QUICK_BTN), background_normal="",
                color=list(COLOR_TEXT_PRIMARY),
                on_press=lambda inst, p=port: self._quick_select(p),
            )
            grid.add_widget(btn)
        self.add_widget(grid)

    def _build_action_button(self):
        self._action_btn = Button(
            text="بدء الاستماع", font_name="Roboto", font_size=sp(15), bold=True,
            size_hint_y=None, height=dp(52),
            background_color=list(COLOR_ACCENT_BLUE), background_normal="",
            background_down="", color=(1, 1, 1, 1),
            on_press=self._toggle_listener,
        )
        self.add_widget(self._action_btn)

    def _build_log_section(self):
        from kivy.graphics import Color, RoundedRectangle
        self.add_widget(SectionLabel(text="سجل النظام"))
        wrapper = BoxLayout(
            orientation="vertical", size_hint_y=None, height=dp(188),
            padding=[dp(8), dp(6), dp(8), dp(6)],
        )
        with wrapper.canvas.before:
            Color(*COLOR_BG_CARD)
            wrapper._rect = RoundedRectangle(pos=wrapper.pos, size=wrapper.size, radius=[dp(6)])
        wrapper.bind(
            pos=lambda i, v: setattr(i._rect, "pos", v),
            size=lambda i, v: setattr(i._rect, "size", v),
        )
        self._log = LogPanel()
        wrapper.add_widget(self._log)
        self.add_widget(wrapper)
        self._log.append("INFO: التطبيق جاهز. حدد المنفذ وابدأ الاستماع.")

    # ── المنطق ───────────────────────────────────────────────────────

    def _quick_select(self, port):
        self._port_input.text = port
        self._log.append("INFO: تم اختيار المنفذ {} من القائمة السريعة.".format(port))

    def _toggle_listener(self, *_):
        if self._is_running:
            self._stop_listener()
        else:
            self._start_listener()

    def _validate_port(self):
        txt = self._port_input.text.strip()
        if not txt.isdigit():
            self._log.append("تحذير: رقم المنفذ غير صالح.")
            return None
        port = int(txt)
        if not (1 <= port <= 65535):
            self._log.append("تحذير: المنفذ {} خارج النطاق المقبول (1–65535).".format(port))
            return None
        return port

    def _start_listener(self):
        port = self._validate_port()
        if port is None:
            return
        self._log.append("INFO: جارٍ محاولة الربط بالمنفذ {} ...".format(port))

        if self._svc_mgr.is_android():
            started = self._svc_mgr.start(port)
            if started:
                self._log.append("INFO: تم تشغيل الخدمة الخلفية على المنفذ {}.".format(port))
                self._set_running_state(port, get_local_ip())
                self._start_poll()
                return
            else:
                self._log.append(
                    "تحذير: تعذّر تشغيل الخدمة الخلفية، سيتم الاستماع عبر الخيط المحلي."
                )

        # احتياطي: استخدام الخيط المحلي
        self._listener_thread = SocketListenerThread(
            port=port,
            log_cb=self._on_log,
            error_cb=self._on_error,
            stopped_cb=self._on_thread_stopped,
        )
        self._listener_thread.start()
        self._set_running_state(port, get_local_ip())

    def _stop_listener(self):
        self._log.append("INFO: جارٍ إنهاء المستمع ...")
        self._stop_poll()
        if self._svc_mgr.is_android():
            self._svc_mgr.stop()
        if self._listener_thread:
            self._listener_thread.stop()
            self._listener_thread = None
        self._set_idle_state()

    def _start_poll(self):
        """استطلاع دوري لسجل الخدمة الخلفية (كل 2 ثانية)."""
        self._poll_event = Clock.schedule_interval(self._poll_service_log, 2.0)

    def _stop_poll(self):
        if self._poll_event:
            self._poll_event.cancel()
            self._poll_event = None

    def _poll_service_log(self, dt):
        self._log.load_from_file()
        status_raw = _read_file(_STATUS_FILE)
        lines = status_raw.strip().split("\n")
        status = lines[0] if lines else "IDLE"
        if status == "IDLE" and self._is_running:
            self._stop_poll()
            self._set_idle_state()
        elif status == "ERROR" and self._is_running:
            addr = lines[1] if len(lines) > 1 else ""
            self._log.append("خطأ: {}".format(addr))
            self._stop_poll()
            self._set_idle_state()

    def _set_running_state(self, port, ip):
        self._is_running = True
        self._status_dot.color = list(COLOR_STATUS_ACTIVE)
        self._status_label.text = "نشط"
        self._status_label.color = list(COLOR_STATUS_ACTIVE)
        self._addr_label.text = "{}:{}".format(ip, port)
        self._action_btn.text = "إيقاف الاستماع"
        self._action_btn.background_color = list(COLOR_STOP_BTN)
        self._port_input.disabled = True

    def _set_idle_state(self):
        self._is_running = False
        self._status_dot.color = list(COLOR_STATUS_IDLE)
        self._status_label.text = "خامل"
        self._status_label.color = list(COLOR_STATUS_IDLE)
        self._addr_label.text = "—"
        self._action_btn.text = "بدء الاستماع"
        self._action_btn.background_color = list(COLOR_ACCENT_BLUE)
        self._port_input.disabled = False

    def _on_log(self, msg):
        self._log.append(msg)

    def _on_error(self, msg):
        self._log.append("خطأ: {}".format(msg))
        self._set_idle_state()

    def _on_thread_stopped(self):
        if self._is_running:
            self._log.append("تحذير: توقف المستمع بشكل غير متوقع.")
            self._set_idle_state()
        else:
            self._log.append("INFO: تم إيقاف المستمع بنجاح.")


# ─── تطبيق Kivy ──────────────────────────────────────────────────────
class NetSocketApp(App):
    def build(self):
        self.title = "NetSocket Utility"
        self.icon = "icon.png"
        return NetSocketRoot()

    def on_pause(self):
        return True

    def on_resume(self):
        pass

    def on_stop(self):
        root = self.root
        if hasattr(root, "_is_running") and root._is_running:
            root._stop_listener()


if __name__ == "__main__":
    NetSocketApp().run()
