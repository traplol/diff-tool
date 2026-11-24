//! Repository-scoped MCP Streamable HTTP server.
pub(crate) mod desktop;
mod tools;

use crate::{config, git};
use axum::{
    body::Bytes,
    extract::State,
    http::{header, HeaderMap, HeaderValue, StatusCode},
    response::{IntoResponse, Response},
    routing::any,
    Router,
};
use serde_json::{json, Value};
use std::{
    collections::BTreeMap,
    ffi::OsString,
    net::{Ipv4Addr, SocketAddrV4},
    path::PathBuf,
    sync::{Arc, Mutex},
};
use tokio::sync::Semaphore;

const VERSIONS: &[&str] = &["2025-11-25", "2025-06-18", "2025-03-26"];
const PROTOCOL_HEADER: &str = "mcp-protocol-version";
const IDENTITY_HEADER: &str = "x-branchline-mcp";

const REGISTER_PATH: &str = "/desktop/repositories";

struct Server {
    repositories: Mutex<BTreeMap<String, PathBuf>>,
    port: u16,
    token: Option<HeaderValue>,
    workers: Arc<Semaphore>,
}

pub fn run(args: impl Iterator<Item = OsString>) -> Result<(), String> {
    let mut paths = Vec::new();
    let mut port = None;
    let mut args = args;
    while let Some(arg) = args.next() {
        if arg == "--help" || arg == "-h" {
            println!(
                "Usage: branchline --mcp [DIRECTORY ...] [--port PORT]\nServe one or more checkouts at http://127.0.0.1:PORT/mcp."
            );
            return Ok(());
        }
        if arg == "--port" && port.is_none() {
            port = Some(parse_port(
                args.next()
                    .and_then(|arg| arg.into_string().ok())
                    .as_deref()
                    .ok_or("--port requires a port number.")?,
            )?);
        } else if arg == "--" {
            paths.extend(args.map(PathBuf::from));
            break;
        } else if !arg.to_string_lossy().starts_with('-') {
            paths.push(PathBuf::from(arg));
        } else {
            return Err("Usage: branchline --mcp [DIRECTORY ...] [--port PORT]".into());
        }
    }
    let configured = config::path().and_then(|path| config::read(&path));
    let explicit_port = port.is_some() || std::env::var_os("BRANCHLINE_MCP_PORT").is_some();
    let settings = match configured {
        Ok(settings) => settings.unwrap_or_default(),
        Err(_) if explicit_port && !paths.is_empty() => config::Settings::default(),
        Err(error) => return Err(error),
    };

    let port = match port {
        Some(port) => port,
        None => configured_port(&settings)?,
    };
    let token = configured_token()?;
    let mut repositories = BTreeMap::new();
    if paths.is_empty() && !settings.mcp_repositories.is_empty() {
        for (id, path) in settings.mcp_repositories {
            if id.trim().is_empty() || !path.is_absolute() {
                return Err(format!(
                    "MCP repository {id:?} needs a name and an absolute checkout path."
                ));
            }
            let root = git::open_repo(&path)
                .map_err(|e| format!("MCP repository {id:?}: {e}"))?
                .root;
            repositories.insert(id, root);
        }
    } else {
        if paths.is_empty() {
            paths.push(std::env::current_dir().map_err(|e| e.to_string())?);
        }
        for path in paths {
            let root = git::open_repo(&path)
                .map_err(|e| format!("{}: {e}", path.display()))?
                .root;
            repositories.insert(git::path_name(&root), root);
        }
    }
    tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .map_err(|e| e.to_string())?
        .block_on(async {
            let addr = SocketAddrV4::new(Ipv4Addr::LOCALHOST, port);
            let listener = tokio::net::TcpListener::bind(addr)
                .await
                .map_err(|e| format!("Could not bind Branchline MCP to {addr}: {e}"))?;
            eprintln!("Branchline MCP is listening at http://{addr}/mcp");
            let state = Arc::new(Server {
                repositories: Mutex::new(repositories),
                port,
                token,
                workers: Arc::new(Semaphore::new(8)),
            });
            axum::serve(
                listener,
                Router::new()
                    .route("/mcp", any(endpoint))
                    .route(REGISTER_PATH, any(endpoint))
                    .with_state(state),
            )
            .await
            .map_err(|e| e.to_string())
        })
}

