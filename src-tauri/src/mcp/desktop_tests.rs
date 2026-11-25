use super::*;
use std::io::{BufRead, BufReader};
use std::net::Shutdown;

fn reply(
    status: &str,
    headers: &str,
    body: &str,
    delay: Duration,
) -> (SocketAddr, thread::JoinHandle<String>) {
    let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).unwrap();
    let addr = listener.local_addr().unwrap();
    let (status, headers, body) = (status.to_owned(), headers.to_owned(), body.to_owned());
    let server = thread::spawn(move || {
        let (stream, _) = listener.accept().unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(2)))
            .unwrap();
        let mut reader = BufReader::new(stream);
        let mut request = String::new();
        loop {
            let mut line = String::new();
            assert_ne!(reader.read_line(&mut line).unwrap(), 0);
            request.push_str(&line);
            if line == "\r\n" {
                break;
            }
        }
        let length: usize = request
            .lines()
            .find_map(|line| line.strip_prefix("Content-Length: "))
            .unwrap()
            .parse()
            .unwrap();
        let mut payload = vec![0; length];
        reader.read_exact(&mut payload).unwrap();
        request.push_str(std::str::from_utf8(&payload).unwrap());
        thread::sleep(delay);
        write!(
            reader.get_mut(),
            "HTTP/1.1 {status}\r\nConnection: close\r\n{headers}Content-Length: {}\r\n\r\n{body}",
            body.len()
        )
        .expect("send HTTP response");
        reader.get_mut().shutdown(Shutdown::Write).unwrap();
        request
    });
    (addr, server)
}

#[test]
fn free_prelaunch_probe_releases_the_port_before_spawn() {
    let reservation = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).unwrap();
    let addr = reservation.local_addr().unwrap();
    drop(reservation);
    assert!(matches!(probe(addr, true), Ok(Listener::Free)));
    let _child_listener = TcpListener::bind(addr).unwrap();
}

#[test]
fn existing_listener_keeps_the_http_timeout_in_both_phases() {
    for before_launch in [true, false] {
        let (addr, server) = reply(
            "200 OK",
            "",
            r#"{"result":{"serverInfo":{"name":"branchline"}}}"#,
            Duration::from_millis(120),
        );
        // The HTTP response can take longer than the 25 ms connection poll.
        let started = Instant::now();
        let result = probe(addr, before_launch).map(|listener| match listener {
            Listener::Free => "Free",
            Listener::Branchline => "Branchline",
        });
        assert_eq!(
            result,
            Ok("Branchline"),
            "before_launch={before_launch}, elapsed={:?}",
            started.elapsed()
        );
        let request = server.join().unwrap();
        assert!(request.starts_with("POST /mcp HTTP/1.1\r\n"));
        assert!(request.contains(r#""method":"initialize""#));
    }
}

#[test]
fn wrong_or_malformed_listeners_are_not_treated_as_free() {
    for before_launch in [true, false] {
        for (status, headers, body) in [
            (
                "200 OK",
                "",
                r#"{"result":{"serverInfo":{"name":"other"}}}"#,
            ),
            ("200 OK", "", "not json"),
            ("401 Unauthorized", "", ""),
            ("401 Unauthorized", "x-branchline-mcp: 0\r\n", ""),
        ] {
            let (addr, server) = reply(status, headers, body, Duration::ZERO);
            let error = probe(addr, before_launch).err().unwrap();
            assert!(error.contains("is in use"), "{error}");
            server.join().unwrap();
        }
    }
}

#[test]
fn authenticated_listener_identity_does_not_bypass_registration_denial() {
    for before_launch in [true, false] {
        let (addr, server) = reply(
            "401 Unauthorized",
            "X-Branchline-MCP: 1\r\n",
            "",
            Duration::ZERO,
        );
        assert!(matches!(
            probe(addr, before_launch),
            Ok(Listener::Branchline)
        ));
        server.join().unwrap();
    }
    let (addr, server) = reply("401 Unauthorized", "", "", Duration::ZERO);
    assert!(register(addr, "/review/checkout")
        .unwrap_err()
        .contains("same BRANCHLINE_MCP_TOKEN"));
    server.join().unwrap();
}

#[test]
fn registration_keeps_the_checkout_and_identity_headers() {
    let root = "/review/répo space";
    let (addr, server) = reply("200 OK", "", r#"{"repoId":"checkout-id"}"#, Duration::ZERO);
    register(addr, root).unwrap();
    let request = server.join().unwrap();
    assert!(request.starts_with("POST /desktop/repositories HTTP/1.1\r\n"));
    assert!(request.contains("x-branchline-mcp: 1\r\n"));
    if let Some(token) = configured_token().unwrap() {
        assert!(request.contains(&format!("Authorization: {}\r\n", token.to_str().unwrap())));
    }
    let body = request.split_once("\r\n\r\n").unwrap().1;
    assert_eq!(serde_json::from_str::<Value>(body).unwrap()["path"], root);
}

#[cfg(windows)]
#[test]
#[ignore = "Run explicitly on idle native Windows to verify the negative-connect improvement"]
fn unused_loopback_checks_do_not_wait_for_the_http_timeout() {
    for before_launch in [true, false] {
        let reservation = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).unwrap();
        let addr = reservation.local_addr().unwrap();
        drop(reservation);
        let started = Instant::now();
        assert!(matches!(probe(addr, before_launch), Ok(Listener::Free)));
        assert!(started.elapsed() < Duration::from_millis(150));
    }
}
