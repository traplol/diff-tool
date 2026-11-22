#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    let mut args = std::env::args_os().skip(1);
    match args.next().as_deref().and_then(|arg| arg.to_str()) {
        Some("--help" | "-h") => {
            println!("Usage: branchline [DIRECTORY]\nOpen the selected Git checkout in a desktop review window.");
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