fn configured_token() -> Result<Option<HeaderValue>, String> {
    match std::env::var("BRANCHLINE_MCP_TOKEN") {
        Ok(token) if !token.is_empty() && token.bytes().all(|b| b.is_ascii_graphic()) => {
            HeaderValue::from_str(&format!("Bearer {token}"))
                .map(Some)
                .map_err(|e| e.to_string())
        }
        Ok(_) => Err("BRANCHLINE_MCP_TOKEN must contain visible ASCII without spaces.".into()),
        Err(std::env::VarError::NotPresent) => Ok(None),
        Err(e) => Err(format!("Invalid BRANCHLINE_MCP_TOKEN: {e}")),
    }
}

fn parse_port(raw: &str) -> Result<u16, String> {
    raw.parse()
        .ok()
        .filter(|port| *port > 0)
        .ok_or_else(|| "The MCP port must be between 1 and 65535.".into())
}

fn configured_port(settings: &config::Settings) -> Result<u16, String> {
    match std::env::var("BRANCHLINE_MCP_PORT") {
        Ok(port) => parse_port(&port),
        Err(std::env::VarError::NotPresent) => match settings.mcp_port {
            Some(port) if port > 0 => Ok(port),
            Some(_) => Err("mcp_port must be between 1 and 65535.".into()),
            None => Ok(config::DEFAULT_MCP_PORT),
        },
        Err(e) => Err(format!("Invalid BRANCHLINE_MCP_PORT: {e}")),
    }
}

fn single_header<'a>(headers: &'a HeaderMap, name: &str) -> Option<Option<&'a str>> {
    let all = headers.get_all(name);
    let mut values = all.iter();
    match values.next() {
        Some(value) if values.next().is_none() => value.to_str().ok().map(Some),
        Some(_) => None,
        None => Some(None),
    }
}

async fn endpoint(State(server): State<Arc<Server>>, request: axum::extract::Request) -> Response {
    let registration = request.uri().path() == REGISTER_PATH;
    let headers = request.headers();
    let ip = format!("127.0.0.1:{}", server.port);
    let localhost = format!("localhost:{}", server.port);
    let host_allowed = |host: &str| {
        host.eq_ignore_ascii_case(&ip)
            || host.eq_ignore_ascii_case(&localhost)
            || (server.port == 80 && ["127.0.0.1", "localhost"].contains(&host))
    };
    if !single_header(headers, "host")
        .flatten()
        .is_some_and(host_allowed)
        || !single_header(headers, "origin").is_some_and(|origin| {
            origin.is_none_or(|origin| origin.strip_prefix("http://").is_some_and(host_allowed))
        })
    {
        return StatusCode::FORBIDDEN.into_response();
    }
    if registration
        && (headers.contains_key(header::ORIGIN)
            || single_header(headers, IDENTITY_HEADER) != Some(Some("1")))
    {
        return StatusCode::FORBIDDEN.into_response();
    }
    if let Some(token) = &server.token {
        if single_header(headers, "authorization").flatten() != token.to_str().ok() {
            return (
                StatusCode::UNAUTHORIZED,
                [
                    (header::WWW_AUTHENTICATE.as_str(), "Bearer"),
                    (IDENTITY_HEADER, "1"),
                ],
            )
                .into_response();
        }
    }
    if !single_header(headers, PROTOCOL_HEADER)
        .is_some_and(|value| value.is_none_or(|value| VERSIONS.contains(&value)))
    {
        return (StatusCode::BAD_REQUEST, "Unsupported MCP protocol version").into_response();
    }
    if request.method() != axum::http::Method::POST {
        return (StatusCode::METHOD_NOT_ALLOWED, [(header::ALLOW, "POST")]).into_response();
    }
    if !single_header(headers, "content-type")
        .flatten()
        .is_some_and(|value| {
            value
                .split(';')
                .next()
                .is_some_and(|mime| mime.trim().eq_ignore_ascii_case("application/json"))
        })
    {
        return StatusCode::UNSUPPORTED_MEDIA_TYPE.into_response();
    }
    let bytes: Bytes = match axum::body::to_bytes(request.into_body(), 128 * 1024).await {
        Ok(bytes) => bytes,
        Err(_) => return StatusCode::PAYLOAD_TOO_LARGE.into_response(),
    };
    let message = match serde_json::from_slice::<Value>(&bytes) {
        Ok(value) => value,
        Err(_) => {
            return json_response(
                StatusCode::BAD_REQUEST,
                error(Value::Null, -32700, "Parse error"),
            )
        }
    };
    let Ok(permit) = server.workers.clone().try_acquire_owned() else {
        return StatusCode::SERVICE_UNAVAILABLE.into_response();
    };
    let result = tokio::task::spawn_blocking(move || {
        let _permit = permit;
        if registration {
            return Some(match register_repository(&server, &message) {
                Ok(repo_id) => json!({"repoId": repo_id}),
                Err(message) => json!({"error": message}),
            });
        }
        let repositories = server.repositories.lock().unwrap().clone();
        dispatch(&repositories, message)
    })
    .await;
    match result {
        Ok(Some(message)) => json_response(StatusCode::OK, message),
        Ok(None) => StatusCode::ACCEPTED.into_response(),
        Err(_) => StatusCode::INTERNAL_SERVER_ERROR.into_response(),
    }
}

