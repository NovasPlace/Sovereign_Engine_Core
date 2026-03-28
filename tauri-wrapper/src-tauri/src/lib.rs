use tauri::{RunEvent, Manager};
use std::process::{Command, Child};
use std::sync::Mutex;

struct AppState {
    api_child: Mutex<Option<Child>>,
    daemon_child: Mutex<Option<Child>>,
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // Dynamically resolve the Python binary path based on Cargo's execution CWD
    let python_path = if std::path::Path::new("../venv/bin/python").exists() {
        "../venv/bin/python"
    } else if std::path::Path::new("../../venv/bin/python").exists() {
        "../../venv/bin/python"
    } else {
        "python3" // Fallback to system python if venv is catastrophically lost
    };

    let main_path = if std::path::Path::new("../main.py").exists() {
        "../main.py"
    } else if std::path::Path::new("../../main.py").exists() {
        "../../main.py"
    } else {
        "main.py"
    };

    let daemon_path = if std::path::Path::new("../daemon.py").exists() {
        "../daemon.py"
    } else if std::path::Path::new("../../daemon.py").exists() {
        "../../daemon.py"
    } else {
        "daemon.py"
    };

    println!("[*] Rust Supervisor starting Sovereign API backend at {}...", python_path);
    let api_proc = Command::new(python_path)
        .arg(main_path)
        .spawn()
        .expect("FATAL: Failed to spawn the Sovereign API backend. Ensure venv is built.");

    println!("[*] Rust Supervisor starting Sovereign Daemon fabric at {}...", python_path);
    let daemon_proc = Command::new(python_path)
        .arg(daemon_path)
        .spawn()
        .expect("FATAL: Failed to spawn the Sovereign Daemon fabric. Ensure venv is built.");

    // Implements a strict 1500ms Wait Lock to ensure Uvicorn binds to port 8002 
    // before the Webview natively queries it.
    std::thread::sleep(std::time::Duration::from_millis(1500));

    let state = AppState {
        api_child: Mutex::new(Some(api_proc)),
        daemon_child: Mutex::new(Some(daemon_proc)),
    };

    let app = tauri::Builder::default()
        .manage(state)
        .plugin(tauri_plugin_opener::init())
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app_handle, event| match event {
        RunEvent::Exit => {
            let state = app_handle.state::<AppState>();
            if let Ok(mut child_guard) = state.inner().api_child.lock() {
                if let Some(mut child) = child_guard.take() {
                    println!("[*] Rust Supervisor killing Sovereign API backend...");
                    let _ = child.kill();
                    let _ = child.wait();
                }
            };
            if let Ok(mut daemon_guard) = state.inner().daemon_child.lock() {
                if let Some(mut child) = daemon_guard.take() {
                    println!("[*] Rust Supervisor killing Sovereign Daemon fabric...");
                    let _ = child.kill();
                    let _ = child.wait();
                }
            };
        }
        _ => {}
    });
}
