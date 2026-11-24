#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    #[cfg(windows)]
    let _git_config = branchline::configure_git_backend();
    let mut args = std::env::args_os().skip(1);
    match args.next().as_deref().and_then(|arg| arg.to_str()) {
        Some("--mcp") => {
            // The release desktop binary uses the Windows GUI subsystem.
            #[cfg(windows)]
            unsafe {
                use windows_sys::Win32::System::Console::{AttachConsole, ATTACH_PARENT_PROCESS};
                AttachConsole(ATTACH_PARENT_PROCESS);
            }
            if let Err(error) = branchline::run_mcp(args) {
                eprintln!("{error}");
                std::process::exit(1);
            }
            return;
        }
        Some("--help" | "-h") => {
            println!("Usage: branchline [DIRECTORY]\n       branchline --mcp [DIRECTORY ...] [--port PORT]\nOpen a desktop review or serve the selected checkouts over MCP.");
            return;
        }
        Some("--version" | "-V") => {
            println!("Branchline {}", env!("CARGO_PKG_VERSION"));
            return;
        }
        _ => {}
    }
    if args.next().is_some() {
        eprintln!("Usage: branchline [DIRECTORY]");
        std::process::exit(2);
    }
    branchline::run()
}
