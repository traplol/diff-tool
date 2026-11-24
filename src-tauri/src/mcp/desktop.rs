//! Ensure desktop windows share a local MCP listener.
use super::{configured_port, IDENTITY_HEADER};
use crate::{config, git};
use serde_json::Value;
use std::{
    io::{self, Read, Write},
    net::{Ipv4Addr, SocketAddr, TcpListener, TcpStream},
    path::PathBuf,
    process::{Command, Stdio},
    thread,
    time::{Duration, Instant},
};

enum Listener {
    Free,
    Branchline(Option<bool>),
}

fn probe(addr: SocketAddr, root: &str, before_launch: bool) -> Result<Listener, String> {
    let timeout = Duration::from_millis(350);
    let mut stream = match TcpStream::connect_timeout(&addr, timeout) {
        Ok(stream) => stream,
        Err(error) if error.kind() == io::ErrorKind::ConnectionRefused => {
            return Ok(Listener::Free)
        }
        // Winsock can time out connecting to a free loopback port. Confirm
        // availability before launching, and let the child bind during startup.
        Err(error)
            if error.kind() == io::ErrorKind::TimedOut
                && (!before_launch || TcpListener::bind(addr).is_ok()) =>
        {
            return Ok(Listener::Free)
        }
        Err(error) => return Err(format!("Could not check MCP at {addr}: {error}")),
    };
    let request =
        r#"{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"list_repositories"}}"#;
    let exchange = || -> io::Result<Vec<u8>> {
        stream.set_read_timeout(Some(timeout))?;
        stream.set_write_timeout(Some(timeout))?;
        write!(
            stream,
            "POST /mcp HTTP/1.1\r\nHost: {addr}\r\nConnection: close\r\nContent-Type: application/json\r\nAccept: application/json, text/event-stream\r\nContent-Length: {}\r\n\r\n{request}",
            request.len()
        )?;
        let mut response = Vec::new();
        stream.take(256 * 1024).read_to_end(&mut response)?;
        Ok(response)
    };
    let occupied = || {
        format!(
            "Port {} is in use. Choose another Branchline MCP port.",
            addr.port()
        )
    };
    let response = exchange().map_err(|_| occupied())?;
    let response = std::str::from_utf8(&response).map_err(|_| occupied())?;
    let (headers, body) = response.split_once("\r\n\r\n").ok_or_else(occupied)?;
    if headers.starts_with("HTTP/1.1 401 ")
        && headers.lines().any(|line| {
            line.split_once(':').is_some_and(|(name, value)| {
                name.eq_ignore_ascii_case(IDENTITY_HEADER) && value.trim() == "1"
            })
        })
    {
        return Ok(Listener::Branchline(None));
    }
    if !headers.starts_with("HTTP/1.1 200 ") {
        return Err(occupied());
    }
    let message: Value = serde_json::from_str(body).map_err(|_| occupied())?;
    let repositories = message["result"]["structuredContent"]["repositories"]
        .as_array()
        .ok_or_else(occupied)?;
    Ok(Listener::Branchline(Some(
        repositories.iter().any(|repo| repo["path"] == root),
    )))
}

pub fn ensure_running(root: &str) -> Result<(), String> {
    let settings = config::read(&config::path()?)?.unwrap_or_default();
    if !settings.mcp_auto_start {
        return Ok(());
    }
    let port = configured_port(&settings)?;
    let addr = SocketAddr::from((Ipv4Addr::LOCALHOST, port));
    let served = |covered| {
        if covered == Some(false) {
            Err(format!(
                "Branchline MCP on port {port} serves other checkouts. Add this checkout to mcp_repositories and restart the server."
            ))
        } else {
            Ok(())
        }
    };
    if let Listener::Branchline(covered) = probe(addr, root, true)? {
        return served(covered);
    }

    let executable = std::env::current_exe().map_err(|e| e.to_string())?;
    let mut command = Command::new(executable);
    command
        .args(["--mcp", "--port", &port.to_string()])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    if settings.mcp_repositories.is_empty() {
        command.arg("--").arg(PathBuf::from(git::path_arg(root)?));
    }
    #[cfg(unix)]
    std::os::unix::process::CommandExt::process_group(&mut command, 0);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        // CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
        command.creation_flags(0x0800_0000 | 0x0000_0200);
    }
    let mut child = command
        .spawn()
        .map_err(|e| format!("Could not start Branchline MCP: {e}"))?;
    let deadline = Instant::now() + Duration::from_secs(2);
    let result = loop {
        match probe(addr, root, false) {
            Ok(Listener::Branchline(covered)) => break served(covered),
            Ok(Listener::Free) if Instant::now() < deadline => {
                thread::sleep(Duration::from_millis(60));
            }
            Ok(Listener::Free) => {
                break Err(format!(
                    "Branchline MCP did not start on port {port} in time."
                ))
            }
            Err(error) => break Err(error),
        }
    };
    // Wait in the background so a stopped child is reaped without tying its
    // lifetime to this desktop window.
    thread::spawn(move || {
        let _ = child.wait();
    });
    result
}
