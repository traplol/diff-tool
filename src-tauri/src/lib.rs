mod config;
mod git;
mod mcp;
mod review;
mod search;
mod service;
mod suggestions;
mod tracking;

use std::{path::PathBuf, sync::Mutex};
use tauri::{AppHandle, Manager};
use tauri_plugin_dialog::DialogExt;

pub use mcp::run as run_mcp;

#[cfg(windows)]
pub fn configure_git_backend() -> Option<tempfile::TempDir> {
    git::configure_native()
}

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
        let opening = matches!(&request, service::Request::Open { .. });
        let state = app.state::<Mutex<service::Workspace>>();
        let mut result = state
            .lock()
            .map_err(|_| "Reopen Branchline to reload the review.")?
            .execute(request, snapshot)?;
        if opening {
            if let Some(root) = result["repo"]["root"].as_str() {
                if let Err(error) = mcp::desktop::ensure_running(root) {
                    result["mcp_warning"] = serde_json::json!(error);
                }
            }
        }
        Ok(result)
    })
    .await
    .map_err(|e| e.to_string())?
}

pub fn run() {
    #[cfg(any(target_os = "linux", windows))]
    let acceleration = config::hardware_acceleration().unwrap_or_else(|error| {
        eprintln!("Could not read hardware acceleration preference: {error}");
        true
    });

    // WebView2 enables the GPU by default. Append the opt-out before it starts.
    #[cfg(windows)]
    if !acceleration {
        let key = "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS";
        let mut args = std::env::var_os(key).unwrap_or_default();
        args.push(" --disable-gpu");
        std::env::set_var(key, args);
    }

    let builder = tauri::Builder::default();
    #[cfg(target_os = "linux")]
    let builder = builder.setup(move |app| {
        use webkit2gtk::{HardwareAccelerationPolicy, SettingsExt, WebViewExt};
        if let Some(window) = app.get_webview_window("main") {
            window.with_webview(move |webview| {
                if let Some(settings) = webview.inner().settings() {
                    let policy = if acceleration {
                        HardwareAccelerationPolicy::Always
                    } else {
                        HardwareAccelerationPolicy::Never
                    };
                    settings.set_hardware_acceleration_policy(policy);
                }
            })?;
        }
        Ok(())
    });
    builder
        .plugin(tauri_plugin_dialog::init())
        .manage(Mutex::new(service::Workspace::default()))
        .invoke_handler(tauri::generate_handler![
            startup_path,
            choose_repository,
            save_markdown,
            search::search_review,
            workspace
        ])
        .run(tauri::generate_context!())
        .expect("Could not start Branchline");
}
