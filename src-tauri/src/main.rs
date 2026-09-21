#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
use std::{
    io::{BufRead, BufReader},
    process::{Child, Command, Stdio},
    sync::Mutex,
    time::Duration,
};
use tauri::Manager;
use tauri_plugin_dialog::DialogExt;

#[derive(Clone, serde::Serialize, serde::Deserialize)]
struct Connection {
    port: u16,
    token: String,
}
struct Backend {
    connection: Connection,
    child: Mutex<Child>,
}

#[tauri::command]
fn backend_connection(state: tauri::State<Backend>) -> Connection {
    state.connection.clone()
}

#[tauri::command]
async fn select_pdfs(app: tauri::AppHandle) -> Result<Vec<String>, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let paths = app
            .dialog()
            .file()
            .add_filter("PDF", &["pdf"])
            .blocking_pick_files();
        paths
            .unwrap_or_default()
            .into_iter()
            .map(|p| {
                p.into_path()
                    .map(|p| p.to_string_lossy().to_string())
                    .map_err(|_| "无效 PDF 路径".to_string())
            })
            .collect()
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn select_folder(app: tauri::AppHandle) -> Result<Option<String>, String> {
    tauri::async_runtime::spawn_blocking(move || {
        app.dialog()
            .file()
            .blocking_pick_folder()
            .and_then(|p| p.into_path().ok())
            .map(|p| p.to_string_lossy().to_string())
    })
    .await
    .map_err(|e| e.to_string())
}

#[tauri::command]
async fn save_export(app: tauri::AppHandle, name: String, bytes: Vec<u8>) -> Result<bool, String> {
    if bytes.len() > 20 * 1024 * 1024 {
        return Err("导出文件过大".into());
    }
    let name = if name.ends_with(".pdf") {
        "ScholarMate-export.pdf"
    } else {
        "ScholarMate-export.md"
    };
    tauri::async_runtime::spawn_blocking(move || {
        let selected = app.dialog().file().set_file_name(name).blocking_save_file();
        if let Some(path) = selected {
            let path = path.into_path().map_err(|_| "无效文件路径".to_string())?;
            std::fs::write(path, bytes).map_err(|_| "文件保存失败，请检查目录权限".to_string())?;
            Ok(true)
        } else {
            Ok(false)
        }
    })
    .await
    .map_err(|e| e.to_string())?
}

fn launch(app: &tauri::App) -> Result<Backend, Box<dyn std::error::Error>> {
    let mut command;
    if cfg!(debug_assertions) {
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap();
        let python = if cfg!(windows) {
            root.join(".venv/Scripts/python.exe")
        } else {
            root.join(".venv/bin/python")
        };
        let python = std::env::var_os("SCHOLARMATE_PYTHON")
            .map(std::path::PathBuf::from)
            .unwrap_or(python);
        command = Command::new(python);
        command.arg(root.join("src-tauri/python/main.py"));
    } else {
        let executable = std::env::current_exe()?
            .parent()
            .unwrap()
            .join(if cfg!(windows) {
                "scholarmate-backend.exe"
            } else {
                "scholarmate-backend"
            });
        command = Command::new(executable);
    }
    let config_dir = app.path().app_config_dir()?;
    let data_dir = std::env::var_os("SCHOLARMATE_DATA_DIR")
        .map(std::path::PathBuf::from)
        .or_else(|| {
            // The user may have moved the data directory; storage.json in the OS
            // configuration folder records where it lives now.
            let text = std::fs::read_to_string(config_dir.join("storage.json")).ok()?;
            let value: serde_json::Value = serde_json::from_str(&text).ok()?;
            let saved = value.get("data_dir")?.as_str()?.trim().to_string();
            (!saved.is_empty()).then(|| std::path::PathBuf::from(saved))
        })
        .map(Ok)
        .unwrap_or_else(|| app.path().app_data_dir())?;
    command
        .env("SCHOLARMATE_DATA_DIR", data_dir)
        .env("SCHOLARMATE_CONFIG_DIR", config_dir)
        .env("SCHOLARMATE_PARENT", "1")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    let mut child = command.spawn()?;
    let stdout = child.stdout.take().ok_or("Python 启动输出不可用")?;
    let (tx, rx) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        let mut reader = BufReader::new(stdout);
        let mut line = String::new();
        let result = reader.read_line(&mut line).map(|_| line);
        let _ = tx.send(result);
        // Drain stdout without displaying the session token or holding a pipe open forever.
        for _ in reader.lines() {}
    });
    let result = rx.recv_timeout(Duration::from_secs(60));
    let connection = match result {
        Ok(Ok(line)) => serde_json::from_str::<Connection>(&line).ok(),
        _ => None,
    };
    if let Some(connection) = connection {
        Ok(Backend {
            connection,
            child: Mutex::new(child),
        })
    } else {
        let _ = child.kill();
        let _ = child.wait();
        Err("Python 服务启动失败，请检查 Python 环境和依赖".into())
    }
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let backend = launch(app)?;
            app.manage(backend);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            backend_connection,
            save_export,
            select_pdfs,
            select_folder
        ])
        .build(tauri::generate_context!())
        .expect("ScholarMate 启动失败");
    app.run(|handle, event| {
        if let tauri::RunEvent::Exit = event {
            if let Some(state) = handle.try_state::<Backend>() {
                if let Ok(mut child) = state.child.lock() {
                    let _ = child.kill();
                    let _ = child.wait();
                }
            }
        }
    });
}

