mod git;
mod review;
mod service;
mod suggestions;
mod tracking;

use std::{path::PathBuf, sync::Mutex};
use tauri::{AppHandle, Manager};
use tauri_plugin_dialog::DialogExt;

#[tauri::command]
fn startup_path() -> Result<String, String> {
    std::env::args_os()
        .nth(1)
        .map(PathBuf::from)
        .map(Ok)
        .unwrap_or_else(|| std::env::current_dir().map_err(|e| e.to_string()))
        .map(|p| git::path_name(&p))
}

#[tauri::command]
async fn choose_repository(app: AppHandle) -> Result<Option<String>, String> {
    tauri::async_runtime::spawn_blocking(move || {
        app.dialog()
            .file()
            .set_title("Open Git repository")
            .blocking_pick_folder()
            .map(|path| {
                path.into_path()
                    .map(|p| git::path_name(&p))
                    .map_err(|e| e.to_string())
            })
            .transpose()
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn save_markdown(app: AppHandle, content: String) -> Result<bool, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let Some(file) = app
            .dialog()
            .file()
            .set_file_name("branchline-review.md")
            .add_filter("Markdown", &["md"])
            .blocking_save_file()
        else {
            return Ok(false);
        };
        let path = file.into_path().map_err(|e| e.to_string())?;
        std::fs::write(path, content).map_err(|e| e.to_string())?;
        Ok(true)
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn workspace(
    app: AppHandle,
    request: service::Request,
    snapshot: Option<u64>,
) -> Result<serde_json::Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let state = app.state::<Mutex<service::Workspace>>();
        let mut state = state
            .lock()
            .map_err(|_| "Reopen Branchline to reload the review.")?;
        state.execute(request, snapshot)
    })
    .await
    .map_err(|e| e.to_string())?
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(Mutex::new(service::Workspace::default()))
        .invoke_handler(tauri::generate_handler![
            startup_path,
            choose_repository,
            save_markdown,
            workspace
        ])
        .run(tauri::generate_context!())
        .expect("Could not start Branchline");
}
