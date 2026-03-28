use std::process::Command;
use std::thread;
use std::time::Duration;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // Spawn the Python FastAPI backend before the window opens.
    // This runs start.sh (the Guardian loop) in the background.
    thread::spawn(|| {
        let project_dir = std::env::current_exe()
            .ok()
            .and_then(|p| p.parent().map(|d| d.to_path_buf()))
            .unwrap_or_default();

        // Try to find the project root (where start.sh lives)
        // In dev mode, it's ../../.. from the binary location
        // In production, we'll bundle start.sh alongside
        let candidates = vec![
            std::env::current_dir().unwrap_or_default(),
            project_dir.join("..").join("..").join(".."),
            project_dir.clone(),
        ];

        for dir in candidates {
            let start_script = dir.join("start.sh");
            if start_script.exists() {
                log::info!("[SOVEREIGN] Found start.sh at: {:?}", start_script);
                let _ = Command::new("bash")
                    .arg(start_script)
                    .current_dir(&dir)
                    .spawn();
                return;
            }
        }

        // Fallback: try launching uvicorn directly
        log::warn!("[SOVEREIGN] start.sh not found, attempting direct uvicorn launch");
        let _ = Command::new("python3")
            .args(["-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002", "--reload"])
            .spawn();
    });

    // Give the backend a moment to bind the port
    thread::sleep(Duration::from_millis(1500));

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
