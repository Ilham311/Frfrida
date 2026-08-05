# Frfrida — W8 Frida CLI v2.1

Termux Frida SSL Unpinning Toolkit dengan **CLI simpel** (`fr <target> <script.js>`), **server auto-detect** (tidak restart kalau sudah jalan), dan **stealth** (port acak + nama proses menyamar daemon).

> ⚠️ **Disclaimer:** Alat ini hanya untuk **pengujian keamanan pada aplikasi yang kamu miliki atau punya izin uji**. Butuh perangkat **root** (Magisk). Segala penyalahgunaan di luar tanggung jawab pembuat.

---

## ✨ Fitur

- **Server pintar (anti restart).** Sebelum attach, tool cek `frida-ps` dulu. Kalau server sudah aktif → langsung dipakai; kalau mati → start otomatis sekali. Tidak perlu start/stop manual.
- **CLI ringkas.** `fr com.aplikasi script.js` — nama paket & script boleh disingkat (auto-match), script boleh dikosongkan (pakai yang terbaru).
- **Versi selalu cocok.** `frida-server` otomatis disamakan dengan versi `frida` client + cache per-versi + mirror unduhan.
- **Stealth (default ON).** Port acak per sesi (hindari 27042/27043) + nama proses samaran (mis. `.logd-aux`).
- **Load `.js` langsung dari Termux** via `-l` (tidak menyalin ke `/data/local/tmp`).

---

## 🚀 Instalasi (1 perintah)

```bash
pkg install curl -y && curl -fsSL https://raw.githubusercontent.com/Ilham311/Frfrida/main/install.sh | bash
```

Atau pakai `wget` (bawaan Termux):

```bash
wget -qO- https://raw.githubusercontent.com/Ilham311/Frfrida/main/install.sh | bash
```

Setelah itu:

```bash
source ~/.bashrc
fr install          # pasang Frida client + server (sekali di awal)
```

---

## 📖 Pemakaian

| Perintah | Fungsi |
|---|---|
| `fr <target> [script.js]` | Jalankan bypass (attach). Server auto-start bila mati, **tidak restart** kalau sudah jalan. |
| `fr spawn <target> [script]` | Bypass mode spawn (launch baru). |
| `fr start` / `fr stop` / `fr restart` | `start` hanya menyalakan bila mati; `restart` paksa nyalakan ulang. |
| `fr status` | Versi Frida, port, nama server, status aktif/mati. |
| `fr install` / `fr update` | Install/Update Frida (server disamakan versinya dengan client). |
| `fr list [filter]` | Daftar paket terpasang (bisa difilter). |
| `fr scripts` | Daftar script `.js` yang terdeteksi. |
| `fr front` | Paket aplikasi yang sedang di depan layar. |
| `fr menu` | Menu interaktif klasik. |

### Contoh

```bash
cd ~/scripts-ssl            # folder berisi file .js kamu
fr com.example.app         # pakai script terbaru otomatis
fr tokopedia ssl.js        # nama paket & script boleh disingkat
fr spawn com.bank bypass.js
```

Script `.js` dibaca dari **folder saat ini** dan dari `~/.w8frida/scripts`.

---

## 🕵️ Stealth

Default ON. Bisa dimatikan lewat `fr menu` → Pengaturan bila ada masalah kompatibilitas:

- **Port acak per sesi** — hindari default Frida `27042`/`27043` yang gampang di-scan.
- **Nama proses samaran** — biner dijalankan sebagai `.logd-aux`, `.kworkerd`, dll. Nama asli `frida-server` di `/data/local/tmp` langsung dihapus setelah disalin.

> Untuk stealth string/simbol tingkat lanjut, pakai `frida-server` hasil rebuild (strongR-frida / hluda) yang versinya dicocokkan manual dengan client.

---

## 📁 Struktur repo

```text
Frfrida/
├── w8frida.py        # CLI utama
├── install.sh        # installer 1 perintah
├── README.md
├── LICENSE
└── scripts/
    └── bypass.js     # contoh script SSL unpinning multi-framework
```

---

## 🛠️ Requirement

- Termux (disarankan dari F-Droid/GitHub, bukan Play Store)
- Perangkat **root** (Magisk)
- Python + `frida-python` (dipasang otomatis oleh installer)

---

## 📝 Lisensi

MIT — lihat berkas [LICENSE](LICENSE).
