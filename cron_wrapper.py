"""
cron_wrapper.py — Penentu JADWAL HARIAN secara acak.

BUKAN lagi "2 post sehari, siang + malam".

Yang diacak tiap hari:
  1. JUMLAH post hari ini  -> 0, 1, 2, atau 3
  2. JAM posting           -> titik acak antara 09:00 - 22:30
  3. JEDA antar post       -> minimal 3 jam

Contoh hasil:
  Hari A: 1 post jam 14:12
  Hari B: 3 post jam 09:47, 13:20, 21:05
  Hari C: 0 post (libur)
  Hari D: 2 post jam 11:33, 19:58

Cron manggil script ini tiap 30 menit. Script cek:
  "sekarang udah lewat jam target yang belum dijalankan?"
  kalau iya -> jalanin scheduler_v2

Cara pakai:
  python cron_wrapper.py            # cek & jalanin kalau waktunya
  python cron_wrapper.py --plan     # lihat rencana hari ini
  python cron_wrapper.py --replan   # bikin rencana baru (buang yang lama)
"""

import argparse
import json
import random
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
WIB = timezone(timedelta(hours=7))
STATE_FILE = BASE_DIR / "data" / "jitter_state.json"

# ── Konfigurasi ──────────────────────────────────────────────
# Peluang jumlah post per hari
N_POST_WEIGHTS = {
    0: 0.12,   # 12% libur (gak posting sama sekali)
    1: 0.38,   # 38% 1 post
    2: 0.50,   # 50% 2 post
}
# MAKSIMAL 2 POST/HARI — gak ada opsi 3.

JAM_MULAI = 9 * 60      # 09:00
JAM_SELESAI = 22 * 60 + 30   # 22:30
JEDA_MINIMAL = 180      # minimal 3 jam antar post

# Window buat cron ngecek (biar gak jalan tengah malem)
CEK_MULAI = 8 * 60
CEK_SELESAI = 23 * 60


# ─────────────────────────────────────────────────────────────
# STATE
# ─────────────────────────────────────────────────────────────

def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_state(s):
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(s, indent=2, ensure_ascii=False),
                          encoding="utf-8")


# ─────────────────────────────────────────────────────────────
# BIKIN RENCANA HARIAN
# ─────────────────────────────────────────────────────────────

def buat_rencana():
    """
    Bikin rencana acak buat hari ini.
    Return: {"n": jumlah_post, "targets": [menit1, menit2, ...], "done": []}
    """
    n = random.choices(
        list(N_POST_WEIGHTS.keys()),
        weights=list(N_POST_WEIGHTS.values()),
        k=1
    )[0]

    if n == 0:
        return {"n": 0, "targets": [], "done": []}

    # pilih n titik waktu, dengan jeda minimal
    targets = []
    percobaan = 0
    while len(targets) < n and percobaan < 200:
        percobaan += 1
        t = random.randint(JAM_MULAI, JAM_SELESAI)
        # cek jeda sama yang udah ada
        if all(abs(t - x) >= JEDA_MINIMAL for x in targets):
            targets.append(t)

    targets.sort()
    return {"n": n, "targets": targets, "done": []}


def fmt_menit(m):
    return f"{m // 60:02d}:{m % 60:02d}"


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def sync_notion(direction="pull", quiet=False):
    """Jalanin notion_sync tanpa ganggu proses posting kalau gagal."""
    try:
        r = subprocess.run(
            [sys.executable, str(BASE_DIR / "notion_sync.py"), f"--{direction}"],
            cwd=str(BASE_DIR), capture_output=True, text=True, timeout=120
        )
        if not quiet:
            print(r.stdout)
        if r.returncode != 0:
            print(f"[notion] {direction} gagal (gak ngaruh ke posting)")
        return r.returncode == 0
    except Exception as e:
        print(f"[notion] {direction} error: {e} (lanjut aja)")
        return False


