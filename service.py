"""
service.py — خدمة خلفية لـ NetSocket Utility
تعمل كعملية مستقلة على أندرويد وتبقى نشطة حتى عند إغلاق التطبيق.
"""

import socket
import threading
import datetime
import os
import time

# ─── مسارات ملفات IPC ───────────────────────────────────────────────
_BASE_DIR = os.environ.get("ANDROID_APP_PATH", "/data/data/com.netsocket.utility")
_CFG_FILE = os.path.join(_BASE_DIR, "socket_config.txt")
_STATUS_FILE = os.path.join(_BASE_DIR, "socket_status.txt")
_LOG_FILE = os.path.join(_BASE_DIR, "socket_log.txt")
_CMD_FILE = os.path.join(_BASE_DIR, "socket_cmd.txt")

_MAX_LOG_LINES = 300
_POLL_INTERVAL = 0.5

_running = True
_server_sock = None
_log_lines = []


def _ts():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _write_status(status, addr=""):
    try:
        with open(_STATUS_FILE, "w") as f:
            f.write("{}\n{}".format(status, addr))
    except Exception:
        pass


def _append_log(msg):
    global _log_lines
    entry = "[{}] {}".format(_ts(), msg)
    _log_lines.append(entry)
    if len(_log_lines) > _MAX_LOG_LINES:
        _log_lines = _log_lines[-_MAX_LOG_LINES:]
    try:
        with open(_LOG_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(_log_lines))
    except Exception:
        pass


def _get_local_ip():
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


def _read_port():
    try:
        with open(_CFG_FILE, "r") as f:
            return int(f.read().strip())
    except Exception:
        return 5900


def _show_foreground_notification(port):
    try:
        from jnius import autoclass
        import android

        PythonService = autoclass("org.kivy.android.PythonService")
        service = PythonService.mService
        Context = autoclass("android.content.Context")

        # إنشاء قناة الإشعارات لأندرويد 8.0+ فقط
        Build = autoclass("android.os.Build")
        if Build.VERSION.SDK_INT >= 26:
            NotificationChannel = autoclass("android.app.NotificationChannel")
            NotificationManager = autoclass("android.app.NotificationManager")
            nm = service.getSystemService(Context.NOTIFICATION_SERVICE)
            ch = NotificationChannel(
                "netsocket_svc",
                "NetSocket Service",
                NotificationManager.IMPORTANCE_LOW,
            )
            nm.createNotificationChannel(ch)
            channel_id = "netsocket_svc"
        else:
            channel_id = ""

        # بناء الإشعار
        if Build.VERSION.SDK_INT >= 26:
            Builder = autoclass("android.app.Notification$Builder")
            builder = Builder(service, channel_id)
        else:
            Builder = autoclass("android.support.v4.app.NotificationCompat$Builder")
            builder = Builder(service)

        builder.setContentTitle("NetSocket Utility")
        builder.setContentText("مستمع TCP نشط على المنفذ {}".format(port))
        builder.setSmallIcon(service.getApplicationInfo().icon)
        builder.setOngoing(True)

        notification = builder.build()
        service.startForeground(9001, notification)
        _append_log("INFO: تم تفعيل الخدمة الأمامية (Foreground Service).")
    except Exception as e:
        _append_log("تحذير: تعذّر تفعيل الخدمة الأمامية. [{}]".format(str(e)[:80]))


def _acquire_locks():
    try:
        from jnius import autoclass
        PythonService = autoclass("org.kivy.android.PythonService")
        service = PythonService.mService
        Context = autoclass("android.content.Context")
        PowerManager = autoclass("android.os.PowerManager")
        pm = service.getSystemService(Context.POWER_SERVICE)
        wl = pm.newWakeLock(
            PowerManager.PARTIAL_WAKE_LOCK,
            "NetSocketUtility::SvcWakeLock"
        )
        wl.acquire()
        WifiManager = autoclass("android.net.wifi.WifiManager")
        wm = service.getSystemService(Context.WIFI_SERVICE)
        wifi_lock = wm.createWifiLock(
            WifiManager.WIFI_MODE_FULL_HIGH_PERF,
            "NetSocketUtility::SvcWifiLock"
        )
        wifi_lock.acquire()
        _append_log("INFO: WakeLock و WifiLock مُفعَّلان.")
        return wl, wifi_lock
    except Exception as e:
        _append_log("تحذير: تعذّر الحصول على WakeLock. [{}]".format(str(e)[:60]))
        return None, None


def _socket_loop(port, stop_event):
    global _server_sock
    try:
        _server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        _server_sock.settimeout(1.0)
        _server_sock.bind(("0.0.0.0", port))
        _server_sock.listen(5)
        ip = _get_local_ip()
        addr_str = "{}:{}".format(ip, port)
        _write_status("ACTIVE", addr_str)
        _append_log("INFO: مستمع TCP نشط على {}.".format(addr_str))

        while not stop_event.is_set():
            try:
                conn, addr = _server_sock.accept()
                _append_log(
                    "INFO: اتصال وارد من {}:{}.".format(addr[0], addr[1])
                )
                conn.close()
            except socket.timeout:
                continue
            except OSError:
                break
    except PermissionError:
        _append_log(
            "خطأ: رفض الإذن. المنفذ {} يتطلب صلاحيات الجذر.".format(port)
        )
        _write_status("ERROR", "رفض الإذن")
    except OSError as e:
        _append_log(
            "خطأ: فشل ربط المنفذ {}. قد يكون مقيداً أو قيد الاستخدام. [{}]".format(
                port, e.errno if hasattr(e, "errno") else ""
            )
        )
        _write_status("ERROR", "فشل الربط")
    finally:
        try:
            if _server_sock:
                _server_sock.close()
        except Exception:
            pass
        _write_status("IDLE", "")
        _append_log("INFO: توقف المستمع.")


def _watch_commands(stop_event):
    """يراقب ملف الأوامر لاستقبال أمر الإيقاف من التطبيق."""
    while not stop_event.is_set():
        try:
            if os.path.exists(_CMD_FILE):
                with open(_CMD_FILE, "r") as f:
                    cmd = f.read().strip()
                if cmd == "STOP":
                    os.remove(_CMD_FILE)
                    _append_log("INFO: استُقبل أمر الإيقاف.")
                    stop_event.set()
                    return
        except Exception:
            pass
        time.sleep(_POLL_INTERVAL)


def main():
    global _running
    _write_status("STARTING", "")
    _append_log("INFO: بدء تشغيل خدمة NetSocket Utility.")

    port = _read_port()
    _show_foreground_notification(port)
    wl, wifi_lock = _acquire_locks()

    stop_event = threading.Event()

    socket_thread = threading.Thread(
        target=_socket_loop, args=(port, stop_event), daemon=True
    )
    socket_thread.start()

    cmd_thread = threading.Thread(
        target=_watch_commands, args=(stop_event,), daemon=True
    )
    cmd_thread.start()

    # الانتظار حتى يتوقف المستمع
    socket_thread.join()
    stop_event.set()

    # تحرير الأقفال
    try:
        if wl and wl.isHeld():
            wl.release()
        if wifi_lock and wifi_lock.isHeld():
            wifi_lock.release()
    except Exception:
        pass

    _append_log("INFO: انتهت الخدمة الخلفية.")
    _write_status("IDLE", "")


if __name__ == "__main__":
    main()
