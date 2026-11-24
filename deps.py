import os
import sys
import shutil
import logging
import zipfile
import tarfile
import tempfile
import subprocess
import importlib
import urllib.request
import importlib.metadata as md

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FFMPEG_DIR = os.path.join(BASE_DIR, "ffmpeg")
FFMPEG_MARKER = os.path.join(FFMPEG_DIR, ".updated")
FFMPEG_MAX_AGE_DAYS = 30

PYTHON_PACKAGES = ["aiogram", "yt-dlp"]

FFMPEG_URLS = {
    "nt": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    "posix": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz",
}


def _pip(*args):
    subprocess.check_call([sys.executable, "-m", "pip", *args])


def ensure_pip():
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "--version"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        logging.info("pip не найден, пытаюсь установить через ensurepip...")
        subprocess.check_call([sys.executable, "-m", "ensurepip", "--upgrade"])


def ensure_python_packages():
    ensure_pip()
    missing = []
    for pkg in PYTHON_PACKAGES:
        try:
            md.version(pkg)
        except md.PackageNotFoundError:
            missing.append(pkg)

    if missing:
        logging.info(f"Устанавливаю отсутствующие пакеты: {', '.join(missing)}")
        _pip("install", *missing)

    # Обновляем все нужные пакеты до последних версий
    logging.info("Проверяю обновления пакетов...")
    _pip("install", "-U", *PYTHON_PACKAGES)
    importlib.invalidate_caches()


def _find_ffmpeg_binary():
    found = shutil.which("ffmpeg")
    if found:
        return found
    name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    local = os.path.join(FFMPEG_DIR, "bin", name)
    return local if os.path.exists(local) else None


def _is_ffmpeg_outdated():
    if not os.path.exists(FFMPEG_MARKER):
        return True
    import time
    age_days = (time.time() - os.path.getmtime(FFMPEG_MARKER)) / 86400
    return age_days > FFMPEG_MAX_AGE_DAYS


def _download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=300) as resp, open(dest, "wb") as f:
        shutil.copyfileobj(resp, f)


def _install_ffmpeg():
    if os.name != "nt" and sys.platform == "darwin":
        if shutil.which("brew"):
            logging.info("Устанавливаю ffmpeg через Homebrew...")
            subprocess.check_call(["brew", "install", "ffmpeg"])
            return
        raise RuntimeError("На macOS установите Homebrew и выполните: brew install ffmpeg")

    url = FFMPEG_URLS["nt" if os.name == "nt" else "posix"]
    logging.info(f"Скачиваю ffmpeg: {url}")
    tmp = tempfile.mkdtemp()
    archive = os.path.join(tmp, os.path.basename(url))
    _download(url, archive)

    if archive.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            z.extractall(tmp)
    else:
        with tarfile.open(archive) as t:
            t.extractall(tmp)

    bin_dir = os.path.join(FFMPEG_DIR, "bin")
    os.makedirs(bin_dir, exist_ok=True)
    wanted = {"ffmpeg", "ffmpeg.exe", "ffprobe", "ffprobe.exe"}
    copied = 0
    for root, _, files in os.walk(tmp):
        for fname in files:
            if fname in wanted:
                shutil.copy2(os.path.join(root, fname), os.path.join(bin_dir, fname))
                copied += 1
    if copied == 0:
        raise RuntimeError("В архиве ffmpeg не найдены исполняемые файлы")

    if os.name != "nt":
        for fname in ("ffmpeg", "ffprobe"):
            p = os.path.join(bin_dir, fname)
            if os.path.exists(p):
                os.chmod(p, 0o755)

    shutil.rmtree(tmp, ignore_errors=True)
    with open(FFMPEG_MARKER, "w") as f:
        f.write("ok")


def ensure_ffmpeg():
    binary = _find_ffmpeg_binary()
    if binary is None:
        if binary is None:
            logging.info("ffmpeg не найден, начинаю загрузку...")
        else:
            logging.info("Обновляю ffmpeg (локальная копия старше 30 дней)...")
        try:
            _install_ffmpeg()
        except Exception as e:
            if binary is None:
                raise RuntimeError(f"Не удалось установить ffmpeg: {e}")
            logging.warning(f"Не удалось обновить ffmpeg, использую текущую версию: {e}")

    # Добавляем папку с ffmpeg в PATH текущего процесса (yt-dlp будет её видеть)
    bin_dir = os.path.join(FFMPEG_DIR, "bin")
    if os.path.isdir(bin_dir) and bin_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")

    binary = _find_ffmpeg_binary()
    try:
        out = subprocess.run([binary, "-version"], capture_output=True, text=True, check=True)
        logging.info(f"ffmpeg готов: {out.stdout.splitlines()[0]}")
    except Exception as e:
        raise RuntimeError(f"ffmpeg установлен, но не запускается: {e}")


def bootstrap():
    logging.basicConfig(level=logging.INFO)
    ensure_python_packages()
    ensure_ffmpeg()
