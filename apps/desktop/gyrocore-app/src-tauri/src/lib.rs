use serde_json::{json, Value};
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Command, Stdio};

fn repo_root() -> PathBuf {
    // src-tauri → gyrocore-app → desktop → apps → repo
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../..")
        .canonicalize()
        .unwrap_or_else(|_| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../.."))
}

fn python_bin() -> String {
    std::env::var("GYROCORE_PYTHON").unwrap_or_else(|_| "python3".into())
}

#[tauri::command]
fn worker_request(request: Value) -> Result<Value, String> {
    let root = repo_root();
    let worker = root.join("apps/desktop/worker/gyrocore_worker.py");
    if !worker.is_file() {
        return Err(format!("worker_missing:{}", worker.display()));
    }
    let core = root.join("core");
    let pythonpath = format!(
        "{}{}{}",
        root.display(),
        if cfg!(windows) { ";" } else { ":" },
        core.display()
    );

    let mut child = Command::new(python_bin())
        .arg(&worker)
        .current_dir(&root)
        .env("PYTHONPATH", pythonpath)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("worker_spawn_failed:{e}"))?;

    {
        let stdin = child.stdin.as_mut().ok_or("worker_stdin_unavailable")?;
        let line = serde_json::to_string(&request).map_err(|e| e.to_string())?;
        writeln!(stdin, "{line}").map_err(|e| format!("worker_stdin_write:{e}"))?;
    }

    let stdout = child.stdout.take().ok_or("worker_stdout_unavailable")?;
    let mut reader = BufReader::new(stdout);
    let mut line = String::new();
    reader
        .read_line(&mut line)
        .map_err(|e| format!("worker_stdout_read:{e}"))?;

    let _ = child.wait();
    if line.trim().is_empty() {
        return Err("worker_empty_response".into());
    }
    serde_json::from_str(line.trim()).map_err(|e| format!("worker_bad_json:{e}"))
}

#[tauri::command]
fn desktop_capabilities() -> Value {
    json!({
        "fc_apply": false,
        "msp": false,
        "serial": false,
        "bridge": "json_lines_stdin_stdout",
        "authorize_path": "run_safety_pipeline -> FinalSafeTuneResult -> authorize_cli"
    })
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![worker_request, desktop_capabilities])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
