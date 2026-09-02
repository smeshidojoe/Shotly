"""
Самообновление через релизы GitHub.

Поток:
  1. check_update()        — есть ли релиз новее текущего (с zip-ассетом).
  2. download_update(url)  — качаем zip в <папка установки>/_update/update.zip.
  3. restart_to_update()   — достаём новый exe из архива, запускаем его с флагом
     --apply-update <старый exe> и немедленно выходим. Новый exe дожидается, пока
     старый освободится, подменяет его собой и запускает. Так можно заменить и
     работающий exe, который во время работы заблокирован.
  4. apply_pending_update()— страховка при старте: если zip остался (помощник не
     отработал), распаковываем то, что не заблокировано.

Только stdlib (urllib) — чтобы не тащить в сборку лишнего.
"""

import os
import shutil
import subprocess
import sys
import zipfile

from .constants import APP_NAME, APP_VERSION, GITHUB_REPO

API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

# Флаги отвязанного процесса (Windows): помощник переживает выход приложения.
_DETACHED = 0x00000008 | 0x00000200   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


_SSL_CTX = None


def ssl_context():
    """Контекст для наших HTTPS-запросов: системное хранилище ПЛЮС certifi.

    На машине с устаревшими корневыми сертификатами Windows проверка цепочки
    падает с «certificate has expired», и обновления молча перестают
    проверяться. certifi закрывает устаревшие корни системы, системное
    хранилище — корпоративные, которых нет в certifi.
    """
    global _SSL_CTX
    if _SSL_CTX is None:
        import ssl
        ctx = ssl.create_default_context()
        try:
            import certifi
            ctx.load_verify_locations(certifi.where())
        except Exception:
            pass                 # certifi нет — остаёмся на системном хранилище
        _SSL_CTX = ctx
    return _SSL_CTX


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def install_dir():
    """Папка установки (где лежит exe). В разработке — корень проекта."""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


UPDATE_DIR = os.path.join(install_dir(), "_update")
UPDATE_ZIP = os.path.join(UPDATE_DIR, "update.zip")
NEW_EXE    = os.path.join(UPDATE_DIR, APP_NAME + "-new.exe")


# ------------------------------------------------------------------ #
def _parse(v):
    """Версия в кортеж чисел; нечисловые части считаем нулём."""
    out = []
    for part in (v or "").lstrip("vV").split("."):
        num = "".join(c for c in part if c.isdigit())
        out.append(int(num) if num else 0)
    return tuple(out) or (0,)


def _is_newer(remote, current):
    return _parse(remote) > _parse(current)


