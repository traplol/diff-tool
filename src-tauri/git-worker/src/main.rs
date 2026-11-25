//! Storage-local Git operations over the owning desktop process's pipes.
#![allow(dead_code)]

#[path = "../../src/git.rs"]
mod git;

fn main() {
    if std::env::args().skip(1).any(|arg| arg != "--stdio") {
        eprintln!("Usage: branchline-git-worker [--stdio]");
        std::process::exit(2);
    }
    #[cfg(windows)]
    let _git_configuration = git::configure_native();
    if let Err(error) = git::worker::run_stdio() {
        eprintln!("Git worker: {error}");
        std::process::exit(1);
    }
}
