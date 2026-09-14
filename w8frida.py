#!/usr/bin/env python3
"""
W8 Frida CLI v3.1  —  Termux Frida SSL Unpinning Toolkit
Pemakaian: fr <target> [script.js]
"""

import glob
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import time
import random
import string
import urllib.request

# ── Konstanta ──────────────────────────────────────────────────────────────── #

APP_NAME    = "W8 Frida CLI"
APP_VERSION = "3.1"
AUTHOR      = "W8SOJIB / W8Team"

PREFIX    = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
LOCAL_TMP = "/data/local/tmp"

W8_HOME      = os.environ.get("W8FRIDA_HOME", os.path.expanduser("~/.w8frida"))
CONFIG_FILE  = os.path.join(W8_HOME, "config.json")
SERVER_BIN   = os.path.join(W8_HOME, "frida-server")
SERVER_STAMP = os.path.join(W8_HOME, ".frida-server.version")
SCRIPTS_HOME = os.path.join(W8_HOME, "scripts")
SCRIPTS_DIR  = os.environ.get("W8FRIDA_SCRIPTS", os.getcwd())

DEFAULT_CONFIG: dict = {
    "frida_port":   37123,
    "server_name":  ".w8fs",
    "last_package": "",
    "last_script":  "",
    "stealth":      True,
    "random_port":  True,
}

STEALTH_NAMES = [
    ".logd-aux", ".kworkerd", ".mediaserverd",
    ".netd-helper", ".system_cache", ".dhcpcd6", ".installd-tmp",
]

FRIDA_TOOLS = [
    "frida", "frida-ps", "frida-ls-devices",
    "frida-trace", "frida-discover", "frida-kill", "frida-apk",
]

# Runtime cache — hindari panggilan su/shell berulang
_cache: dict = {}


# ── Config ─────────────────────────────────────────────────────────────────── #

def ensure_home():
    os.makedirs(W8_HOME, exist_ok=True)
    os.makedirs(SCRIPTS_HOME, exist_ok=True)


def load_config() -> dict:
    cfg = DEFAULT_CONFIG.copy()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    return cfg


def save_config():
    try:
        os.makedirs(W8_HOME, exist_ok=True)
        tmp = CONFIG_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(CONFIG, f, indent=4)
        os.replace(tmp, CONFIG_FILE)  # atomic
    except OSError as e:
        warn(f"Gagal simpan config: {e}")


CONFIG = load_config()


def frida_host() -> str:
    return f"127.0.0.1:{CONFIG['frida_port']}"


# ── UI ─────────────────────────────────────────────────────────────────────── #

class C:
    RST  = "\033[0m";  BOLD = "\033[1m"
    RED  = "\033[91m"; GRN  = "\033[92m"   # 'm' — bukan ']'
    YLW  = "\033[93m"; CYN  = "\033[96m"
    GRY  = "\033[90m"


def _p(pre: str, col: str, msg: str):
    print(f"{col}{pre}{C.RST} {msg}")

def info(m: str):  _p("[*]", C.GRY, m)
def ok(m: str):    _p("[+]", C.GRN, m)
def warn(m: str):  _p("[!]", C.YLW, m)
def err(m: str):   _p("[-]", C.RED, m)
def step(m: str):  print(f"\n{C.CYN}{C.BOLD}> {m}{C.RST}")


def ask(prompt: str, default: str = "") -> str:
    suf = f" {C.GRY}[{default}]{C.RST}" if default else ""
    try:
        raw = input(f"{C.YLW}?{C.RST} {prompt}{suf}: ").strip()
    except EOFError:
        return default
    return raw or default


