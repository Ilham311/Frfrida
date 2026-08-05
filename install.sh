#!/data/data/com.termux/files/usr/bin/bash
# W8 Frida CLI — one-command installer untuk Termux
set -e

REPO="Ilham311/Frfrida"
BRANCH="main"
RAW="https://raw.githubusercontent.com/$REPO/$BRANCH"
HOME_DIR="$HOME/.w8frida"

echo "==> Menyiapkan Termux..."
pkg update -y && pkg upgrade -y
pkg install root-repo -y || true
pkg update -y
pkg install python git wget xz-utils which frida-python -y

echo "==> Mengunduh W8 Frida CLI..."
mkdir -p "$HOME_DIR/scripts"
wget -q -O "$HOME_DIR/w8frida.py" "$RAW/w8frida.py"
# contoh script bypass (abaikan bila gagal)
wget -q -O "$HOME_DIR/scripts/bypass.js" "$RAW/scripts/bypass.js" || true

echo "==> Memasang perintah global 'fr'..."
cat > "$PREFIX/bin/fr" <<EOF
#!$PREFIX/bin/bash
exec python "$HOME_DIR/w8frida.py" "\$@"
EOF
chmod +x "$PREFIX/bin/fr"

# Tambah env ke .bashrc (sekali saja)
if ! grep -q "W8FRIDA_HOME" "$HOME/.bashrc" 2>/dev/null; then
  cat >> "$HOME/.bashrc" <<EOF

# --- W8 Frida CLI ---
export W8FRIDA_HOME="$HOME_DIR"
# Script .js dibaca dari folder saat ini + \$W8FRIDA_HOME/scripts
# Contoh: fr com.example bypass.js
EOF
fi

echo
echo "Selesai. Jalankan: source ~/.bashrc   (atau buka ulang Termux)"
echo "Lalu:  fr install     # sekali di awal"
echo "Pakai: fr com.target bypass.js"
