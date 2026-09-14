# Frfrida — W8 Frida CLI v3.1

Termux Frida SSL Unpinning Toolkit dengan CLI simpel (`fr <target> [script.js]`).

> **Disclaimer:** Hanya untuk pengujian keamanan pada aplikasi yang kamu miliki atau punya izin uji. Butuh perangkat **root** (Magisk).

---

## Instalasi (1 perintah, selesai langsung)

```bash
wget -qO- https://raw.githubusercontent.com/Ilham311/Frfrida/main/install.sh | bash
```

Installer langsung:
- Install semua paket yang dibutuhkan
- Daftarkan perintah `fr` secara global
- Install frida-server yang cocok dengan versi client

Setelah selesai, langsung bisa pakai tanpa restart Termux.

---

## Pemakaian

```bash
fr com.example.app          # bypass pakai script default (terbaru di folder ini)
fr tokopedia ssl.js         # nama paket & script boleh disingkat
fr spawn com.bank bypass.js # mode spawn (launch app baru)
fr --help                   # semua perintah
```

| Perintah | Fungsi |
|---|---|
| `fr <target> [script.js]` | Bypass (attach). Server auto-start bila mati, tidak restart kalau sudah jalan. |
| `fr spawn <target> [script]` | Bypass mode spawn. |
| `fr start` / `fr stop` / `fr restart` | Kelola server. |
| `fr status` | Versi Frida, port, nama server, status. |
| `fr install` / `fr update` | Install/Update Frida (client + server disamakan). |
| `fr list [filter]` | Daftar paket terpasang. |
| `fr scripts` | Daftar script `.js` yang terdeteksi. |
| `fr front` | Paket app yang sedang di depan layar. |
| `fr menu` | Menu interaktif. |

Script `.js` dibaca dari **folder saat ini** dan dari `~/.w8frida/scripts`.

---

## Fitur

- **Server pintar** — cek dulu sebelum start; tidak restart kalau sudah jalan.
- **Versi selalu cocok** — frida-server disamakan otomatis dengan versi client.
- **Stealth (default ON)** — port acak per sesi + nama proses menyamar daemon.
- **Fuzzy match** — nama paket & script boleh disingkat.
- **Mirror download** — fallback ke gh-proxy bila GitHub lambat.

---

## Requirement

- Termux (dari F-Droid atau GitHub, **bukan** Play Store)
- Perangkat **root** (Magisk)
- Python + `frida-python` (dipasang otomatis oleh installer)

---

## Struktur repo

```
Frfrida/
├── w8frida.py        # CLI utama
├── install.sh        # installer 1 perintah
├── README.md
├── LICENSE
└── scripts/
    └── bypass.js     # contoh SSL unpinning multi-framework
```

---

## Lisensi

MIT — lihat [LICENSE](LICENSE).
