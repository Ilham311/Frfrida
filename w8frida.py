#!/usr/bin/env python3
"""
W8 Frida CLI v2.1
=================
Termux Frida SSL Unpinning Toolkit — CLI + auto server.

Created by : W8SOJIB / W8Team
v2.1       : server auto-detect (tidak restart bila sudah jalan),
             CLI `fr` (fr <target> <script.js>), one-command install.
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import random
import string
import urllib.request

# --------------------------------------------------------------------------- #
# Konstanta & konfigurasi
# --------------------------------------------------------------------------- #

APP_NAME = "W8 Frida CLI"
APP_VERSION = "2.1"
AUTHOR = "W8SOJIB / W8Team"

PREFIX = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
LIBPYTHON = f"{PREFIX}/lib/libpython{sys.version_info.major}.{sys.version_info.minor}.so"
LOCAL_TMP = "/data/local/tmp"
FRIDA_HOME = f"{PREFIX}/tmp/frida-home"

# Home W8 Frida: config + binari + cache + scripts default (stabil, tak ikut cwd).
W8_HOME = os.environ.get("W8FRIDA_HOME", os.path.expanduser("~/.w8frida"))
CONFIG_FILE = os.path.join(W8_HOME, "config.json")
SERVER_BIN = os.path.join(W8_HOME, "frida-server")
SERVER_STAMP = os.path.join(W8_HOME, ".frida-server.version")
SCRIPTS_HOME = os.path.join(W8_HOME, "scripts")

# Folder script .js utama = folder saat ini (bisa dioverride lewat env).
SCRIPTS_DIR = os.environ.get("W8FRIDA_SCRIPTS", os.getcwd())

DEFAULT_CONFIG = {
    "frida_port": 37123,
    "server_name": ".w8fs",
    "last_package": "",
    "last_script": "",
    "stealth": True,
    "random_port": True,
}

# Nama proses samaran yang menyerupai daemon sistem (dipilih acak saat stealth).
STEALTH_NAMES = [".logd-aux", ".kworkerd", ".mediaserverd", ".netd-helper",
                 ".system_cache", ".dhcpcd6", ".installd-tmp"]


def ensure_home():
    os.makedirs(W8_HOME, exist_ok=True)
    os.makedirs(SCRIPTS_HOME, exist_ok=True)


def load_config():
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
        with open(CONFIG_FILE, "w") as f:
            json.dump(CONFIG, f, indent=4)
    except Exception:
        pass


CONFIG = load_config()


def frida_host():
    return f"127.0.0.1:{CONFIG['frida_port']}"


# --------------------------------------------------------------------------- #
# Lapisan UI (warna, log, banner, prompt)
# --------------------------------------------------------------------------- #

class Ansi:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    GREY = "\033[90m"


def _p(prefix, color, msg):
    print(f"{color}{prefix}{Ansi.RESET} {msg}")


def info(msg):
    _p("[*]", Ansi.GREY, msg)


def ok(msg):
    _p("[\u2713]", Ansi.GREEN, msg)


def warn(msg):
    _p("[!]", Ansi.YELLOW, msg)


def err(msg):
    _p("[\u2717]", Ansi.RED, msg)


def step(msg):
    print(f"\n{Ansi.CYAN}{Ansi.BOLD}\u25b8 {msg}{Ansi.RESET}")


def ask(prompt, default=""):
    suffix = f" {Ansi.GREY}[{default}]{Ansi.RESET}" if default else ""
    try:
        raw = input(f"{Ansi.YELLOW}?{Ansi.RESET} {prompt}{suffix}: ").strip()
    except EOFError:
        return default
    return raw or default


def confirm(prompt, default=True):
    hint = "Y/n" if default else "y/N"
    raw = input(f"{Ansi.YELLOW}?{Ansi.RESET} {prompt} {Ansi.GREY}[{hint}]{Ansi.RESET}: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes")


def banner():
    os.system("clear")
    width = 52
    line = "\u2550" * width
    def row(text, color=""):
        print(f"{Ansi.CYAN}\u2551{Ansi.RESET}{color}{text.center(width)}{Ansi.RESET}{Ansi.CYAN}\u2551{Ansi.RESET}")
    print(f"{Ansi.CYAN}\u2554{line}\u2557{Ansi.RESET}")
    row(f"{APP_NAME}  v{APP_VERSION}", Ansi.BOLD + Ansi.GREEN)
    row("Termux Frida SSL Unpinning Toolkit", Ansi.YELLOW)
    row(f"by {AUTHOR}", Ansi.GREY)
    print(f"{Ansi.CYAN}\u255a{line}\u255d{Ansi.RESET}")


# --------------------------------------------------------------------------- #
# Lapisan shell / root
# --------------------------------------------------------------------------- #

def sh(cmd, timeout=None, capture=False):
    """Jalankan perintah shell. Return (sukses, output)."""
    try:
        if capture:
            r = subprocess.run(cmd, shell=True, timeout=timeout,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            return r.returncode == 0, r.stdout.strip()
        r = subprocess.run(cmd, shell=True, timeout=timeout)
        return r.returncode == 0, ""
    except subprocess.TimeoutExpired:
        return False, ""
    except Exception as e:
        return False, str(e)


def out(cmd, timeout=None):
    return sh(cmd, timeout=timeout, capture=True)[1]


def su(cmd, timeout=None, capture=False):
    return sh(f"su -c {shlex.quote(cmd)}", timeout=timeout, capture=capture)


def su_out(cmd, timeout=None):
    return su(cmd, timeout=timeout, capture=True)[1]


def have_root():
    return sh("su -c id", timeout=8, capture=True)[0]


# --------------------------------------------------------------------------- #
# Environment Frida
# --------------------------------------------------------------------------- #

def ensure_frida_home():
    for sub in ("", "/.config", "/.cache", "/.local/share"):
        os.makedirs(FRIDA_HOME + sub, exist_ok=True)


def frida_env(cmd):
    home = shlex.quote(FRIDA_HOME)
    return (
        f"HOME={home} XDG_CONFIG_HOME={home}/.config "
        f"XDG_CACHE_HOME={home}/.cache XDG_DATA_HOME={home}/.local/share "
        f"LD_PRELOAD={shlex.quote(LIBPYTHON)} {cmd}"
    )


def frida_tool_ok():
    return sh(frida_env("frida-ps --version"), timeout=8)[0]


def frida_server_ok():
    """True kalau frida-server merespon di port config saat ini."""
    return sh(frida_env(f"frida-ps -H {frida_host()}"), timeout=8)[0]


# --------------------------------------------------------------------------- #
# Deteksi
# --------------------------------------------------------------------------- #

def detect_arch():
    abi = out("getprop ro.product.cpu.abi")
    if "arm64" in abi:
        return "android-arm64"
    if abi.startswith("arm"):
        return "android-arm"
    if "x86_64" in abi:
        return "android-x86_64"
    if abi == "x86":
        return "android-x86"
    return ""


def frontmost_package():
    raw = su_out("dumpsys activity activities | grep -E 'mResumedActivity|topResumedActivity'")
    m = re.search(r"([a-zA-Z0-9_.]+)/", raw)
    return m.group(1) if m else ""


def list_packages():
    for cmd in ("pm list packages -3", "pm list packages", "cmd package list packages"):
        raw = su_out(cmd)
        if "package:" in raw:
            pkgs = [l.replace("package:", "").strip()
                    for l in raw.splitlines() if l.startswith("package:")]
            if pkgs:
                return sorted(set(pkgs))
    return []


def package_pid(package):
    for p in su_out(f"pidof {package}").split():
        if p.isdigit():
            return p
    return ""


def launch_package(package):
    su(f"monkey -p {package} -c android.intent.category.LAUNCHER 1")
    time.sleep(2)


def detect_framework(package):
    paths = su_out(f"pm path {package}").replace("package:", "").split()
    if not paths:
        return []
    libs = su_out(f"unzip -l {shlex.quote(paths[0])}").lower()
    mapping = {
        "libflutter.so": "Flutter",
        "libunity.so": "Unity",
        "libreactnativejni.so": "React Native",
        "libmono.so": "Xamarin/Mono",
        "libgodot_android.so": "Godot",
    }
    return [name for lib, name in mapping.items() if lib in libs]


# --------------------------------------------------------------------------- #
# Script bypass
# --------------------------------------------------------------------------- #

def script_dirs():
    dirs, seen = [], []
    for d in (SCRIPTS_DIR, SCRIPTS_HOME):
        if d and os.path.isdir(d) and d not in seen:
            seen.append(d)
            dirs.append(d)
    return dirs


def available_scripts():
    """Semua .js dari folder saat ini + ~/.w8frida/scripts, terbaru dulu."""
    found = {}
    for d in script_dirs():
        try:
            for f in os.listdir(d):
                if f.endswith(".js"):
                    p = os.path.join(d, f)
                    if os.path.isfile(p) and f not in found:
                        found[f] = p
        except OSError:
            continue
    return sorted(found.values(), key=lambda p: os.path.getmtime(p), reverse=True)


def auto_pick_script():
    scripts = available_scripts()
    if not scripts:
        return ""
    last = CONFIG.get("last_script")
    for s in scripts:
        if os.path.basename(s) == last:
            return s
    return scripts[0]


def resolve_script(arg):
    scripts = available_scripts()
    if arg:
        if os.path.isfile(arg):
            return os.path.abspath(arg)
        for s in scripts:
            if os.path.basename(s) == arg:
                return s
        matches = [s for s in scripts if arg.lower() in os.path.basename(s).lower()]
        if len(matches) == 1:
            return matches[0]
        if matches:
            warn("Beberapa script cocok:")
            for i, s in enumerate(matches, 1):
                print(f"  {Ansi.GREEN}{i:>2}{Ansi.RESET}. {os.path.basename(s)}")
            sel = ask("Pilih nomor", "1")
            if sel.isdigit() and 1 <= int(sel) <= len(matches):
                return matches[int(sel) - 1]
            return ""
        warn(f"Script '{arg}' tidak ada, pakai default.")
    return auto_pick_script()


# --------------------------------------------------------------------------- #
# Stealth / anti-deteksi
# --------------------------------------------------------------------------- #

def _rand(n, alpha=string.ascii_lowercase + string.digits):
    return "".join(random.choices(alpha, k=n))


def stealth_on():
    return bool(CONFIG.get("stealth", True))


def pick_port():
    if not CONFIG.get("random_port", True):
        return int(CONFIG["frida_port"])
    while True:
        p = random.randint(20000, 65000)
        if p not in (27042, 27043):
            return p


def pick_proc_name():
    return f"{random.choice(STEALTH_NAMES)}{_rand(2)}"


# --------------------------------------------------------------------------- #
# Instalasi
# --------------------------------------------------------------------------- #

FRIDA_TOOLS = ["frida", "frida-ps", "frida-ls-devices", "frida-trace",
               "frida-discover", "frida-kill", "frida-apk"]


def fix_tool_wrappers():
    if not os.path.exists(LIBPYTHON):
        warn(f"libpython tidak ditemukan: {LIBPYTHON}")
        return False
    for tool in FRIDA_TOOLS:
        path = out(f"command -v {tool}")
        if not path or not os.path.isfile(path):
            continue
        real = f"{path}.real"
        try:
            with open(path, "r", errors="ignore") as fh:
                head = fh.read(256)
            if "W8_LDPRELOAD_WRAPPER" in head:
                continue
            if not os.path.exists(real):
                os.rename(path, real)
            wrapper = (
                f"#!{PREFIX}/bin/sh\n"
                "# W8_LDPRELOAD_WRAPPER\n"
                f'export LD_PRELOAD="{LIBPYTHON}${{LD_PRELOAD:+:$LD_PRELOAD}}"\n'
                f'exec "{real}" "$@"\n'
            )
            with open(path, "w") as fh:
                fh.write(wrapper)
            os.chmod(path, 0o755)
        except OSError as e:
            warn(f"Gagal memperbaiki {tool}: {e}")
    return True


def installed_frida_version():
    v = out(frida_env('python -c "import frida; print(frida.__version__)"'))
    if v and "Traceback" not in v and "Error" not in v:
        return v.strip()
    return ""


def latest_frida_version():
    try:
        api = "https://api.github.com/repos/frida/frida/releases/latest"
        data = json.loads(urllib.request.urlopen(api, timeout=20).read().decode())
        return data["tag_name"].lstrip("v")
    except Exception:
        return ""


def install_termux_packages():
    step("Menyiapkan paket Termux")
    sh("pkg update -y && pkg upgrade -y")
    sh("pkg install root-repo -y")
    sh("pkg update -y")
    return sh("pkg install wget xz-utils python git which frida-python -y")[0]


def install_frida_tools():
    ensure_frida_home()
    fix_tool_wrappers()
    if frida_tool_ok():
        ok("Frida tools siap")
        return True
    warn("Menginstal ulang frida-python")
    sh("pkg install frida-python -y")
    fix_tool_wrappers()
    if frida_tool_ok():
        ok("Frida tools siap")
        return True
    err("Frida tools gagal disiapkan (paket Termux mungkin tidak cocok)")
    return False


def target_version():
    """Versi server = versi client terpasang (WAJIB sama). Fallback: rilis terbaru."""
    return installed_frida_version() or latest_frida_version()


def server_urls(ver, fname):
    rel = f"frida/frida/releases/download/{ver}/{fname}"
    return [
        "https://github.com/" + rel,
        "https://gh-proxy.com/https://github.com/" + rel,
        "https://ghproxy.net/https://github.com/" + rel,
    ]


def download_frida_server(force=False):
    ensure_home()
    arch = detect_arch()
    if not arch:
        err("Arsitektur Android tidak didukung")
        return False
    ver = target_version()
    if not ver:
        err("Tidak bisa menentukan versi Frida")
        return False

    have = (os.path.exists(SERVER_BIN) and os.path.exists(SERVER_STAMP)
            and open(SERVER_STAMP).read().strip() == f"{ver}-{arch}")
    if have and not force:
        ok(f"frida-server {ver} sudah versi terbaru yang cocok")
        return True

    fname = f"frida-server-{ver}-{arch}.xz"
    tmp_xz = os.path.join(W8_HOME, fname)
    tmp_bin = os.path.join(W8_HOME, fname[:-3])
    step(f"Mengunduh frida-server {ver} ({arch})")
    downloaded = False
    for url in server_urls(ver, fname):
        if sh(f"wget -q -O {shlex.quote(tmp_xz)} {shlex.quote(url)}")[0] \
                and os.path.exists(tmp_xz) and os.path.getsize(tmp_xz) > 0:
            downloaded = True
            break
        warn("Sumber gagal, mencoba mirror berikutnya...")
    if not downloaded:
        err("Unduhan gagal dari semua sumber")
        return False
    sh(f"unxz -f {shlex.quote(tmp_xz)}")
    sh(f"mv -f {shlex.quote(tmp_bin)} {shlex.quote(SERVER_BIN)}")
    sh(f"chmod +x {shlex.quote(SERVER_BIN)}")
    with open(SERVER_STAMP, "w") as fh:
        fh.write(f"{ver}-{arch}")
    ok(f"frida-server {ver} siap")
    return True


def push_frida_server():
    if not os.path.exists(SERVER_BIN):
        return False
    src = os.path.abspath(SERVER_BIN)
    return su(f"mkdir -p {LOCAL_TMP}; cp {shlex.quote(src)} {LOCAL_TMP}/frida-server; "
              f"chmod 755 {LOCAL_TMP}/frida-server")[0]


def check_up_to_date():
    cur = installed_frida_version()
    latest = latest_frida_version()
    if cur and latest:
        if cur == latest:
            ok(f"Frida client sudah terbaru: v{cur}")
        else:
            warn(f"Frida client v{cur}, rilis terbaru v{latest}. "
                 "Jalankan 'fr install' untuk menyamakan.")
    return cur, latest


def install_frida():
    banner()
    step("Install / Update Frida")
    if not have_root():
        err("Akses root tidak tersedia")
        return False
    install_termux_packages()
    if not install_frida_tools():
        return False
    check_up_to_date()
    if not download_frida_server(force=True):
        return False
    push_frida_server()
    ok("Instalasi selesai")
    return True


# --------------------------------------------------------------------------- #
# Manajemen server (auto-detect: TIDAK restart bila sudah jalan)
# --------------------------------------------------------------------------- #

def ensure_server():
    """Pastikan server hidup TANPA restart kalau sudah aktif.
    Inti fitur v2.1: script tidak perlu start/stop manual lagi."""
    if frida_server_ok():
        ok(f"Server sudah aktif di {frida_host()} (tidak perlu start ulang)")
        return True
    info("Server belum jalan, memulai...")
    return start_server(force=True)


def start_server(force=True):
    if not os.path.exists(SERVER_BIN) and not download_frida_server():
        return False
    if not force and frida_server_ok():
        ok("Server sudah aktif — dibiarkan berjalan")
        return True
    if stealth_on():
        if CONFIG.get("random_port", True):
            CONFIG["frida_port"] = pick_port()
        CONFIG["server_name"] = pick_proc_name()
    push_frida_server()
    name = CONFIG["server_name"]
    target = f"{LOCAL_TMP}/{name}"
    label = "frida-server (stealth)" if stealth_on() else "frida-server"
    step(f"Menjalankan {label} sebagai {name} pada {frida_host()}")
    su(f"pkill -f {name}")
    su("pkill -f frida-server")
    su(f"cp -f {LOCAL_TMP}/frida-server {shlex.quote(target)}; chmod 755 {shlex.quote(target)}")
    su(f"rm -f {LOCAL_TMP}/frida-server")   # jangan tinggalkan nama asli
    try:
        subprocess.Popen(
            ["su", "-c", f"{target} -l {frida_host()}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            preexec_fn=os.setpgrp if hasattr(os, "setpgrp") else None,
        )
    except Exception as e:
        err(f"Gagal start: {e}")
        return False
    save_config()   # simpan port/nama agar sesi 'fr' berikutnya kenal server ini
    info("Menunggu server siap...")
    for _ in range(8):
        time.sleep(1)
        if frida_server_ok():
            ok("frida-server berjalan")
            return True
    warn("Server start, tapi koneksi client belum terverifikasi")
    return False


def stop_server():
    su(f"pkill -f frida-server; pkill -f {CONFIG['server_name']}")
    ok("frida-server dihentikan")


def server_status():
    if frida_server_ok():
        ok(f"Server AKTIF di {frida_host()}")
    else:
        warn("Server tidak aktif")


# --------------------------------------------------------------------------- #
# Menjalankan bypass
# --------------------------------------------------------------------------- #

def resolve_package(query):
    pkgs = list_packages()
    if not pkgs:
        return query
    if query in pkgs:
        return query
    matches = [p for p in pkgs if query.lower() in p.lower()]
    if len(matches) == 1:
        ok(f"Target cocok: {matches[0]}")
        return matches[0]
    if not matches:
        warn(f"Tidak ada paket cocok '{query}', pakai apa adanya.")
        return query
    warn(f"Beberapa paket cocok '{query}':")
    matches = matches[:20]
    for i, p in enumerate(matches, 1):
        print(f"  {Ansi.GREEN}{i:>2}{Ansi.RESET}. {p}")
    sel = ask("Pilih nomor", "1")
    if sel.isdigit() and 1 <= int(sel) <= len(matches):
        return matches[int(sel) - 1]
    return ""


def pick_package():
    q = ask("Filter nama paket (kosong = semua)").lower()
    pkgs = list_packages()
    if not pkgs:
        return ask("Ketik nama paket manual (mis. com.example)")
    matches = [p for p in pkgs if q in p.lower()] if q else pkgs
    if not matches:
        warn("Tidak ada paket cocok")
        return ""
    matches = matches[:40]
    print()
    for i, p in enumerate(matches, 1):
        print(f"  {Ansi.GREEN}{i:>2}{Ansi.RESET}. {p}")
    sel = ask("Pilih nomor / ketik paket")
    if sel.isdigit() and 1 <= int(sel) <= len(matches):
        return matches[int(sel) - 1]
    return sel


def run_bypass(package, script, spawn=False):
    # AUTO: hanya start kalau server mati; kalau sudah jalan, langsung pakai.
    if not ensure_server():
        return False
    script_path = os.path.abspath(script)
    script_name = os.path.basename(script_path)
    base = frida_env(f"frida -H {frida_host()}")

    def attach(args):
        return sh(f"{base} {args} -l {shlex.quote(script_path)}")[0]

    CONFIG["last_package"] = package
    CONFIG["last_script"] = script_name
    save_config()

    step("Menjalankan bypass")
    ok(f"Target : {package}")
    ok(f"Script : {script_name}")
    ok(f"Mode   : {'spawn' if spawn else 'attach'}")

    if spawn:
        if attach(f"-f {shlex.quote(package)}"):
            return True
        warn("Spawn gagal, beralih ke attach")
    launch_package(package)
    pid = package_pid(package)
    if pid:
        info(f"PID: {pid}")
        if attach(f"-p {pid}"):
            return True
    if attach(f"-n {shlex.quote(package)}"):
        return True
    err("Gagal attach ke aplikasi. Buka app manual lalu coba lagi.")
    return False


# --------------------------------------------------------------------------- #
# CLI (fr <target> <script.js> dan sub-perintah)
# --------------------------------------------------------------------------- #

def cli_run(rest, spawn=False):
    if "--spawn" in rest:
        spawn = True
        rest = [r for r in rest if r != "--spawn"]
    if not rest:
        err("Pemakaian: fr <target> [script.js]")
        return
    target = rest[0]
    script_arg = rest[1] if len(rest) > 1 else ""
    if not have_root():
        err("Akses root tidak tersedia. Perangkat harus di-root.")
        return
    if not frida_tool_ok():
        info("Frida belum terpasang, menginstal...")
        if not install_frida():
            return
    ensure_server()   # deteksi otomatis; tak restart bila sudah jalan
    package = resolve_package(target)
    if not package:
        return
    script = resolve_script(script_arg)
    if not script:
        err("Tidak ada script .js ditemukan (taruh di folder ini atau ~/.w8frida/scripts).")
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


def cli_list(rest):
    q = rest[0].lower() if rest else ""
    pkgs = list_packages()
    pkgs = [p for p in pkgs if q in p.lower()] if q else pkgs
    if not pkgs:
        warn("Tidak ada paket")
        return
    for p in pkgs:
        print(p)
    info(f"Total: {len(pkgs)}")


def cli_scripts():
    scripts = available_scripts()
    if not scripts:
        warn("Tidak ada script .js (folder ini / ~/.w8frida/scripts)")
        return
    for i, s in enumerate(scripts, 1):
        tag = "  <-- default" if s == auto_pick_script() else ""
        print(f"  {Ansi.GREEN}{i:>2}{Ansi.RESET}. {os.path.basename(s)}{tag}  {Ansi.GREY}{s}{Ansi.RESET}")


def print_help():
    print(f"""{Ansi.BOLD}{APP_NAME} v{APP_VERSION}{Ansi.RESET} — by {AUTHOR}

