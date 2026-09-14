#!/data/data/com.termux/files/usr/bin/bash
# W8 Frida CLI — one-command installer untuk Termux
set -e

REPO="Ilham311/Frfrida"
BRANCH="main"
RAW="https://raw.githubusercontent.com/$REPO/$BRANCH"
W8_HOME="$HOME/.w8frida"
FR_BIN="$PREFIX/bin/fr"

echo ""
echo "==> W8 Frida CLI Installer"
echo ""

# 1. Paket Termux
echo "[*] Update & install paket Termux..."
pkg update -y 2>/dev/null || true
pkg install root-repo -y 2>/dev/null || true
pkg update -y 2>/dev/null || true
pkg install -y wget xz-utils python git which frida-python

# 2. Unduh file CLI
echo "[*] Mengunduh W8 Frida CLI..."
mkdir -p "$W8_HOME/scripts"
wget -q -O "$W8_HOME/w8frida.py"       "$RAW/w8frida.py"
wget -q -O "$W8_HOME/scripts/bypass.js" "$RAW/scripts/bypass.js" || true

# 3. Perintah global 'fr'
echo "[*] Memasang perintah global 'fr'..."
cat > "$FR_BIN" << 'WRAPPER'
#!/data/data/com.termux/files/usr/bin/bash
exec python "$HOME/.w8frida/w8frida.py" "$@"
WRAPPER
chmod +x "$FR_BIN"

# 4. Env di .bashrc (idempoten)
if ! grep -q 'W8FRIDA_HOME' "$HOME/.bashrc" 2>/dev/null; then
  printf '\n# W8 Frida CLI\nexport W8FRIDA_HOME="%s"\n' "$W8_HOME" >> "$HOME/.bashrc"
fi

# 5. Install Frida client + server langsung sekarang
echo "[*] Menjalankan fr install (frida client + server)..."
export W8FRIDA_HOME="$W8_HOME"
python "$W8_HOME/w8frida.py" install

echo ""
echo "[+] SELESAI! Semua sudah terpasang."
echo ""
echo "Cara pakai:"
echo "  fr com.target            # bypass pakai script default"
echo "  fr com.target bypass.js  # bypass pakai script tertentu"
echo "  fr --help                # semua perintah"
echo ""
echo "(Jika 'fr' belum dikenali, ketik: source ~/.bashrc)"
