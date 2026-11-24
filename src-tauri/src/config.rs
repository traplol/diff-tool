use rusqlite::{Connection, TransactionBehavior};
use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeMap,
    env, fs,
    io::{self, Write},
    path::{Path, PathBuf},
};

pub const DEFAULT_MCP_PORT: u16 = 8765;

#[derive(Clone, Copy, Debug, Default, Deserialize, PartialEq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Layout {
    #[default]
    Unified,
    Split,
}

#[derive(Clone, Debug, Default, Deserialize, PartialEq, Serialize)]
#[serde(default)]
pub struct RepoSettings {
    pub base_branch: String,
    pub layers: Vec<String>,
    #[serde(flatten)]
    other: BTreeMap<String, serde_json::Value>,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(default)]
pub struct Settings {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub mcp_port: Option<u16>,
    pub mcp_auto_start: bool,
    #[serde(skip_serializing_if = "BTreeMap::is_empty")]
    pub mcp_repositories: BTreeMap<String, PathBuf>,
    pub hardware_acceleration: bool,
    pub diff_layout: Layout,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub sidebar_width: Option<i64>,
    pub repositories: BTreeMap<String, RepoSettings>,
    #[serde(flatten)]
    other: BTreeMap<String, serde_json::Value>,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            mcp_port: None,
            mcp_auto_start: true,
            mcp_repositories: BTreeMap::new(),
            hardware_acceleration: true,
            diff_layout: Layout::Unified,
            sidebar_width: None,
            repositories: BTreeMap::new(),
            other: BTreeMap::new(),
        }
    }
}

pub fn path() -> Result<PathBuf, String> {
    if let Some(dir) = env::var_os("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .filter(|p| p.is_absolute())
    {
        return Ok(dir.join("branchline/config.json"));
    }
    #[cfg(windows)]
    let path = env::var_os("APPDATA")
        .map(PathBuf::from)
        .or_else(|| env::var_os("USERPROFILE").map(|p| PathBuf::from(p).join("AppData/Roaming")))
        .map(|p| p.join("Branchline/config.json"));
    #[cfg(not(windows))]
    let path = env::var_os("HOME").map(|p| PathBuf::from(p).join(".config/branchline/config.json"));
    path.ok_or_else(|| "Could not locate the Branchline configuration directory.".into())
}

pub fn read(path: &Path) -> Result<Option<Settings>, String> {
    match fs::read(path) {
        Ok(bytes) => serde_json::from_slice(&bytes)
            .map(Some)
            .map_err(|e| format!("Invalid settings in {}: {e}", path.display())),
        Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(None),
        Err(e) => Err(format!("Could not read {}: {e}", path.display())),
    }
}

pub fn hardware_acceleration() -> Result<bool, String> {
    Ok(read(&path()?)?.unwrap_or_default().hardware_acceleration)
}

pub fn update(path: &Path, change: impl FnOnce(&mut Settings)) -> Result<Settings, String> {
    let dir = path.parent().ok_or("Missing configuration directory.")?;
    let write_error = |e: io::Error| format!("Could not save {}: {e}", path.display());
    fs::create_dir_all(dir).map_err(write_error)?;
    // Serialize the entire read/modify/replace across running app instances.
    // SQLite's file lock is released by the OS if an instance exits mid-write.
    let lock_error = |e: rusqlite::Error| format!("Could not lock {}: {e}", path.display());
    let mut lock = Connection::open(dir.join("config.lock")).map_err(lock_error)?;
    let _guard = lock
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(lock_error)?;
    let old = read(path)?;
    let mut settings = old.clone().unwrap_or_default();
    change(&mut settings);
    if old.as_ref() != Some(&settings) {
        let mut file = tempfile::NamedTempFile::new_in(dir).map_err(write_error)?;
        serde_json::to_writer_pretty(&mut file, &settings)
            .map_err(|e| format!("Could not write {}: {e}", path.display()))?;
        writeln!(file).map_err(write_error)?;
        file.as_file().sync_all().map_err(write_error)?;
        file.persist(path).map_err(|e| write_error(e.error))?;
    }
    Ok(settings)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Arc, Barrier};

    #[test]
    fn concurrent_edits_keep_other_checkouts_and_hand_edited_preferences() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("config.json");
        fs::write(
            &path,
            r#"{"hardware_acceleration":false,"custom":"preserve"}"#,
        )
        .unwrap();
        let ready = Arc::new(Barrier::new(4));
        std::thread::scope(|scope| {
            for i in 0..4 {
                let ready = ready.clone();
                let path = &path;
                scope.spawn(move || {
                    ready.wait();
                    update(path, |s| {
                        s.repositories
                            .entry(format!("checkout-{i}"))
                            .or_default()
                            .base_branch = format!("topic-{i}");
                    })
                    .unwrap();
                });
            }
        });
        let settings = read(&path).unwrap().unwrap();
        assert!(!settings.hardware_acceleration);
        assert_eq!(settings.other["custom"], "preserve");
        for i in 0..4 {
            assert_eq!(
                settings.repositories[&format!("checkout-{i}")].base_branch,
                format!("topic-{i}")
            );
        }
    }
}