def confirm(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    try:
        raw = input(f"{C.YLW}?{C.RST} {prompt} {C.GRY}[{hint}]{C.RST}: ").strip().lower()
    except EOFError:
        return default
    return (raw in ("y", "yes")) if raw else default


def banner():
    # Hanya clear jika berjalan di terminal interaktif
    if sys.stdout.isatty():
        os.system("clear")
    w = 52
    ln = "=" * w
    def row(t: str, col: str = ""):
        print(f"{C.CYN}|{C.RST}{col}{t.center(w)}{C.RST}{C.CYN}|{C.RST}")
    print(f"{C.CYN}+{ln}+{C.RST}")
    row(f"{APP_NAME}  v{APP_VERSION}", C.BOLD + C.GRN)
    row("Termux Frida SSL Unpinning Toolkit", C.YLW)
    row(f"by {AUTHOR}", C.GRY)
    print(f"{C.CYN}+{ln}+{C.RST}")


# ── Shell / root ───────────────────────────────────────────────────────────── #

def sh(cmd: str, timeout=None, capture: bool = False) -> tuple:
    """Jalankan shell command. Return (ok:bool, output:str)."""
    try:
        if capture:
            r = subprocess.run(
                cmd, shell=True, timeout=timeout,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            return r.returncode == 0, r.stdout.strip()
        r = subprocess.run(cmd, shell=True, timeout=timeout)
        return r.returncode == 0, ""
    except subprocess.TimeoutExpired:
        return False, ""
    except Exception as e:
        return False, str(e)


def out(cmd: str, timeout=None) -> str:
    return sh(cmd, timeout=timeout, capture=True)[1]


def su(cmd: str, timeout=None, capture: bool = False) -> tuple:
    return sh(f"su -c {shlex.quote(cmd)}", timeout=timeout, capture=capture)


def su_out(cmd: str, timeout=None) -> str:
    return su(cmd, timeout=timeout, capture=True)[1]


def have_root() -> bool:
    """Cek root sekali, cache hasilnya untuk sesi ini."""
    if "root" not in _cache:
        ok2, res = sh("su -c id", timeout=8, capture=True)
        _cache["root"] = ok2 and "uid=0" in res
    return _cache["root"]


# ── Frida env ──────────────────────────────────────────────────────────────── #

def _libpython() -> str:
    """Cari libpython.so yang paling baru di PREFIX/lib. Cached."""
    if "libpython" not in _cache:
        pattern = os.path.join(PREFIX, "lib", "libpython3*.so")
        matches = sorted(glob.glob(pattern), reverse=True)
        _cache["libpython"] = matches[0] if matches else ""
    return _cache["libpython"]


def frida_env(cmd: str) -> str:
    """Bungkus command dengan LD_PRELOAD libpython."""
    lib = _libpython()
    if not lib:
        return cmd
    # Gunakan env -S untuk keamanan, fallback ke export inline
    return f'LD_PRELOAD={shlex.quote(lib)} {cmd}'


def frida_ok() -> bool:
    """True kalau frida client bisa dijalankan."""
    if "frida_ok" not in _cache:
        ok2, res = sh(frida_env("frida --version"), timeout=8, capture=True)
        _cache["frida_ok"] = ok2 and bool(res) and "Error" not in res
    return _cache["frida_ok"]


def _tcp_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """Cek apakah port TCP terbuka — jauh lebih cepat dari frida-ps."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def frida_server_ok() -> bool:
    """True kalau frida-server merespon di port config."""
    port = int(CONFIG["frida_port"])
    # Langkah 1: cek TCP (< 100ms) — cepat, tidak spawn proses
    if not _tcp_open("127.0.0.1", port, timeout=1.0):
        return False
    # Langkah 2: verifikasi dengan frida-ps
    ok2, res = sh(frida_env(f"frida-ps -H {frida_host()}"), timeout=10, capture=True)
    return ok2 and "Unable" not in res and "Failed" not in res


# ── Deteksi ────────────────────────────────────────────────────────────────── #

def detect_arch() -> str:
    abi = out("getprop ro.product.cpu.abi")
    if "arm64" in abi:        return "android-arm64"
    if abi.startswith("arm"): return "android-arm"
    if "x86_64" in abi:       return "android-x86_64"
    if abi == "x86":          return "android-x86"
    err(f"Arsitektur tidak dikenali: {abi!r}")
    return ""


def frontmost_package() -> str:
    raw = su_out("dumpsys activity activities | grep -E 'mResumedActivity|topResumedActivity' | head -1")
    # Format: ActivityRecord{... com.example.app/.MainActivity ...}
    m = re.search(r'\{[^}]+\s+([a-zA-Z][a-zA-Z0-9_.]+)/\.?[A-Z]', raw)
    if m:
        return m.group(1)
    # Fallback: ambil com.xxx.yyy sebelum '/'
    m = re.search(r'([a-zA-Z][a-zA-Z0-9_]+(\.[a-zA-Z0-9_]+){1,})/[A-Za-z]', raw)
    return m.group(1) if m else ""


def list_packages(use_root: bool = False) -> list:
    """Daftar paket terpasang. Tidak perlu root untuk pm list packages."""
    runner = su_out if use_root else out
    for cmd in ("pm list packages -3", "pm list packages", "cmd package list packages"):
        raw = runner(cmd)
        if "package:" in raw:
            pkgs = [
                line.replace("package:", "").strip()
                for line in raw.splitlines()
                if line.startswith("package:")
            ]
            if pkgs:
                return sorted(set(pkgs))
    # Fallback ke root jika tanpa root gagal
    if not use_root:
        return list_packages(use_root=True)
    return []


def package_pid(package: str) -> str:
    for p in su_out(f"pidof {shlex.quote(package)}").split():
        if p.isdigit():
            return p
    return ""


def launch_package(package: str):
    """Buka app hanya jika belum berjalan."""
    pid = package_pid(package)
    if pid:
        info(f"App sudah berjalan (PID {pid}), tidak perlu launch ulang")
        return
    # am start dengan action MAIN + category LAUNCHER
    ok2, _ = su(
        f"am start -a android.intent.action.MAIN "
        f"-c android.intent.category.LAUNCHER "
        f"-n $(pm resolve-activity --components -a android.intent.action.MAIN "
        f"-c android.intent.category.LAUNCHER {shlex.quote(package)} 2>/dev/null "
        f"| head -1) 2>/dev/null"
    )
    if not ok2:
        # Fallback: am start langsung dengan package
        su(f"am start -a android.intent.action.MAIN "
           f"-c android.intent.category.LAUNCHER {shlex.quote(package)}")
    time.sleep(1.5)


def detect_framework(package: str) -> list:
    path_raw = su_out(f"pm path {shlex.quote(package)}")
    parts = path_raw.replace("package:", "").strip().split()
    if not parts:
        return []
    apk = parts[0]
    libs = su_out(f"unzip -l {shlex.quote(apk)} 2>/dev/null").lower()
    mapping = {
        "libflutter.so":        "Flutter",
        "libunity.so":          "Unity",
        "libreactnativejni.so": "React Native",
        "libmono.so":           "Xamarin/Mono",
        "libgodot_android.so":  "Godot",
    }
    return [name for lib, name in mapping.items() if lib in libs]


# ── Script ─────────────────────────────────────────────────────────────────── #

def available_scripts() -> list:
    """Kumpulkan .js dari cwd + ~/.w8frida/scripts, unik, terbaru dulu."""
    seen: set = set()
    result: list = []
    for d in dict.fromkeys([SCRIPTS_DIR, SCRIPTS_HOME]):
        if not (d and os.path.isdir(d)):
            continue
        try:
            for fname in os.listdir(d):
                if fname.endswith(".js"):
                    p = os.path.join(d, fname)
                    rp = os.path.realpath(p)
                    if os.path.isfile(p) and rp not in seen:
                        seen.add(rp)
                        result.append(p)
        except OSError:
            continue
    return sorted(result, key=lambda p: os.path.getmtime(p), reverse=True)


def auto_pick_script(scripts: list = None) -> str:
    """Pilih script default: last_script jika ada, lalu yang terbaru."""
    if scripts is None:
        scripts = available_scripts()
    if not scripts:
        return ""
    last = CONFIG.get("last_script", "")
    if last:
        for s in scripts:
            if os.path.basename(s) == last:
                return s
    return scripts[0]


def resolve_script(arg: str, scripts: list = None) -> str:
    """Cari script dari arg (nama/path/substring). Kembalikan path absolut atau ''."""
    if scripts is None:
        scripts = available_scripts()
    if arg:
        if os.path.isfile(arg):
            return os.path.abspath(arg)
        # Exact match nama file
        for s in scripts:
            if os.path.basename(s) == arg:
                return s
        # Substring match
        matches = [s for s in scripts if arg.lower() in os.path.basename(s).lower()]
        if len(matches) == 1:
            return matches[0]
        if matches:
            warn("Beberapa script cocok:")
            for i, s in enumerate(matches, 1):
                print(f"  {C.GRN}{i:>2}{C.RST}. {os.path.basename(s)}")
            sel = ask("Pilih nomor", "1")
            if sel.isdigit() and 1 <= int(sel) <= len(matches):
                return matches[int(sel) - 1]
            return ""
        warn(f"Script '{arg}' tidak ditemukan, pakai default.")
    return auto_pick_script(scripts)


# ── Stealth ────────────────────────────────────────────────────────────────── #

def _rand(n: int) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def stealth_on() -> bool:
    return bool(CONFIG.get("stealth", True))


def pick_port() -> int:
    if not CONFIG.get("random_port", True):
        return int(CONFIG["frida_port"])
    banned = {27042, 27043}
    for _ in range(30):
        p = random.randint(20000, 60000)
        if p in banned:
            continue
        if not _tcp_open("127.0.0.1", p, timeout=0.2):
            return p
    return random.randint(30000, 60000)


def pick_proc_name() -> str:
    return f"{random.choice(STEALTH_NAMES)}{_rand(2)}"


# ── Install ────────────────────────────────────────────────────────────────── #

def _fix_tool_wrappers():
    lib = _libpython()
    if not lib:
        warn("libpython tidak ditemukan, skip wrapper fix")
        return
    for tool in FRIDA_TOOLS:
        path = shutil.which(tool) or out(f"command -v {tool}").strip()
        if not path or not os.path.isfile(path):
            continue
        real = path + ".real"
        try:
            with open(path, "r", errors="ignore") as fh:
                if "W8_LDPRELOAD_WRAPPER" in fh.read(256):
                    continue
            # Backup dulu ke .real
            if not os.path.exists(real):
                shutil.copy2(path, real)  # copy2 preserves permissions
            # Tulis wrapper ke file tmp, baru replace secara atomic
            wrapper = (
                f"#!{PREFIX}/bin/sh\n"
                "# W8_LDPRELOAD_WRAPPER\n"
                f'export LD_PRELOAD="{lib}${{LD_PRELOAD:+:$LD_PRELOAD}}"\n'
                f'exec "{real}" "$@"\n'
            )
            tmp_path = path + ".w8tmp"
            with open(tmp_path, "w") as fh:
                fh.write(wrapper)
            os.chmod(tmp_path, 0o755)
            os.replace(tmp_path, path)  # atomic replace
        except OSError as e:
            warn(f"Gagal fix wrapper {tool}: {e}")


def installed_frida_version() -> str:
    """Ambil versi frida dari Python package (akurat setelah pip upgrade)."""
    if "frida_ver" not in _cache:
        # Prioritas: import frida — akurat meski pip upgrade melampaui Termux pkg
        ver = out(frida_env('python -c "import frida; print(frida.__version__)"'), timeout=10).strip()
        if not ver or "Error" in ver or "Traceback" in ver:
            # Fallback: frida --version (bisa stale kalau wrapper pakai binary lama)
            ver = out(frida_env("frida --version"), timeout=5).strip()
        if not ver or "Error" in ver or "\n" in ver:
            # Fallback terakhir: pkg show
            raw = out("pkg show frida-python 2>/dev/null | grep '^Version:'")
            ver = raw.replace("Version:", "").strip()
        _cache["frida_ver"] = ver.strip() if ver and "Error" not in ver and "Traceback" not in ver else ""
    return _cache["frida_ver"]


def latest_frida_version() -> str:
    """Ambil versi rilis terbaru Frida dari GitHub. Cached."""
    if "latest_ver" not in _cache:
        try:
            api = "https://api.github.com/repos/frida/frida/releases/latest"
            req = urllib.request.Request(api, headers={"User-Agent": "w8frida/3.1"})
            data = json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
            _cache["latest_ver"] = data["tag_name"].lstrip("v")
        except Exception:
            _cache["latest_ver"] = ""
    return _cache["latest_ver"]


def target_version() -> str:
    """Versi server = versi client. Fallback ke rilis terbaru."""
    return installed_frida_version() or latest_frida_version()


def _server_urls(ver: str, fname: str) -> list:
    rel = f"frida/frida/releases/download/{ver}/{fname}"
    return [
        "https://github.com/" + rel,
        "https://gh-proxy.com/https://github.com/" + rel,
        "https://ghproxy.net/https://github.com/" + rel,
    ]


def download_frida_server(force: bool = False) -> bool:
    ensure_home()
    arch = detect_arch()
    if not arch:
        return False
    ver = target_version()
    if not ver:
        err("Tidak bisa menentukan versi Frida")
        return False

    stamp_val = f"{ver}-{arch}"
    try:
        current = open(SERVER_STAMP).read().strip() if os.path.exists(SERVER_STAMP) else ""
    except OSError:
        current = ""

    if current == stamp_val and os.path.exists(SERVER_BIN) and not force:
        ok(f"frida-server {ver} ({arch}) sudah cocok")
        return True

    fname   = f"frida-server-{ver}-{arch}.xz"
    tmp_xz  = os.path.join(W8_HOME, fname)
    tmp_bin = tmp_xz[:-3]

    step(f"Mengunduh frida-server {ver} ({arch})")
    downloaded = False
    for url in _server_urls(ver, fname):
        info(f"Mencoba: {url}")
        # --progress=bar:force agar progress bar tampil, tanpa noise verbose
        ok2, _ = sh(f"wget --progress=bar:force -O {shlex.quote(tmp_xz)} {shlex.quote(url)} 2>&1")
        if ok2 and os.path.exists(tmp_xz) and os.path.getsize(tmp_xz) > 100_000:
            downloaded = True
            break
        warn("Gagal, mencoba mirror berikutnya...")
        try:
            os.remove(tmp_xz)
        except OSError:
            pass

    if not downloaded:
        err("Unduhan gagal dari semua sumber")
        return False

    ok2, _ = sh(f"unxz -f {shlex.quote(tmp_xz)}")
    if not ok2 or not os.path.exists(tmp_bin):
        err("Gagal ekstrak .xz")
        try:
            os.remove(tmp_xz)
        except OSError:
            pass
        return False

    try:
        shutil.move(tmp_bin, SERVER_BIN)
        os.chmod(SERVER_BIN, 0o755)
        with open(SERVER_STAMP, "w") as fh:
            fh.write(stamp_val)
    except OSError as e:
        err(f"Gagal simpan frida-server: {e}")
        return False

    ok(f"frida-server {ver} siap")
    return True


def _push_frida_server() -> bool:
    """Salin frida-server ke /data/local/tmp."""
    if not os.path.exists(SERVER_BIN):
        err("frida-server binary tidak ada di W8_HOME")
        return False
    src = shlex.quote(os.path.abspath(SERVER_BIN))
    ok2, msg = su(
        f"mkdir -p {LOCAL_TMP} && "
        f"cp {src} {LOCAL_TMP}/frida-server && "
        f"chmod 755 {LOCAL_TMP}/frida-server",
        capture=True
    )
    if not ok2:
        err(f"Gagal salin frida-server ke /data/local/tmp: {msg}")
    return ok2


def _print_version_gap():
    cur    = installed_frida_version()
    latest = latest_frida_version()  # sudah cached dari target_version()
    if cur and latest and cur != latest:
        warn(f"Client v{cur}, terbaru v{latest} — jalankan 'fr install' untuk update")


def install_frida() -> bool:
    banner()
    step("Install / Update Frida")
    if not have_root():
        err("Akses root tidak tersedia (butuh Magisk / perangkat root)")
        return False

    step("Menyiapkan paket Termux")
    # Hanya update index, TIDAK upgrade semua paket (menghindari gangguan)
    sh("pkg update -y 2>/dev/null || true")
    sh("pkg install root-repo -y 2>/dev/null || true")
    sh("pkg update -y 2>/dev/null || true")
    sh("pkg install -y wget xz-utils python which frida-python")
    # pkg repo Termux sering lagging versi, upgrade via pip agar selalu latest
    info("Mengupgrade frida via pip (PyPI)...")
    # --break-system-packages diperlukan di Python 3.11+ (PEP 668)
    ok2_pip, pip_out = sh(
        "pip install --upgrade frida --break-system-packages 2>&1 || "
        "pip install --upgrade frida 2>&1",
        timeout=120, capture=True
    )
    if ok2_pip:
        ok("frida diupgrade via pip")
        _cache["pip_upgraded"] = True
    else:
        # Tidak ada wheel untuk platform ini — versi pkg adalah tertinggi yang bisa dipasang
        _cache["pip_upgraded"] = False
        info("Tidak ada wheel baru untuk platform ini, tetap di versi pkg")

    # Invalidate frida cache setelah install
    _cache.pop("frida_ok", None)
    _cache.pop("frida_ver", None)
    _cache.pop("libpython", None)

    _fix_tool_wrappers()
    if not frida_ok():
        warn("Mencoba install ulang frida-python...")
        sh("pkg install frida-python -y")
        _cache.pop("frida_ok", None)
        _fix_tool_wrappers()
        if not frida_ok():
            err("Frida client gagal disiapkan")
            return False
    ok("Frida client siap")

    if not download_frida_server(force=True):
        return False
    if not _push_frida_server():
        return False

    # Restart server agar versi baru aktif
    if frida_server_ok():
        info("Server lama terdeteksi, merestart dengan versi baru...")
        stop_server()
        time.sleep(0.5)
    if not start_server(force=True):
        warn("Server belum berhasil distart — jalankan: fr start")

    # Refresh cache versi agar _print_version_gap akurat
    _cache.pop("frida_ver", None)
    _print_version_gap()
    ok("Instalasi selesai — jalankan: fr <target>")
    return True


# ── Server ─────────────────────────────────────────────────────────────────── #

def _kill_old_server():
    """Hentikan semua proses frida yang mungkin masih jalan (1 su call)."""
    name = CONFIG.get("server_name", "")
    pkill_name = f"; pkill -f {shlex.quote(name)} 2>/dev/null" if name else ""
    su(f"pkill -f frida-server 2>/dev/null{pkill_name}; true")


def start_server(force: bool = False) -> bool:
    """Jalankan frida-server. force=False = lewati kalau sudah aktif."""
    if not force and frida_server_ok():
        ok(f"Server sudah aktif di {frida_host()}")
        return True

    if not os.path.exists(SERVER_BIN) and not download_frida_server():
        return False
    if not _push_frida_server():
        return False

    # Tentukan port dan nama sebelum kill (agar tidak kill diri sendiri)
    if stealth_on():
        if CONFIG.get("random_port", True):
            CONFIG["frida_port"] = pick_port()
        CONFIG["server_name"] = pick_proc_name()
    save_config()

    name   = CONFIG["server_name"]
    target = f"{LOCAL_TMP}/{name}"
    label  = "frida-server (stealth)" if stealth_on() else "frida-server"

    step(f"Menjalankan {label} sebagai {C.BOLD}{name}{C.RST} @ port {CONFIG['frida_port']}")
    _kill_old_server()
    time.sleep(0.3)  # beri waktu proses lama benar-benar mati

    ok2, msg = su(
        f"cp -f {LOCAL_TMP}/frida-server {shlex.quote(target)} && "
        f"chmod 755 {shlex.quote(target)} && "
        f"rm -f {LOCAL_TMP}/frida-server",
        capture=True
    )
    if not ok2:
        err(f"Gagal menyiapkan binary server: {msg}")
        return False

    try:
        subprocess.Popen(
            ["su", "-c", f"{target} -l {frida_host()}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as e:
        err(f"Gagal start: {e}")
        return False

    # Tunggu pakai TCP check (cepat), bukan frida-ps (lambat)
    info("Menunggu server siap...")
    port = int(CONFIG["frida_port"])
    deadline = time.time() + 15
    while time.time() < deadline:
        time.sleep(0.5)
        if _tcp_open("127.0.0.1", port, timeout=0.5):
            # Konfirmasi sekali dengan frida-ps
            time.sleep(0.3)
            if frida_server_ok():
                ok(f"frida-server berjalan (port {port})")
                return True
    warn("Server dijalankan tapi koneksi belum terverifikasi (timeout 15s)")
    return False


def ensure_server() -> bool:
    """Nyalakan server hanya kalau belum aktif."""
    if frida_server_ok():
        ok(f"Server aktif di {frida_host()}")
        return True
    info("Server belum jalan, memulai...")
    return start_server(force=True)


def stop_server():
    _kill_old_server()
    name = CONFIG.get("server_name", "")
    targets = [f"{LOCAL_TMP}/frida-server"]
    if name:
        targets.append(f"{LOCAL_TMP}/{name}")
    rm_list = " ".join(shlex.quote(t) for t in targets)
    su(f"rm -f {rm_list} 2>/dev/null; true")
    ok("frida-server dihentikan")


def server_status():
    if frida_server_ok():
        ok(f"Server {C.BOLD}AKTIF{C.RST} di {frida_host()} | nama: {CONFIG['server_name']}")
    else:
        warn(f"Server tidak aktif (port terakhir: {CONFIG['frida_port']})")


# ── Bypass ─────────────────────────────────────────────────────────────────── #

def resolve_package(query: str) -> str:
    """Resolve nama paket dari query (exact / fuzzy). Return paket terpilih atau ''."""
    pkgs = list_packages()
    if not pkgs:
        warn("Tidak bisa mengambil daftar paket, pakai query apa adanya")
        return query
    if query in pkgs:
        return query
    matches = [p for p in pkgs if query.lower() in p.lower()]
    if len(matches) == 1:
        ok(f"Paket cocok: {matches[0]}")
        return matches[0]
    if not matches:
        warn(f"Paket '{query}' tidak ditemukan, pakai apa adanya")
        return query
    warn(f"{len(matches)} paket cocok '{query}':")
    shown = matches[:20]
    for i, p in enumerate(shown, 1):
        print(f"  {C.GRN}{i:>2}{C.RST}. {p}")
    sel = ask("Pilih nomor", "1")
    if sel.isdigit() and 1 <= int(sel) <= len(shown):
        return shown[int(sel) - 1]
    return ""


def pick_package() -> str:
    q = ask("Filter nama paket (kosong = semua)").lower()
    pkgs = list_packages()
    if not pkgs:
        return ask("Ketik nama paket (mis. com.example)")
    matches = [p for p in pkgs if q in p.lower()] if q else pkgs
    if not matches:
        warn("Tidak ada paket cocok")
        return ""
    shown = matches[:40]
    print()
    for i, p in enumerate(shown, 1):
        print(f"  {C.GRN}{i:>2}{C.RST}. {p}")
    sel = ask("Pilih nomor / ketik nama paket")
    if sel.isdigit() and 1 <= int(sel) <= len(shown):
        return shown[int(sel) - 1]
    return sel


def run_bypass(package: str, script: str, spawn: bool = False) -> bool:
    if not ensure_server():
        return False

    script_path = os.path.abspath(script)
    if not os.path.isfile(script_path):
        err(f"Script tidak ditemukan: {script_path}")
        return False

    CONFIG["last_package"] = package
    CONFIG["last_script"]  = os.path.basename(script_path)
    save_config()

    step("Menjalankan bypass")
    ok(f"Target : {package}")
    ok(f"Script : {os.path.basename(script_path)}")
    ok(f"Mode   : {'spawn' if spawn else 'attach'}")

    base = frida_env(f"frida -H {frida_host()}")
    script_q = shlex.quote(script_path)

    def attach(args: str) -> bool:
        return sh(f"{base} {args} -l {script_q}")[0]

    # Mode spawn
    if spawn:
        if attach(f"-f {shlex.quote(package)} --no-pause"):
            return True
        warn("Spawn gagal, beralih ke attach")

    # Cek apakah app sudah berjalan
    pid = package_pid(package)
    if not pid:
        info("App tidak berjalan, membuka...")
        launch_package(package)
        pid = package_pid(package)

    # Attach by PID dulu (paling andal)
    if pid:
        info(f"Attach ke PID {pid}")
        if attach(f"-p {pid}"):
            return True

    # Fallback: attach by name
    info("Fallback: attach by name")
    if attach(f"-n {shlex.quote(package)}"):
        return True

    err("Gagal attach ke aplikasi.")
    err("Coba: buka app manual, tunggu sebentar, lalu jalankan ulang.")
    return False


# ── CLI ────────────────────────────────────────────────────────────────────── #

def _require_root_frida() -> bool:
    """Pastikan root dan frida tersedia. Return False jika tidak."""
    if not have_root():
        err("Akses root tidak tersedia. Butuh perangkat root (Magisk).")
        return False
    if not frida_ok():
        info("Frida belum terpasang, memulai instalasi otomatis...")
        if not install_frida():
            return False
        # Refresh cache setelah install
        _cache.pop("frida_ok", None)
    return True


def cli_run(rest: list, spawn: bool = False):
    if "--spawn" in rest:
        spawn = True
        rest = [r for r in rest if r != "--spawn"]
    if not rest:
        err("Pemakaian: fr <target> [script.js]")
        return
    if not _require_root_frida():
        return

    package = resolve_package(rest[0])
    if not package:
        return

    scripts = available_scripts()  # ambil sekali, reuse
    script  = resolve_script(rest[1] if len(rest) > 1 else "", scripts)
    if not script:
        err("Tidak ada script .js ditemukan.")
        err(f"  Taruh file .js di folder ini atau {SCRIPTS_HOME}")
        return
    run_bypass(package, script, spawn=spawn)


def cli_status():
    cur = installed_frida_version()
    info(f"{APP_NAME} v{APP_VERSION}")
    info(f"Frida client : {cur or '(belum terpasang)'}")
    info(f"Port         : {CONFIG['frida_port']}")
    info(f"Server name  : {CONFIG['server_name']}")
    info(f"Stealth      : {'ON' if CONFIG.get('stealth', True) else 'OFF'}")
    info(f"Random port  : {'ON' if CONFIG.get('random_port', True) else 'OFF'}")
    server_status()


def cli_list(rest: list):
    q = rest[0].lower() if rest else ""
    step("Mengambil daftar paket...")
    pkgs = list_packages()
    pkgs = [p for p in pkgs if q in p.lower()] if q else pkgs
    if not pkgs:
        warn("Tidak ada paket ditemukan")
        return
    for p in pkgs:
        print(p)
    info(f"Total: {len(pkgs)}")


def cli_scripts():
    scripts = available_scripts()
    default = auto_pick_script(scripts)
    if not scripts:
        warn(f"Tidak ada script .js (cwd: {SCRIPTS_DIR} / {SCRIPTS_HOME})")
        return
    for i, s in enumerate(scripts, 1):
        tag = f"  {C.GRN}<-- default{C.RST}" if s == default else ""
        print(f"  {C.GRN}{i:>2}{C.RST}. {os.path.basename(s)}{tag}  {C.GRY}{s}{C.RST}")


def print_help():
    print(f"""{C.BOLD}{APP_NAME} v{APP_VERSION}{C.RST} — {AUTHOR}

{C.CYN}Pemakaian:{C.RST}
  fr <target> [script.js]       Bypass (attach). Server auto-start bila mati.
  fr spawn <target> [script]    Bypass mode spawn (launch app baru).
  fr start                      Nyalakan server (skip jika sudah jalan).
  fr stop                       Hentikan server.
  fr restart                    Paksa restart server.
  fr status                     Status versi & server.
  fr install | update           Install/Update Frida (client + server).
  fr uninstall                  Hapus file Frida.
  fr list [filter]              Daftar paket terpasang.
  fr scripts                    Daftar script .js yang terdeteksi.
  fr front                      Paket app yang sedang di depan layar.
  fr menu                       Menu interaktif.

{C.CYN}Contoh:{C.RST}
  fr com.example.app            # pakai script default
  fr tokopedia ssl.js           # nama paket & script boleh disingkat
  fr spawn com.bank bypass.js   # mode spawn

Script .js dibaca dari {C.GRY}<folder saat ini>{C.RST} dan {C.GRY}{SCRIPTS_HOME}{C.RST}
""")


# ── Menu interaktif ────────────────────────────────────────────────────────── #

def quick_start():
    banner()
    step("Quick Start")
    if not _require_root_frida():
        return
    ensure_server()

    package = frontmost_package()
    if package:
        info(f"App aktif: {C.BOLD}{package}{C.RST}")
        if not confirm(f"Gunakan '{package}'?", True):
            package = ""
    if not package:
        package = pick_package()
    if not package:
        return

    fw = detect_framework(package)
    if fw:
        info(f"Framework terdeteksi: {', '.join(fw)}")

    scripts = available_scripts()  # ambil sekali
    if not scripts:
        err(f"Tidak ada script .js di folder ini / {SCRIPTS_HOME}")
        return
    default = auto_pick_script(scripts)
    info(f"Script default: {C.BOLD}{os.path.basename(default)}{C.RST}")
    for i, s in enumerate(scripts, 1):
        marker = f"  {C.GRN}<-- default{C.RST}" if s == default else ""
        print(f"  {C.GRN}{i:>2}{C.RST}. {os.path.basename(s)}{marker}")
    sel = ask("Nomor script (Enter = default)", "")
    script = scripts[int(sel) - 1] if sel.isdigit() and 1 <= int(sel) <= len(scripts) else default
    run_bypass(package, script)


def advanced_run():
    banner()
    step("Run Script (Advanced)")
    if not _require_root_frida():
        return
    scripts = available_scripts()
    if not scripts:
        err("Tidak ada script .js")
        return
    for i, s in enumerate(scripts, 1):
        print(f"  {C.GRN}{i:>2}{C.RST}. {os.path.basename(s)}  {C.GRY}{s}{C.RST}")
    sel = ask("Pilih script", "1")
    if sel.isdigit() and 1 <= int(sel) <= len(scripts):
        script = scripts[int(sel) - 1]
    elif os.path.isfile(sel):
        script = os.path.abspath(sel)
    else:
        err("Script tidak valid")
        return
    package = pick_package()
    if not package:
        return
    spawn = confirm("Gunakan mode spawn (launch app baru)?", False)
    run_bypass(package, script, spawn=spawn)


def server_menu():
    banner()
    step("Kelola Server")
    print(f"  {C.GRN}1{C.RST}. Start  (skip jika sudah jalan)")
    print(f"  {C.GRN}2{C.RST}. Stop")
    print(f"  {C.GRN}3{C.RST}. Restart")
    print(f"  {C.GRN}4{C.RST}. Status")
    handlers = {
        "1": ensure_server,
        "2": stop_server,
        "3": lambda: start_server(force=True),
        "4": server_status,
    }
    choice = ask("Pilih", "4")
    handlers.get(choice, server_status)()


def _toggle(key: str, label: str):
    CONFIG[key] = not CONFIG.get(key, True)
    save_config()
    state = "ON" if CONFIG[key] else "OFF"
    ok(f"{label}: {C.BOLD}{state}{C.RST}")


def settings_menu():
    banner()
    step("Pengaturan")
    def on(k: str) -> str:
        return f"{C.GRN}ON{C.RST}" if CONFIG.get(k, True) else f"{C.RED}OFF{C.RST}"
    print(f"  {C.GRN}1{C.RST}. Port               : {CONFIG['frida_port']}")
    print(f"  {C.GRN}2{C.RST}. Nama server        : {CONFIG['server_name']}")
    print(f"  {C.GRN}3{C.RST}. Stealth mode       : {on('stealth')}")
    print(f"  {C.GRN}4{C.RST}. Port acak per sesi : {on('random_port')}")
    print(f"  {C.GRN}5{C.RST}. Acak nama server sekarang")
    print(f"  {C.RED}0{C.RST}. Kembali")
    choice = ask("Pilih", "0")
    if choice == "1":
        p = ask("Port baru", str(CONFIG["frida_port"]))
        if p.isdigit() and 1024 <= int(p) <= 65535:
            CONFIG["frida_port"] = int(p)
            save_config()
            ok("Port diperbarui")
        else:
            warn("Port tidak valid (1024-65535)")
    elif choice == "2":
        n = ask("Nama server baru (mis. .mysrv)")
        if n:
            CONFIG["server_name"] = n
            save_config()
            ok(f"Nama diperbarui: {n}")
    elif choice == "3":
        _toggle("stealth", "Stealth mode")
    elif choice == "4":
        _toggle("random_port", "Port acak per sesi")
    elif choice == "5":
        CONFIG["server_name"] = pick_proc_name()
        save_config()
        ok(f"Nama acak baru: {CONFIG['server_name']}")


def uninstall_frida():
    banner()
    step("Uninstall Frida")
    if not confirm("Yakin hapus frida-server & semua file terkait?", False):
        return
    stop_server()
    for tool in FRIDA_TOOLS:
        path = shutil.which(tool) or out(f"command -v {tool}").strip()
        if not path:
            continue
        real = path + ".real"
        if os.path.exists(real):
            try:
                os.remove(path)
                os.rename(real, path)
                ok(f"Wrapper {tool} dipulihkan")
            except OSError as e:
                warn(f"{tool}: {e}")
    for local_file in (SERVER_BIN, SERVER_STAMP):
        try:
            if os.path.exists(local_file):
                os.remove(local_file)
        except OSError:
            pass
    ok("Selesai. Jalankan 'pkg uninstall frida-python' bila perlu.")


def main_menu():
    actions = {
        "1": ("Quick Start (otomatis)",    quick_start),
        "2": ("Run Script (advanced)",      advanced_run),
        "3": ("Install / Update Frida",     install_frida),
        "4": ("Kelola Server",              server_menu),
        "5": ("Pengaturan",                settings_menu),
        "6": ("Uninstall Frida",            uninstall_frida),
    }
    while True:
        banner()
        print()
        for key, (label, _) in actions.items():
            print(f"  {C.GRN}{key}{C.RST}. {label}")
        print(f"  {C.RED}0{C.RST}. Keluar")
        choice = ask("Pilih menu", "1")
        if choice == "0":
            print(f"{C.CYN}Bye{C.RST}")
            break
        entry = actions.get(choice)
        if not entry:
            continue
        try:
            entry[1]()
        except KeyboardInterrupt:
            print()
            warn("Dibatalkan")
        try:
            input(f"\n{C.GRY}Tekan Enter untuk lanjut...{C.RST}")
        except (KeyboardInterrupt, EOFError):
            pass


# ── Dispatch ───────────────────────────────────────────────────────────────── #

def main():
    ensure_home()
    args = sys.argv[1:]
    if not args:
        return main_menu()
    cmd  = args[0].lower()
    rest = args[1:]
    dispatch = {
        "-h":        print_help,
        "--help":    print_help,
        "help":      print_help,
        "-v":        lambda: print(f"{APP_NAME} v{APP_VERSION}"),
        "--version": lambda: print(f"{APP_NAME} v{APP_VERSION}"),
        "version":   lambda: print(f"{APP_NAME} v{APP_VERSION}"),
        "menu":      main_menu,
        "start":     ensure_server,
        "restart":   lambda: start_server(force=True),
        "stop":      stop_server,
        "status":    cli_status,
        "install":   install_frida,
        "update":    install_frida,
        "uninstall": uninstall_frida,
        "list":      lambda: cli_list(rest),
        "scripts":   cli_scripts,
        "front":     lambda: print(frontmost_package() or "(tidak terdeteksi)"),
        "spawn":     lambda: cli_run(rest, spawn=True),
        "run":       lambda: cli_run(rest, spawn=False),
    }
    fn = dispatch.get(cmd)
    if fn:
        return fn()
    # default: fr <target> [script]
    return cli_run(args, spawn=False)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{C.CYN}Bye{C.RST}")
