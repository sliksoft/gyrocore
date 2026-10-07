use serde_json::{json, Value};
use std::ffi::OsStr;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

/// Dev/test override for the GyroCore checkout used by the worker bridge.
const REPO_ROOT_ENV: &str = "GYROCORE_REPO_ROOT";
const WORKER_REL: &str = "apps/desktop/worker/gyrocore_worker.py";

/// src-tauri → gyrocore-app → desktop → apps → repo (four levels up).
fn default_repo_root(manifest_dir: &Path) -> PathBuf {
    let root = manifest_dir.join("../../../..");
    root.canonicalize().unwrap_or(root)
}

fn worker_path(root: &Path) -> PathBuf {
    root.join(WORKER_REL)
}

/// Resolve `(repo_root, worker)`; an explicit override never falls back to the default.
fn resolve_worker(
    override_root: Option<&OsStr>,
    manifest_dir: &Path,
) -> Result<(PathBuf, PathBuf), String> {
    let root = match override_root {
        Some(raw) => {
            let given = PathBuf::from(raw);
            let root = given.canonicalize().map_err(|e| {
                format!(
                    "repo_root_override_invalid:{REPO_ROOT_ENV}={} ({e})",
                    given.display()
                )
            })?;
            let worker = worker_path(&root);
            if !worker.is_file() {
                return Err(format!(
                    "repo_root_override_invalid:{REPO_ROOT_ENV}={} has no worker at {}",
                    root.display(),
                    worker.display()
                ));
            }
            root
        }
        None => default_repo_root(manifest_dir),
    };
    let worker = worker_path(&root);
    if !worker.is_file() {
        return Err(format!(
            "worker_missing: worker={} repo_root={} (set {REPO_ROOT_ENV} to the GyroCore checkout)",
            worker.display(),
            root.display()
        ));
    }
    Ok((root, worker))
}

fn python_bin() -> String {
    std::env::var("GYROCORE_PYTHON").unwrap_or_else(|_| "python3".into())
}

#[tauri::command]
fn worker_request(request: Value) -> Result<Value, String> {
    let override_root = std::env::var_os(REPO_ROOT_ENV);
    let (root, worker) = resolve_worker(
        override_root.as_deref(),
        Path::new(env!("CARGO_MANIFEST_DIR")),
    )?;
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::sync::atomic::{AtomicUsize, Ordering};

    static NEXT: AtomicUsize = AtomicUsize::new(0);

    /// Fresh `<tmp>/repo` with the Tauri crate dir; optionally with the worker script.
    fn fake_repo(with_worker: bool) -> (PathBuf, PathBuf) {
        let base = std::env::temp_dir().join(format!(
            "gyrocore-path-test-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::SeqCst)
        ));
        let _ = fs::remove_dir_all(&base);
        let repo = base.join("repo");
        let manifest = repo.join("apps/desktop/gyrocore-app/src-tauri");
        fs::create_dir_all(&manifest).unwrap();
        if with_worker {
            let worker = worker_path(&repo);
            fs::create_dir_all(worker.parent().unwrap()).unwrap();
            fs::write(&worker, "# worker\n").unwrap();
        }
        (repo.canonicalize().unwrap(), manifest)
    }

    #[test]
    fn source_tree_layout_resolves_repo_root_and_worker() {
        let (repo, manifest) = fake_repo(true);
        let (root, worker) = resolve_worker(None, &manifest).unwrap();
        assert_eq!(root, repo);
        assert_eq!(worker, repo.join("apps/desktop/worker/gyrocore_worker.py"));
    }

    #[test]
    fn actual_crate_layout_finds_the_checked_in_worker() {
        let (root, worker) = resolve_worker(None, Path::new(env!("CARGO_MANIFEST_DIR"))).unwrap();
        assert!(root.join("core").is_dir(), "{}", root.display());
        assert!(worker.is_file(), "{}", worker.display());
    }

    #[test]
    fn override_is_used_instead_of_manifest_layout() {
        let (_, manifest_without_worker) = fake_repo(false);
        let (other, _) = fake_repo(true);
        let (root, worker) =
            resolve_worker(Some(other.as_os_str()), &manifest_without_worker).unwrap();
        assert_eq!(root, other);
        assert_eq!(worker, worker_path(&other));
    }

    #[test]
    fn invalid_override_fails_without_falling_back() {
        let (_, manifest) = fake_repo(true);
        let (no_worker, _) = fake_repo(false);
        let missing = no_worker.join("does-not-exist");
        for bad in [missing.as_os_str(), no_worker.as_os_str(), OsStr::new("")] {
            let err = resolve_worker(Some(bad), &manifest).unwrap_err();
            assert!(err.starts_with("repo_root_override_invalid:"), "{err}");
            assert!(err.contains(REPO_ROOT_ENV), "{err}");
        }
    }

    #[test]
    fn missing_worker_reports_worker_and_repo_root() {
        let (repo, manifest) = fake_repo(false);
        let err = resolve_worker(None, &manifest).unwrap_err();
        assert!(err.starts_with("worker_missing:"), "{err}");
        assert!(
            err.contains(&worker_path(&repo).display().to_string()),
            "{err}"
        );
        assert!(
            err.contains(&format!("repo_root={}", repo.display())),
            "{err}"
        );
        assert!(!err.contains("apps/apps"), "{err}");
    }
}