fn register_repository(server: &Server, message: &Value) -> Result<String, String> {
    let path = message["path"]
        .as_str()
        .ok_or("Expected a checkout path.")?;
    let path = PathBuf::from(git::path_arg(path)?);
    if !path.is_absolute() {
        return Err("Expected an absolute checkout path.".into());
    }
    if let Some((id, _)) = server
        .repositories
        .lock()
        .unwrap()
        .iter()
        .find(|(_, root)| **root == path)
    {
        return Ok(id.clone());
    }
    let root = git::open_repo(&path)?.root;
    let mut repositories = server.repositories.lock().unwrap();
    if let Some((id, _)) = repositories.iter().find(|(_, path)| **path == root) {
        return Ok(id.clone());
    }
    let path_id = git::path_name(&root);
    let mut id = path_id.clone();
    let mut suffix = 2;
    while repositories.contains_key(&id) {
        id = format!("{path_id}#{suffix}");
        suffix += 1;
    }
    repositories.insert(id.clone(), root);
    Ok(id)
}

fn json_response(status: StatusCode, message: Value) -> Response {
    (
        status,
        [(header::CONTENT_TYPE, "application/json")],
        message.to_string(),
    )
        .into_response()
}

fn error(id: Value, code: i32, message: &str) -> Value {
    json!({"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}})
}

fn dispatch(repositories: &BTreeMap<String, PathBuf>, message: Value) -> Option<Value> {
    let id = message.get("id");
    if message["jsonrpc"] != "2.0"
        || id.is_some_and(|id| !id.is_string() && !id.is_i64() && !id.is_u64())
    {
        return Some(error(Value::Null, -32600, "Invalid request"));
    }
    let Some(method) = message["method"].as_str() else {
        if id.is_some() && (message.get("result").is_some() ^ message.get("error").is_some()) {
            return None;
        }
        return Some(error(Value::Null, -32600, "Invalid request"));
    };
    let id = id?.clone();
    let params = &message["params"];
    if !params.is_null() && !params.is_object() {
        return Some(error(id, -32602, "Expected named parameters"));
    }
    let result = match method {
        "initialize" => {
            let Some(version) = params["protocolVersion"].as_str() else {
                return Some(error(id, -32602, "protocolVersion is required"));
            };
            json!({
                "protocolVersion": if VERSIONS.contains(&version) { version } else { VERSIONS[0] },
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "branchline", "version": env!("CARGO_PKG_VERSION")},
                "instructions": "Use list_repositories to identify the checkout by repoId and path. Pass repoId to repository tools when more than one checkout is served. Use list_comments for feedback and reply_to_comment to record a response and optionally resolve the thread."
            })
        }
        "ping" => json!({}),
        "tools/list" => json!({"tools": tools::list(repositories.len() > 1)}),
        "tools/call" => {
            let Some(name) = params["name"].as_str() else {
                return Some(error(id, -32602, "Tool name is required"));
            };
            let args = params
                .get("arguments")
                .cloned()
                .unwrap_or_else(|| json!({}));
            if !args.is_object() || !tools::contains(name) {
                return Some(error(id, -32602, "Unknown tool or invalid arguments"));
            }
            match tools::call(repositories, name, args) {
                Ok(data) => json!({
                    "content": [{"type": "text", "text": data.to_string()}],
                    "structuredContent": data
                }),
                Err(message) => {
                    json!({"isError": true, "content": [{"type": "text", "text": message}]})
                }
            }
        }
        _ => return Some(error(id, -32601, "Method not found")),
    };
    Some(json!({"jsonrpc": "2.0", "id": id, "result": result}))
}