{Ansi.CYAN}Pemakaian:{Ansi.RESET}
  fr <target> [script.js]     Jalankan bypass (attach). Server auto-start bila mati.
  fr spawn <target> [script]  Jalankan bypass mode spawn.
  fr start                    Start server HANYA kalau belum jalan.
  fr stop                     Stop server.
  fr restart                  Paksa restart server.
  fr status                   Info versi & status server.
  fr install | update         Install/Update Frida (client + server).
  fr uninstall                Hapus Frida & file terkait.
  fr list [filter]            Daftar paket terpasang.
  fr scripts                  Daftar script .js yang terdeteksi.
  fr front                    Paket aplikasi yang sedang di depan.
  fr menu                     Buka menu interaktif.

{Ansi.CYAN}Contoh:{Ansi.RESET}
  fr com.example.app          # pakai script default (terbaru)
  fr tokopedia ssl.js         # cocokkan nama paket & script (boleh disingkat)
  fr spawn com.bank bypass.js
""")


# --------------------------------------------------------------------------- #
# Menu interaktif (opsional: 'fr menu' atau jalankan tanpa argumen)
# --------------------------------------------------------------------------- #

def quick_start():
    banner()
    step("Quick Start (otomatis)")
    if not have_root():
        err("Akses root tidak tersedia. Perangkat harus di-root.")
        return
    if not frida_tool_ok():
        info("Frida belum terpasang, memulai instalasi...")
        if not install_frida():
            return
    ensure_server()

    package = frontmost_package()
    if package and not confirm(f"Gunakan aplikasi aktif '{package}'?", True):
        package = ""
    if not package:
        package = pick_package()
    if not package:
        return

    frameworks = detect_framework(package)
    if frameworks:
        info(f"Framework terdeteksi: {', '.join(frameworks)}")
    scripts = available_scripts()
    if not scripts:
        err("Tidak ada script .js di folder ini")
        return
    script = auto_pick_script()
    info(f"Saran script: {os.path.basename(script)}  (Enter untuk pakai, atau pilih nomor lain)")
    for i, s in enumerate(scripts, 1):
        marker = "  <-- default" if s == script else ""
        print(f"  {Ansi.GREEN}{i:>2}{Ansi.RESET}. {os.path.basename(s)}{marker}")
    sel = ask("Nomor script", "")
    if sel.isdigit() and 1 <= int(sel) <= len(scripts):
        script = scripts[int(sel) - 1]
    run_bypass(package, script, spawn=False)


def advanced_run():
    banner()
    step("Run Script (Advanced)")
    scripts = available_scripts()
    if not scripts:
        err("Tidak ada script .js")
        return
    for i, s in enumerate(scripts, 1):
        print(f"  {Ansi.GREEN}{i:>2}{Ansi.RESET}. {os.path.basename(s)}")
    sel = ask("Pilih script", "1")
    if sel.isdigit() and 1 <= int(sel) <= len(scripts):
        script = scripts[int(sel) - 1]
    elif os.path.isfile(sel):
        script = sel
    else:
        err("Script tidak valid")
        return
    package = pick_package()
    if not package:
        return
    spawn = confirm("Gunakan mode spawn (launch baru)?", False)
    run_bypass(package, script, spawn=spawn)


def server_menu():
    banner()
    step("Kelola Server")
    print("  1. Start server (hanya bila mati)")
    print("  2. Stop server")
    print("  3. Restart server")
    print("  4. Status")
    choice = ask("Pilih", "4")
    if choice == "1":
        ensure_server()
    elif choice == "2":
        stop_server()
    elif choice == "3":
        start_server(force=True)
    else:
        server_status()


def _toggle(key, label):
    CONFIG[key] = not CONFIG.get(key, True)
    save_config()
    ok(f"{label}: {'ON' if CONFIG[key] else 'OFF'}")


def settings_menu():
    banner()
    step("Pengaturan")
    on = lambda k: "ON" if CONFIG.get(k, True) else "OFF"
    print(f"  1. Port                 : {CONFIG['frida_port']}")
    print(f"  2. Nama server          : {CONFIG['server_name']}")
    print(f"  3. Stealth mode         : {on('stealth')}")
    print(f"  4. Port acak per sesi   : {on('random_port')}")
    print("  5. Nama server acak sekarang")
    print("  0. Kembali")
    choice = ask("Pilih", "0")
    if choice == "1":
        p = ask("Port baru", str(CONFIG["frida_port"]))
        if p.isdigit():
            CONFIG["frida_port"] = int(p)
            save_config()
            ok("Port diperbarui")
    elif choice == "2":
        n = ask("Nama server (mis. .mysrv)")
        if n:
            CONFIG["server_name"] = n
            save_config()
            ok("Nama diperbarui")
    elif choice == "3":
        _toggle("stealth", "Stealth mode")
    elif choice == "4":
        _toggle("random_port", "Port acak per sesi")
    elif choice == "5":
        CONFIG["server_name"] = pick_proc_name()
        save_config()
        ok(f"Nama acak: {CONFIG['server_name']}")


def uninstall_frida():
    banner()
    step("Uninstall Frida")
    if not confirm("Yakin hapus Frida & file terkait?", False):
        return
    stop_server()
    for tool in FRIDA_TOOLS:
        path = out(f"command -v {tool}")
        real = f"{path}.real" if path else ""
        if path and os.path.exists(real):
            try:
                os.remove(path)
                os.rename(real, path)
                ok(f"Wrapper {tool} dipulihkan")
            except OSError as e:
                warn(f"{tool}: {e}")
    for t in (f"{LOCAL_TMP}/frida-server", f"{LOCAL_TMP}/{CONFIG['server_name']}"):
        su(f"rm -f {t}")
    for local_file in (SERVER_BIN, SERVER_STAMP):
        if os.path.exists(local_file):
            os.remove(local_file)
    if os.path.isdir(FRIDA_HOME):
        shutil.rmtree(FRIDA_HOME, ignore_errors=True)
    ok("Uninstall selesai. Jalankan 'pkg uninstall frida-python' bila perlu.")


def main_menu():
    actions = {
        "1": ("Quick Start (otomatis)", quick_start),
        "2": ("Run Script (advanced)", advanced_run),
        "3": ("Install / Update Frida", install_frida),
        "4": ("Kelola Server", server_menu),
        "5": ("Pengaturan", settings_menu),
        "6": ("Uninstall Frida", uninstall_frida),
    }
    while True:
        banner()
        print()
        for key, (label, _) in actions.items():
            print(f"  {Ansi.GREEN}{key}{Ansi.RESET}. {label}")
        print(f"  {Ansi.RED}0{Ansi.RESET}. Keluar")
        choice = ask("Pilih menu", "1")
        if choice == "0":
            print(f"{Ansi.CYAN}Bye{Ansi.RESET}")
            break
        entry = actions.get(choice)
        if not entry:
            err("Menu tidak valid")
            time.sleep(1)
            continue
        try:
            entry[1]()
        except KeyboardInterrupt:
            print()
            warn("Dibatalkan")
        input(f"\n{Ansi.GREY}Tekan Enter untuk lanjut...{Ansi.RESET}")


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #

def main():
    ensure_home()
    args = sys.argv[1:]
    if not args:
        return main_menu()
    cmd = args[0].lower()
    rest = args[1:]
    if cmd in ("-h", "--help", "help"):
        return print_help()
    if cmd in ("-v", "--version", "version"):
        return print(f"{APP_NAME} v{APP_VERSION}")
    if cmd == "menu":
        return main_menu()
    if cmd == "start":
        return ensure_server()
    if cmd == "restart":
        return start_server(force=True)
    if cmd == "stop":
        return stop_server()
    if cmd == "status":
        return cli_status()
    if cmd in ("install", "update"):
        return install_frida()
    if cmd == "uninstall":
        return uninstall_frida()
    if cmd == "list":
        return cli_list(rest)
    if cmd == "scripts":
        return cli_scripts()
    if cmd == "front":
        return print(frontmost_package() or "(tidak terdeteksi)")
    if cmd == "spawn":
        return cli_run(rest, spawn=True)
    if cmd == "run":
        return cli_run(rest, spawn=False)
    # default: 'fr <target> [script]'
    return cli_run(args, spawn=False)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Ansi.CYAN}Bye{Ansi.RESET}")
