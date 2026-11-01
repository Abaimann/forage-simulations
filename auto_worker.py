import os
import sys
import json
import subprocess
import datetime
import urllib.request
import urllib.error

REPO_DIR = r"C:\SAVING\GAWEAN GW\forage-simulations"
LOG_FILE = os.path.join(REPO_DIR, "worker.log")
API_KEY = "sk-cp-tmNbwuiqPEz96BtxLxmHFxnHStfeTgh8opQAxBit9vLlN_OQHbPHN4v0vGvHmLki2-iElSx2GtiAzKZa6Ur_KzDfwne_DW4NT98b3IEHjweX4ivZy4z1-Ao"
API_URL = "https://api.minimax.io/v1/chat/completions"
MODEL = "MiniMax-M3.1-Flash"

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

def call_ai(prompt, instructions):
    system_msg = (
        "You are a Senior Software Engineer & Technical Consultant helping complete a "
        "Forage Virtual Internship simulation task.\n"
        "Analyze the provided task instructions and generate the full, production-ready solution.\n"
        "Return your output STRICTLY as valid JSON matching this schema:\n"
        "{\n"
        '  "files": [\n'
        '    {"filename": "string", "content": "string"}\n'
        "  ],\n"
        '  "summary": "Short 1-2 sentence description of completed work"\n'
        "}\n"
        "Ensure one of the files is 'README.md' containing comprehensive project documentation, "
        "approach explanation, and step-by-step instructions on how to test the code. "
        "Do NOT wrap with markdown backticks if possible, return raw json."
    )

    user_msg = f"Task Instructions:\n{instructions}\n\nPlease generate the solution files."

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ],
        "temperature": 0.2
    }

    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=req_data,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            
            # Clean possible markdown block
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            elif content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            
            return json.loads(content)
    except Exception as e:
        log(f"AI API call failed: {e}")
        return None

def process_pending_tasks():
    log("=== Forage Auto-Worker started ===")
    
    task_file_candidates = ["task.md", "instruksi.txt", "instructions.txt", "task.txt"]
    pending_found = False

    for item in os.listdir(REPO_DIR):
        folder_path = os.path.join(REPO_DIR, item)
        if not os.path.isdir(folder_path) or item.startswith("."):
            continue
        
        completed_marker = os.path.join(folder_path, ".completed")
        if os.path.exists(completed_marker):
            continue

        # Look for instruction file
        instruction_file = None
        for cand in task_file_candidates:
            cand_path = os.path.join(folder_path, cand)
            if os.path.isfile(cand_path):
                instruction_file = cand_path
                break

        if not instruction_file:
            continue

        pending_found = True
        log(f"Found pending task in: {item}")
        
        try:
            with open(instruction_file, "r", encoding="utf-8") as f:
                instructions = f.read()
        except Exception as e:
            log(f"Failed to read instructions for {item}: {e}")
            continue

        log(f"Generating solution for '{item}' via {MODEL}...")
        result = call_ai(item, instructions)
        if not result or "files" not in result:
            log(f"Failed to generate valid solution files for {item}.")
            continue

        # Write generated files
        for f in result["files"]:
            fname = f.get("filename")
            fcontent = f.get("content")
            if fname and fcontent:
                out_path = os.path.join(folder_path, fname)
                try:
                    with open(out_path, "w", encoding="utf-8") as out_f:
                        out_f.write(fcontent)
                    log(f"  + Generated: {fname}")
                except Exception as e:
                    log(f"  ! Failed writing {fname}: {e}")

        # Mark completed
        with open(completed_marker, "w", encoding="utf-8") as marker:
            marker.write(f"Completed on: {datetime.datetime.now().isoformat()}\n")
            marker.write(f"Summary: {result.get('summary', 'Done')}\n")

        # Git commit and push
        log(f"Committing and pushing solution for '{item}' to GitHub...")
        run_git(["add", "."])
        commit_msg = f"feat({item}): complete simulation task - {result.get('summary', 'solution generated')}"
        ok, out, err = run_git(["commit", "-m", commit_msg])
        if ok:
            log(f"Git commit created: {out.splitlines()[0] if out else 'Success'}")
            push_ok, push_out, push_err = run_git(["push", "origin", "main"])
            if push_ok:
                log(f"Git push to origin/main SUCCEEDED! 🚀")
            else:
                log(f"Git push failed: {push_err}")
        else:
            log(f"Git commit skipped or failed: {err or out}")

    if not pending_found:
        log("No pending tasks found. System idle. Ready for new tasks.")
    
    log("=== Forage Auto-Worker finished ===")

if __name__ == "__main__":
    process_pending_tasks()
