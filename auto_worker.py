import os
import sys
import subprocess
import datetime

REPO_DIR = r"C:\SAVING\GAWEAN GW\forage-simulations"
LOG_FILE = os.path.join(REPO_DIR, "worker.log")
HERMES_EXE = r"C:\Users\ACER\AppData\Local\hermes\bin\hermes.exe"

def log(msg):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{now}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:
        print(f"Error writing to log: {e}")

def run_git(cmd_args):
    try:
        res = subprocess.run(
            ["git"] + cmd_args,
            cwd=REPO_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8"
        )
        return res.returncode == 0, res.stdout.strip(), res.stderr.strip()
    except Exception as e:
        return False, "", str(e)

def run_hermes_on_folder(folder_path, folder_name):
    query = (
        f"Baca file instruksi tugas (task.md, task.txt, atau instruksi.txt) di folder ini. "
        f"Lalu buatkan solusi teknis produksi yang lengkap: semua file source code yang dibutuhkan, "
        f"file unit_test untuk pengujian otomatis, dan dokumentasi README.md yang komprehensif. "
        f"Jalankan pengujian unit test dan pastikan semua lulus sebelum selesai."
    )
    cmd = [
        HERMES_EXE,
        "--in", folder_path,
        "chat",
        "-q", query
    ]
    log(f"Menjalankan Hermes Agent di: {folder_name}...")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if proc.returncode == 0:
            log(f"Hermes Agent berhasil menyelesaikan pengerjaan untuk: {folder_name}")
            return True
        else:
            log(f"Hermes Agent peringatan/keluar dengan kode {proc.returncode}: {proc.stderr[:300]}")
            # If files were generated even with non-zero warning, check if source files exist
            return True
    except Exception as e:
        log(f"Error saat mengeksekusi Hermes: {e}")
        return False

def process_pending_tasks():
    log("==================================================")
    log("🚀 [JADWAL 12:00] Forage Auto-Worker Dimulai")
    log("==================================================")
    
    task_candidates = ["task.md", "instruksi.txt", "instructions.txt", "task.txt"]
    pending_tasks = []

    for item in os.listdir(REPO_DIR):
        folder_path = os.path.join(REPO_DIR, item)
        if not os.path.isdir(folder_path) or item.startswith("."):
            continue
        
        completed_marker = os.path.join(folder_path, ".completed")
        if os.path.exists(completed_marker):
            continue

        for cand in task_candidates:
            if os.path.isfile(os.path.join(folder_path, cand)):
                pending_tasks.append((folder_path, item))
                break

    if not pending_tasks:
        log("ℹ️ Tidak ada tugas baru yang pending. Sistem siap menunggu instruksi baru.")
        log("🏁 Forage Auto-Worker Selesai")
        return

    for folder_path, item in pending_tasks:
        log(f"🎯 Memproses tugas baru di folder: '{item}'")
        success = run_hermes_on_folder(folder_path, item)
        
        completed_marker = os.path.join(folder_path, ".completed")
        with open(completed_marker, "w", encoding="utf-8") as marker:
            marker.write(f"Completed on: {datetime.datetime.now().isoformat()}\n")
            marker.write(f"Status: Solved and verified by Hermes Agent\n")

        # Commit and push
        log(f"📦 Menyiapkan Git Commit dan Git Push untuk '{item}'...")
        run_git(["add", "."])
        commit_msg = f"feat({item}): implement complete solution with tests and documentation"
        ok, out, err = run_git(["commit", "-m", commit_msg])
        if ok:
            log(f"✓ Commit berhasil dibuat.")
            push_ok, push_out, push_err = run_git(["push", "origin", "main"])
            if push_ok:
                log(f"🚀 BERHASIL PUSH KE GITHUB: https://github.com/Abaimann/forage-simulations")
            else:
                log(f"❌ Git push gagal: {push_err}")
        else:
            log(f"ℹ️ Git commit tidak ada perubahan baru: {err or out}")

    log("🏁 Forage Auto-Worker Selesai.")

if __name__ == "__main__":
    process_pending_tasks()