def check_update(timeout=8):
    """
    Возвращает dict:
      {"status": "available"|"current"|"error",
       "version": tag, "download_url": zip|None, "notes": str, "error": str}
    """
    import json
    import urllib.request

    req = urllib.request.Request(
        API_URL,
        headers={"User-Agent": APP_NAME, "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout,
                                    context=ssl_context()) as resp:
            data = json.load(resp)
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

    tag = data.get("tag_name") or ""
    if not tag:
        return {"status": "error", "error": "no releases"}
    if not _is_newer(tag, APP_VERSION):
        return {"status": "current", "version": tag}

    zip_url = None
    for a in data.get("assets", []):
        if (a.get("name") or "").lower().endswith(".zip"):
            zip_url = a.get("browser_download_url")
            break

    return {"status": "available", "version": tag,
            "download_url": zip_url, "notes": data.get("body", "")}


def download_update(url, on_progress=None, timeout=60):
    """Качает zip в UPDATE_ZIP. on_progress(frac 0..1). Бросает при сбое."""
    import urllib.request

    if not url:
        raise RuntimeError("no download url")
    os.makedirs(UPDATE_DIR, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": APP_NAME})
    tmp = UPDATE_ZIP + ".part"
    with urllib.request.urlopen(req, timeout=timeout,
                                context=ssl_context()) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with open(tmp, "wb") as f:
            while True:
                chunk = resp.read(1024 * 64)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if on_progress and total:
                    on_progress(done / total)
    os.replace(tmp, UPDATE_ZIP)
    return True


def has_pending_update():
    return os.path.isfile(UPDATE_ZIP)


def apply_pending_update(target=None):
    """Страховка при старте: распаковать оставшийся zip поверх папки установки.
    Заблокированный exe так не заменить — это делает помощник."""
    if not has_pending_update():
        return False
    try:
        with zipfile.ZipFile(UPDATE_ZIP, "r") as zf:
            zf.extractall(target or install_dir())
        os.remove(UPDATE_ZIP)
        return True
    except Exception:
        return False


def _extract_new_exe():
    """Достаёт наш exe из скачанного zip рядом с программой, пока приложение ещё
    работает: файл новый, блокировок нет. Ищем на любой глубине архива по имени,
    иначе — первый .exe. Возвращает путь или None."""
    if not has_pending_update():
        return None
    try:
        want = os.path.basename(sys.executable).lower()
        with zipfile.ZipFile(UPDATE_ZIP, "r") as zf:
            names = zf.namelist()
            pick = next((n for n in names
                         if os.path.basename(n).lower() == want), None)
            if pick is None:
                pick = next((n for n in names if n.lower().endswith(".exe")), None)
            if pick is None:
                return None
            os.makedirs(UPDATE_DIR, exist_ok=True)
            with zf.open(pick) as src, open(NEW_EXE, "wb") as out:
                shutil.copyfileobj(src, out)
        return NEW_EXE
    except Exception:
        return None


def _log(msg):
    """Строка в _update/helper.log — единственный след обновления, если что-то
    пошло не так уже после выхода приложения."""
    try:
        import datetime
        os.makedirs(UPDATE_DIR, exist_ok=True)
        with open(os.path.join(UPDATE_DIR, "helper.log"), "a",
                  encoding="utf-8") as f:
            stamp = datetime.datetime.now().isoformat(timespec="seconds")
            f.write("[%s] %s\n" % (stamp, msg))
    except Exception:
        pass


def apply_self_update(target):
    """Выполняется НОВЫМ exe, запущенным с --apply-update <старый exe>: ждёт,
    пока старый освободится, подменяет его собой и запускает."""
    import time

    src = sys.executable
    if not target or not os.path.isfile(src):
        return False
    ok = False
    for _ in range(200):                      # до ~80 c ждём выхода старого
        try:
            shutil.copyfile(src, target)
            ok = True
            break
        except (PermissionError, OSError):
            time.sleep(0.4)
    _log("self-apply copy ok=%s -> %s" % (ok, target))
    # Целевой exe запускаем в любом случае: если подмена не удалась, пользователь
    # хотя бы не останется без программы.
    try:
        subprocess.Popen([target], creationflags=_DETACHED, close_fds=True,
                         cwd=os.path.dirname(target) or None)
    except Exception as exc:
        _log("relaunch err: %s" % exc)
    return ok


def cleanup_applied():
    """При старте убирает распакованный новый exe, если он совпал с текущим
    (обновление применилось). Иначе оставляем — можно повторить."""
    if not is_frozen() or not os.path.isfile(NEW_EXE):
        return
    try:
        if os.path.getsize(NEW_EXE) == os.path.getsize(sys.executable):
            os.remove(NEW_EXE)
    except OSError:
        pass


def restart_to_update():
    """Готовит новый exe и запускает подмену. После True вызывающий обязан
    немедленно выйти (os._exit), чтобы освободить свой exe-файл."""
    if not is_frozen() or not has_pending_update():
        return False
    new_exe = _extract_new_exe()
    if not new_exe or not os.path.isfile(new_exe):
        _log("restart_to_update: no new exe extracted")
        return False
    try:
        os.remove(UPDATE_ZIP)                 # exe извлечён, архив больше не нужен
    except OSError:
        pass
    try:
        subprocess.Popen(
            [new_exe, "--apply-update", os.path.abspath(sys.executable)],
            creationflags=_DETACHED, close_fds=True)
        _log("launched self-apply helper: %s" % new_exe)
        return True
    except Exception as exc:
        _log("self-apply launch failed: %s" % exc)
        return False


def _ps_lit(path):
    """Строковый литерал PowerShell: апостроф внутри пути удваивается, иначе
    путь вида C:\\Users\\O'Brien ломает разбор скрипта."""
    return "'" + str(path).replace("'", "''") + "'"


def relaunch_app():
    """Перезапуск ТОГО ЖЕ приложения (без обновления) — нужен после сброса
    настроек. Отвязанный помощник ждёт выхода текущего процесса по PID, иначе
    новый экземпляр упрётся в мьютекс единственного запуска, и стартует exe
    заново. Вызывающий обязан сразу выйти (os._exit). True — помощник запущен."""
    exe = os.path.abspath(sys.executable)
    pid = os.getpid()
    if is_frozen():
        script = (
            "$ErrorActionPreference='SilentlyContinue';\n"
            "$exe=%s; $procId=%d;\n" % (_ps_lit(exe), pid) +
            "try{ Wait-Process -Id $procId -Timeout 30 }catch{}\n"
            "Start-Process -FilePath $exe\n"
        )
        try:
            import base64
            # -EncodedCommand (base64 UTF-16LE) обходит проблемы кавычек и
            # кодировок командной строки — важно для путей с кириллицей.
            enc = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
            ps = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"),
                              "System32", "WindowsPowerShell", "v1.0",
                              "powershell.exe")
            if not os.path.isfile(ps):
                ps = "powershell"
            subprocess.Popen(
                [ps, "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-WindowStyle", "Hidden", "-EncodedCommand", enc],
                creationflags=_DETACHED, close_fds=True)
            _log("relaunch: helper launched")
            return True
        except Exception as exc:
            _log("relaunch failed: %s" % exc)
            return False

    # Режим разработки: просто поднимаем интерпретатор с теми же аргументами.
    try:
        subprocess.Popen([sys.executable] + sys.argv, close_fds=True)
        return True
    except Exception:
        return False
