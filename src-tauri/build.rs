use std::{env, fs, path::PathBuf};

fn main() {
    println!("cargo:rustc-check-cfg=cfg(branchline_git_worker)");
    println!("cargo:rerun-if-env-changed=BRANCHLINE_GIT_WORKER_PATH");
    if let Some(path) = env::var_os("BRANCHLINE_GIT_WORKER_PATH") {
        let path =
            fs::canonicalize(PathBuf::from(path)).expect("Cannot read embedded Git worker path");
        let bytes = fs::read(&path).expect("Cannot read embedded Git worker");
        let target = env::var("CARGO_CFG_TARGET_OS").unwrap_or_default();
        let valid = match target.as_str() {
            "windows" => bytes.starts_with(b"\x7fELF"),
            "linux" => bytes.starts_with(b"MZ"),
            _ => false,
        };
        assert!(
            valid,
            "BRANCHLINE_GIT_WORKER_PATH must name a worker for the opposite operating system"
        );
        println!("cargo:rerun-if-changed={}", path.display());
        println!(
            "cargo:rustc-env=BRANCHLINE_GIT_WORKER_PATH={}",
            path.display()
        );
        println!("cargo:rustc-cfg=branchline_git_worker");
    }
    tauri_build::build();
}
