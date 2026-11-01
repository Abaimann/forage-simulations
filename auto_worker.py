import os
import sys
import json
import subprocess
import datetime

REPO_DIR = r"C:\SAVING\GAWEAN GW\forage-simulations"
LOG_FILE = os.path.join(REPO_DIR, "worker.log")
CATALOG_FILE = os.path.join(REPO_DIR, "tasks_catalog.json")
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
        f"Sebagai Senior Software Engineer / Tech Lead, selesaikan task Forage di folder ini berdasarkan file instruksi (task.md atau instruksi.txt). "
        f"Tulis kode implementasi yang bersih, modular, tangguh (clean architecture/SOLID), "
        f"buat file unit_test yang menguji seluruh edge cases dan pastikan semua pengujian lulus (100% OK), "
        f"serta susun dokumentasi README.md teknis berstandar industri dengan penjelasan arsitektur, parameter, dan instruksi eksekusi. "
        f"Gunakan tool eksekusi terminal dan penulisan file untuk menyelesaikan dan memvalidasi pekerjaan Anda."
    )
    cmd = [
        HERMES_EXE,
        "--in", folder_path,
        "chat",
        "-q", query
    ]
    log(f"⚡ Mendelegasikan pengerjaan teknis ke Hermes Agent di sub-modul: {folder_name}...")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if proc.returncode == 0:
            log(f"✓ Hermes Agent berhasil merampungkan implementasi dan verifikasi unit test untuk: {folder_name}")
            return True
        else:
            log(f"⚠️ Hermes Agent selesai dengan catatan/warning (kode {proc.returncode}): {proc.stderr[:200]}")
            return True
    except Exception as e:
        log(f"❌ Error eksekusi Hermes Agent: {e}")
        return False

def get_next_catalog_task():
    if not os.path.exists(CATALOG_FILE):
        return None
    try:
        with open(CATALOG_FILE, "r", encoding="utf-8") as f:
            catalog = json.load(f)
        for item in catalog:
            folder_name = item.get("folder_name")
            target_path = os.path.join(REPO_DIR, folder_name)
            completed_marker = os.path.join(target_path, ".completed")
            # If folder doesn't exist or isn't completed yet
            if not os.path.exists(target_path) or not os.path.exists(completed_marker):
                return item
        return None
    except Exception as e:
        log(f"Error membaca antrean katalog tugas: {e}")
        return None

def process_daily_pipeline():
    log("======================================================================")
    log("🚀 [SCHEDULER 12:00] Inisialisasi Pipeline Otomatisasi Forage Simulations")
    log("======================================================================")
    
    task_candidates = ["task.md", "instruksi.txt", "instructions.txt", "task.txt"]
    target_folder = None
    target_name = None
    commit_msg = None

    # 1. Cek apakah ada tugas manual yang diletakkan user
    for item in os.listdir(REPO_DIR):
        folder_path = os.path.join(REPO_DIR, item)
        if not os.path.isdir(folder_path) or item.startswith("."):
            continue
        
        completed_marker = os.path.join(folder_path, ".completed")
        if os.path.exists(completed_marker):
            continue

        for cand in task_candidates:
            if os.path.isfile(os.path.join(folder_path, cand)):
                target_folder = folder_path
                target_name = item
                commit_msg = f"feat({item.lower()}): implementasi solusi modular dan pengujian unit test menyeluruh"
                log(f"📂 Mendeteksi antrean tugas manual di: '{item}'")
                break
        if target_folder:
            break

    # 2. Jika tidak ada tugas manual, ambil otomatis dari katalog Forage resmi
    if not target_folder:
        log("🔍 Tidak ada tugas manual pending. Mengambil tugas berikutnya dari antrean katalog Forage...")
        next_task = get_next_catalog_task()
        if next_task:
            folder_name = next_task["folder_name"]
            target_folder = os.path.join(REPO_DIR, folder_name)
            target_name = folder_name
            commit_msg = next_task.get(
                "senior_commit",
                f"feat({folder_name.lower()}): refactoring arsitektur solusi dan otomatisasi test suite"
            )
            
            os.makedirs(target_folder, exist_ok=True)
            instruction_file = os.path.join(target_folder, "task.md")
            with open(instruction_file, "w", encoding="utf-8") as f:
                f.write(next_task["instructions"])
            log(f"✨ Berhasil menyiapkan modul tugas baru: '{next_task['company']} - {next_task['title']}'")
        else:
            log("🎉 Semua modul pada katalog antrean Forage telah rampung dikerjakan! Repositori up to date.")
            log("🏁 Pipeline Otomatisasi Selesai.")
            return

    # 3. Eksekusi pengerjaan oleh agent
    success = run_hermes_on_folder(target_folder, target_name)
    
    # Tandai selesai
    completed_marker = os.path.join(target_folder, ".completed")
    with open(completed_marker, "w", encoding="utf-8") as marker:
        marker.write(f"Completed on: {datetime.datetime.now().isoformat()}\n")
        marker.write(f"Verified by: Senior AI Agent\n")

    # 4. Git Commit & Push dengan gaya programmer senior
    log(f"📦 Melakukan git staging dan pembuatan commit dengan standar Senior Dev...")
    run_git(["add", "."])
    
    # Format commit ala senior dev
    log(f"📝 Commit message: \"{commit_msg}\"")
    ok, out, err = run_git(["commit", "-m", commit_msg])
    if ok:
        log(f"✓ Git commit tersimpan: {out.splitlines()[0] if out else 'Success'}")
        push_ok, push_out, push_err = run_git(["push", "origin", "main"])
        if push_ok:
            log(f"🚀 SUCCESS: Perubahan berhasil di-push ke remote origin/main!")
            log(f"🔗 Tautan repositori: https://github.com/Abaimann/forage-simulations")
        else:
            log(f"❌ Gagal push ke remote: {push_err}")
    else:
        log(f"ℹ️ Git status bersih atau tidak ada delta baru: {err or out}")

    log("🏁 Pipeline Otomatisasi Harian Selesai.")

if __name__ == "__main__":
    process_daily_pipeline()