def main():
    ap = argparse.ArgumentParser(description="Penentu jadwal harian acak")
    ap.add_argument("--plan", action="store_true", help="Lihat rencana hari ini")
    ap.add_argument("--replan", action="store_true", help="Bikin rencana baru")
    ap.add_argument("--force", action="store_true", help="Jalanin sekarang, abaikan jam")
    args = ap.parse_args()

    now = datetime.now(WIB)
    today = now.date().isoformat()
    current_min = now.hour * 60 + now.minute

    state = load_state()

    # AUTO PULL: ambil perubahan dari Notion sebelum posting
    if not args.plan:
        sync_notion("pull", quiet=True)

    # bikin / ambil rencana hari ini
    if args.replan or today not in state:
        state[today] = buat_rencana()
        save_state(state)

    plan = state[today]

    # ── mode lihat rencana ──
    if args.plan:
        print(f"\n{'='*58}")
        print(f"  RENCANA HARI INI — {now.strftime('%d %b %Y')}")
        print(f"{'='*58}")
        if plan["n"] == 0:
            print(f"\n  🛌 LIBUR — gak posting hari ini")
            print(f"     (10% hari memang libur, biar natural)")
        else:
            print(f"\n  Jumlah post: {plan['n']}")
            print(f"\n  {'#':>2}  {'Jam':>6}  {'Status':10}")
            print(f"  {'-'*24}")
            for i, t in enumerate(plan["targets"], 1):
                done = i <= len(plan["done"])
                status = "✅ udah" if done else "⏳ nunggu"
                print(f"  {i:>2}  {fmt_menit(t):>6}  {status}")
        print(f"\n  Window posting: {fmt_menit(JAM_MULAI)} - {fmt_menit(JAM_SELESAI)}")
        print(f"  Jeda minimal  : {JEDA_MINIMAL} menit")
        print(f"{'='*58}\n")
        return 0

    # ── di luar window? ──
    if not args.force and not (CEK_MULAI <= current_min <= CEK_SELESAI):
        print(f"[{fmt_menit(current_min)}] di luar window ({fmt_menit(CEK_MULAI)}-{fmt_menit(CEK_SELESAI)}), skip")
        return 0

    # ── libur? ──
    if plan["n"] == 0 and not args.force:
        print(f"[{fmt_menit(current_min)}] hari ini LIBUR (rencana 0 post)")
        return 0

    # ── cek tiap target ──
    ran = 0
    for i, target in enumerate(plan["targets"], 1):
        if i <= len(plan["done"]):
            continue   # udah jalan

        if not args.force and current_min < target:
            continue   # belum waktunya

        # tentuin slot berdasarkan jam
        slot = "Siang" if target < 15 * 60 else "Malam"

        print(f"\n[{fmt_menit(current_min)}] ▶ POST KE-{i} dari {plan['n']} "
              f"(target {fmt_menit(target)}, slot {slot})")

        r = subprocess.run(
            [sys.executable, str(BASE_DIR / "scheduler_v2.py"), slot, "--auto-slot"],
            cwd=str(BASE_DIR), capture_output=True, text=True, timeout=900
        )
        print(r.stdout)
        if r.returncode != 0 and r.stderr:
            print("STDERR:", r.stderr[-800:])

        plan["done"].append({"idx": i, "target": target,
                             "ran_at": datetime.now(WIB).isoformat(),
                             "rc": r.returncode})
        state[today] = plan
        save_state(state)
        ran += 1

        # AUTO PUSH: kirim status baru ke Notion
        if r.returncode == 0:
            sync_notion("push", quiet=True)

        if not args.force:
            break   # satu post per eksekusi, biar gak spam

    if ran == 0:
        sisa = [fmt_menit(t) for i, t in enumerate(plan["targets"], 1)
                if i > len(plan["done"])]
        print(f"[{fmt_menit(current_min)}] nunggu. Target belum lewat: {sisa or '-'}")

    # cleanup state lama (7 hari)
    if len(state) > 7:
        for k in sorted(state.keys())[:-7]:
            del state[k]
        save_state(state)

    return 0


if __name__ == "__main__":
    sys.exit(main())
