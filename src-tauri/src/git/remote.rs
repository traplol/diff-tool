//! A persistent read-only Git worker beside a cross-boundary checkout.
//! Review storage and the repository's public root remain in the GUI process.
use super::{worker, Result};
use serde::Serialize;
use serde_json::Value;
#[cfg(any(branchline_git_worker, test))]
use sha2::{Digest, Sha256};
use std::{
    collections::HashMap,
    env,
    ffi::{OsStr, OsString},
    fs,
    io::{BufRead, BufReader, BufWriter, Write},
    path::{Path, PathBuf},
    process::{Child, ChildStdin, ChildStdout, Command, Stdio},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex, OnceLock, Weak,
    },
};

static WORKERS: OnceLock<Mutex<HashMap<PathBuf, Weak<Worker>>>> = OnceLock::new();
#[cfg(branchline_git_worker)]
static HELPER: OnceLock<Result<PathBuf>> = OnceLock::new();

#[derive(Serialize)]
struct Call<'a> {
    id: u64,
    #[serde(flatten)]
    request: &'a worker::Request,
}

fn transact(
    input: &mut impl Write,
    output: &mut impl BufRead,
    id: u64,
    request: &worker::Request,
) -> Result<worker::Response> {
    serde_json::to_writer(&mut *input, &Call { id, request })
        .map_err(|error| format!("Could not send a Git worker request: {error}"))?;
    input
        .write_all(b"\n")
        .and_then(|_| input.flush())
        .map_err(|error| format!("Could not send a Git worker request: {error}"))?;
    let mut line = String::new();
    if output
        .read_line(&mut line)
        .map_err(|error| format!("Could not read the Git worker response: {error}"))?
        == 0
    {
        return Err(
            "The Git storage worker closed its output. Refresh the repository to reconnect.".into(),
        );
    }
    if !line.ends_with('\n') {
        return Err("The Git storage worker returned an incomplete response frame.".into());
    }
    let response: worker::Response = serde_json::from_str(&line)
        .map_err(|error| format!("Invalid Git storage worker response: {error}"))?;
    if response.id != id {
        return Err("The Git storage worker returned an unexpected request ID. Refresh the repository to reconnect.".into());
    }
    Ok(response)
}

struct Connection {
    child: Child,
    input: Option<BufWriter<ChildStdin>>,
    output: BufReader<ChildStdout>,
    next_id: u64,
    valid: bool,
    initial: Option<worker::OpenResult>,
}

impl Connection {
    fn start(mut command: Command) -> Result<Self> {
        let mut child = command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|error| format!("Could not start the Git storage worker: {error}"))?;
        let input = BufWriter::new(
            child
                .stdin
                .take()
                .ok_or("Git worker stdin is unavailable.")?,
        );
        let output = BufReader::new(
            child
                .stdout
                .take()
                .ok_or("Git worker stdout is unavailable.")?,
        );
        Ok(Self {
            child,
            input: Some(input),
            output,
            next_id: 0,
            valid: true,
            initial: None,
        })
    }

    fn request(&mut self, request: &worker::Request) -> Result<Value> {
        if !self.valid {
            return Err(
                "The Git storage worker disconnected. Refresh the repository to reconnect.".into(),
            );
        }
        if let Some(status) = self.child.try_wait().map_err(|error| error.to_string())? {
            self.valid = false;
            return Err(format!(
                "The Git storage worker exited ({status}). Refresh the repository to reconnect."
            ));
        }
        self.next_id = self
            .next_id
            .checked_add(1)
            .ok_or("Git worker request counter exhausted.")?;
        match transact(
            self.input.as_mut().ok_or("Git worker stdin is closed.")?,
            &mut self.output,
            self.next_id,
            request,
        ) {
            Ok(response) => response.into_result(),
            Err(error) => {
                self.valid = false;
                let _ = self.child.kill();
                let _ = self.child.wait();
                Err(error)
            }
        }
    }
}

impl Drop for Connection {
    fn drop(&mut self) {
        // Discard a partial failed frame rather than flushing it during Drop.
        if let Some(input) = self.input.take() {
            let (pipe, _) = input.into_parts();
            drop(pipe);
        }
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

enum Location {
    #[cfg(windows)]
    Wsl(super::windows::WslCheckout),
    #[cfg(target_os = "linux")]
    Windows(OsString),
    #[cfg(all(test, unix))]
    Fixture { root: PathBuf, program: PathBuf },
}

impl Location {
    fn root(&self) -> &OsStr {
        match self {
            #[cfg(windows)]
            Self::Wsl(checkout) => &checkout.directory,
            #[cfg(target_os = "linux")]
            Self::Windows(path) => path,
            #[cfg(all(test, unix))]
            Self::Fixture { root, .. } => root.as_os_str(),
        }
    }

    fn os(&self) -> &'static str {
        match self {
            #[cfg(windows)]
            Self::Wsl(_) => "linux",
            #[cfg(target_os = "linux")]
            Self::Windows(_) => "windows",
            #[cfg(all(test, unix))]
            Self::Fixture { .. } => std::env::consts::OS,
        }
    }

    fn command(&self, helper: &Path) -> Result<Command> {
        match self {
            #[cfg(windows)]
            Self::Wsl(checkout) => {
                let mut command = checkout.launcher()?;
                // Only the constant program is shell code. The cached helper
                // path is a separate positional argument, never interpolated.
                command
                    .arg("--cd")
                    .arg(&checkout.directory)
                    .args([
                        "--exec",
                        "/bin/sh",
                        "-c",
                        r#"exec "$(wslpath -u "$1")" --stdio"#,
                        "branchline-git-worker",
                    ])
                    .arg(helper);
                Ok(command)
            }
            #[cfg(target_os = "linux")]
            Self::Windows(root) => {
                let mut command = Command::new(helper);
                command
                    .current_dir(wslpath("-u", &normal_windows_path(root)?)?)
                    .arg("--stdio");
                windows_environment(&mut command);
                Ok(command)
            }
            #[cfg(all(test, unix))]
            Self::Fixture { .. } => Ok(Command::new(helper)),
        }
    }

    fn logical_path(&self, execution: &Path) -> Result<PathBuf> {
        match self {
            #[cfg(windows)]
            Self::Wsl(checkout) => {
                use std::path::{Component, Prefix};
                let host = checkout.host_path(execution)?;
                let mut components = host.components();
                let Some(Component::Prefix(prefix)) = components.next() else {
                    return Err("Invalid WSL share path.".into());
                };
                let (server, share) = match prefix.kind() {
                    Prefix::UNC(server, share) | Prefix::VerbatimUNC(server, share) => {
                        (server, share)
                    }
                    _ => return Err("Invalid WSL share path.".into()),
                };
                // Preserve libgit2's existing raw root string. Configuration and
                // draft keys use it directly, unlike normalized SQLite keys.
                let mut legacy = OsString::from("//");
                legacy.push(server);
                legacy.push("/");
                legacy.push(share);
                let mut logical = PathBuf::from(legacy);
                for component in components {
                    logical.push(component.as_os_str());
                }
                Ok(logical)
            }
            #[cfg(target_os = "linux")]
            Self::Windows(_) => wslpath("-u", &normal_windows_path(execution.as_os_str())?),
            #[cfg(all(test, unix))]
            Self::Fixture { .. } => Ok(execution.to_owned()),
        }
    }

    fn at_root(&self, root: &Path) -> Result<Self> {
        match self {
            #[cfg(windows)]
            Self::Wsl(checkout) => {
                super::windows::WslCheckout::from_path(&checkout.host_path(root)?)
                    .map(Self::Wsl)
                    .ok_or_else(|| "Invalid WSL checkout path.".into())
            }
            #[cfg(target_os = "linux")]
            Self::Windows(_) => Ok(Self::Windows(root.as_os_str().to_owned())),
            #[cfg(all(test, unix))]
            Self::Fixture { program, .. } => Ok(Self::Fixture {
                root: root.to_owned(),
                program: program.clone(),
            }),
        }
    }
}

pub(super) struct Worker {
    location: Location,
    execution_root: PathBuf,
    logical_root: PathBuf,
    git_executable: Option<String>,
    #[cfg(target_os = "linux")]
    git_program: OnceLock<Result<PathBuf>>,
    connection: Mutex<Connection>,
    valid: AtomicBool,
}

impl std::fmt::Debug for Worker {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("Git storage worker")
            .field("execution_root", &self.execution_root)
            .finish()
    }
}

impl Worker {
    fn start(location: Location) -> Result<Self> {
        #[cfg(all(test, unix))]
        let helper = match &location {
            Location::Fixture { program, .. } => program.clone(),
            _ => helper_path()?,
        };
        #[cfg(not(all(test, unix)))]
        let helper = helper_path()?;
        let mut connection = Connection::start(location.command(&helper)?)?;
        let hello = connection.request(&worker::Request::Hello)?;
        if hello["protocol"].as_u64() != Some(worker::PROTOCOL.into())
            || hello["os"].as_str() != Some(location.os())
        {
            return Err(
                "The embedded Git storage worker is incompatible with this application.".into(),
            );
        }
        let opened: worker::OpenResult =
            serde_json::from_value(connection.request(&worker::Request::Open {
                path: super::path_name(Path::new(location.root())),
            })?)
            .map_err(|error| format!("Invalid Git worker repository metadata: {error}"))?;
        let execution_root = opened.repo.root.clone();
        let logical_root = location.logical_path(&execution_root)?;
        let git_executable = opened.git_executable.clone();
        connection.initial = Some(opened);
        Ok(Self {
            location,
            execution_root,
            logical_root,
            git_executable,
            #[cfg(target_os = "linux")]
            git_program: OnceLock::new(),
            connection: Mutex::new(connection),
            valid: AtomicBool::new(true),
        })
    }

    pub(super) fn request(&self, request: &worker::Request) -> Result<Value> {
        let mut connection = self
            .connection
            .lock()
            .map_err(|_| "The Git storage worker lock failed. Reopen the repository.")?;
        let result = connection.request(request);
        if !connection.valid {
            self.valid.store(false, Ordering::Relaxed);
        }
        result
    }

    pub(super) fn independent_reader(&self) -> Result<Arc<Self>> {
        // Search preparation can scan a large index before its streaming phase.
        // Its pipe must not queue foreground operations behind that work.
        Self::start(self.location.at_root(&self.execution_root)?).map(Arc::new)
    }

    pub(super) fn open(&self) -> Result<worker::OpenResult> {
        let mut connection = self
            .connection
            .lock()
            .map_err(|_| "The Git storage worker lock failed. Reopen the repository.")?;
        if let Some(initial) = connection.initial.take() {
            return Ok(initial);
        }
        let result = connection.request(&worker::Request::Open {
            path: super::path_name(&self.execution_root),
        });
        if !connection.valid {
            self.valid.store(false, Ordering::Relaxed);
        }
        serde_json::from_value(result?)
            .map_err(|error| format!("Invalid Git worker repository metadata: {error}"))
    }

    pub(super) fn logical_path(&self, execution: &Path) -> Result<PathBuf> {
        if execution == self.execution_root {
            return Ok(self.logical_root.clone());
        }
        self.location.logical_path(execution)
    }

    pub(super) fn register_alias(self: &Arc<Self>, root: &Path) -> Result<()> {
        registry()
            .lock()
            .map_err(|_| "The Git worker registry lock failed.")?
            .insert(
                std::path::absolute(root).map_err(|error| error.to_string())?,
                Arc::downgrade(self),
            );
        Ok(())
    }

    fn healthy(&self) -> bool {
        if !self.valid.load(Ordering::Relaxed) {
            return false;
        }
        match self.connection.try_lock() {
            Ok(mut connection) => match connection.child.try_wait() {
                Ok(None) => true,
                _ => {
                    connection.valid = false;
                    self.valid.store(false, Ordering::Relaxed);
                    false
                }
            },
            Err(std::sync::TryLockError::WouldBlock) => true,
            Err(std::sync::TryLockError::Poisoned(_)) => false,
        }
    }
}

fn registry() -> &'static Mutex<HashMap<PathBuf, Weak<Worker>>> {
    WORKERS.get_or_init(|| Mutex::new(HashMap::new()))
}

pub(super) fn for_root(root: &Path) -> Result<Option<Arc<Worker>>> {
    let key = std::path::absolute(root).map_err(|error| error.to_string())?;
    if let Some(worker) = registry()
        .lock()
        .map_err(|_| "The Git worker registry lock failed.")?
        .get(&key)
        .and_then(Weak::upgrade)
        .filter(|worker| worker.healthy())
    {
        return Ok(Some(worker));
    }
    let Some(location) = locate(&key)? else {
        return Ok(None);
    };
    let candidate = Arc::new(Worker::start(location)?);
    let mut entries = registry()
        .lock()
        .map_err(|_| "The Git worker registry lock failed.")?;
    if let Some(winner) = entries
        .get(&key)
        .or_else(|| entries.get(&candidate.logical_root))
        .and_then(Weak::upgrade)
        .filter(|worker| worker.healthy())
    {
        entries.insert(key, Arc::downgrade(&winner));
        return Ok(Some(winner));
    }
    entries.retain(|_, worker| worker.strong_count() > 0);
    entries.insert(key, Arc::downgrade(&candidate));
    entries.insert(candidate.logical_root.clone(), Arc::downgrade(&candidate));
    Ok(Some(candidate))
}

fn locate(root: &Path) -> Result<Option<Location>> {
    #[cfg(windows)]
    {
        Ok(super::windows::WslCheckout::from_path(root).map(Location::Wsl))
    }
    #[cfg(target_os = "linux")]
    {
        use std::{ffi::CString, os::unix::ffi::OsStrExt};
        if env::var_os("WSL_DISTRO_NAME").is_none() {
            return Ok(None);
        }
        let path =
            CString::new(root.as_os_str().as_bytes()).map_err(|_| "Invalid checkout path.")?;
        let mut filesystem = std::mem::MaybeUninit::<libc::statfs>::uninit();
        if unsafe { libc::statfs(path.as_ptr(), filesystem.as_mut_ptr()) } != 0 {
            return Ok(None);
        }
        let filesystem = unsafe { filesystem.assume_init() };
        // drvfs uses 9p on WSL2 and FUSE on some older configurations. Avoid
        // spawning wslpath at all for ordinary WSL ext4 checkouts.
        if !matches!(filesystem.f_type as u64, 0x0102_1997 | 0x6573_5546) {
            return Ok(None);
        }
        let path = fs::canonicalize(root).map_err(|error| error.to_string())?;
        let converted = wslpath("-w", path.as_os_str())?;
        let text = converted
            .to_str()
            .ok_or("Unsupported Windows checkout path.")?;
        if windows_drive_path(text) {
            Ok(Some(Location::Windows(converted.into_os_string())))
        } else {
            Ok(None)
        }
    }
}

#[cfg(target_os = "linux")]
fn wslpath(flag: &str, path: &OsStr) -> Result<PathBuf> {
    let output = Command::new("/usr/bin/wslpath")
        .arg(flag)
        .arg(path)
        .stdin(Stdio::null())
        .output()
        .map_err(|error| format!("Could not translate the WSL path: {error}"))?;
    if !output.status.success() {
        return Err("WSL could not translate this checkout path.".into());
    }
    let value = std::str::from_utf8(&output.stdout)
        .map_err(|_| "WSL returned a non-Unicode Windows path.")?
        .trim_end_matches(['\r', '\n']);
    if value.is_empty() {
        return Err("WSL returned an empty checkout path.".into());
    }
    Ok(PathBuf::from(value))
}

fn windows_drive_path(path: &str) -> bool {
    let bytes = path.as_bytes();
    bytes.len() >= 3
        && bytes[0].is_ascii_alphabetic()
        && bytes[1] == b':'
        && matches!(bytes[2], b'\\' | b'/')
}

#[cfg(target_os = "linux")]
fn normal_windows_path(path: &OsStr) -> Result<OsString> {
    let path = path.to_str().ok_or("Unsupported Windows Git path.")?;
    Ok(if let Some(unc) = path.strip_prefix(r"\\?\UNC\") {
        format!(r"\\{unc}").into()
    } else {
        path.strip_prefix(r"\\?\").unwrap_or(path).into()
    })
}

#[cfg(target_os = "linux")]
fn windows_environment(command: &mut Command) {
    const KEYS: [(&str, &str); 4] = [
        ("GIT_NO_LAZY_FETCH", "1"),
        ("GIT_TERMINAL_PROMPT", "0"),
        ("GIT_OPTIONAL_LOCKS", "0"),
        ("LC_ALL", "C"),
    ];
    let mut transfer: Vec<String> = env::var("WSLENV")
        .unwrap_or_default()
        .split(':')
        .filter(|entry| {
            !entry.is_empty()
                && !KEYS.iter().any(|(name, _)| {
                    entry
                        .split('/')
                        .next()
                        .is_some_and(|existing| existing.eq_ignore_ascii_case(name))
                })
        })
        .map(str::to_owned)
        .collect();
    for (name, value) in KEYS {
        command.env(name, value);
        // /w transfers from a WSL process to the Windows child only.
        transfer.push(format!("{name}/w"));
    }
    command.env("WSLENV", transfer.join(":"));
}

/// Searches retain their streaming/cancellation path instead of monopolizing
/// the foreground worker. Windows -> WSL uses windows::command as before.
pub(super) fn command(root: &Path) -> Result<Option<Command>> {
    #[cfg(windows)]
    {
        let _ = root;
        Ok(None)
    }
    #[cfg(target_os = "linux")]
    {
        let Some(worker) = for_root(root)? else {
            return Ok(None);
        };
        let program = worker
            .git_program
            .get_or_init(|| {
                let path = worker
                    .git_executable
                    .as_ref()
                    .ok_or("Install Git for Windows to search this Windows checkout.")?;
                wslpath("-u", &normal_windows_path(OsStr::new(path))?)
            })
            .clone()?;
        let mut command = Command::new(program);
        command
            .args(["--no-pager", "--literal-pathspecs", "-C"])
            .arg(&worker.execution_root)
            .stdin(Stdio::null());
        windows_environment(&mut command);
        Ok(Some(command))
    }
}

fn helper_path() -> Result<PathBuf> {
    #[cfg(not(branchline_git_worker))]
    {
        Err("This build does not include the cross-boundary Git worker. Rebuild with build.sh for Windows/WSL repository support.".into())
    }
    #[cfg(branchline_git_worker)]
    {
        HELPER
            .get_or_init(|| {
                let bytes = include_bytes!(env!("BRANCHLINE_GIT_WORKER_PATH")).as_slice();
                #[cfg(windows)]
                let directory = env::var_os("LOCALAPPDATA")
                    .map(PathBuf::from)
                    .filter(|path| path.is_absolute())
                    .map(|path| path.join("Branchline/git-workers"));
                #[cfg(not(windows))]
                let directory = env::var_os("XDG_CACHE_HOME")
                    .map(PathBuf::from)
                    .or_else(|| env::var_os("HOME").map(|home| PathBuf::from(home).join(".cache")))
                    .filter(|path| path.is_absolute())
                    .map(|path| path.join("branchline/git-workers"));
                materialize(
                    &directory.ok_or("Could not locate the Git worker cache directory.")?,
                    bytes,
                )
            })
            .clone()
    }
}

#[cfg(any(branchline_git_worker, test))]
fn materialize(directory: &Path, bytes: &[u8]) -> Result<PathBuf> {
    let expected = Sha256::digest(bytes);
    let digest = format!("{expected:x}");
    let extension = if cfg!(windows) { "" } else { ".exe" };
    let path = directory.join(format!("branchline-git-worker-{digest}{extension}"));
    fs::create_dir_all(directory)
        .map_err(|error| format!("Could not create the Git worker cache: {error}"))?;
    let matches = || fs::read(&path).is_ok_and(|cached| Sha256::digest(&cached) == expected);
    if !matches() {
        let mut temporary = tempfile::NamedTempFile::new_in(directory)
            .map_err(|error| format!("Could not create the cached Git worker: {error}"))?;
        temporary
            .write_all(bytes)
            .and_then(|_| temporary.as_file().sync_all())
            .map_err(|error| format!("Could not write the cached Git worker: {error}"))?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            temporary
                .as_file()
                .set_permissions(fs::Permissions::from_mode(0o755))
                .map_err(|error| format!("Could not set Git worker permissions: {error}"))?;
        }
        if let Err(error) = temporary.persist(&path) {
            // Another GUI/MCP process may have atomically installed the same
            // digest while this process was preparing its temporary file.
            if !matches() {
                return Err(format!(
                    "Could not install the cached Git worker: {}",
                    error.error
                ));
            }
        }
    }
    if !matches() {
        return Err("The cached Git storage worker failed its digest check.".into());
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&path, fs::Permissions::from_mode(0o755))
            .map_err(|error| format!("Could not set Git worker permissions: {error}"))?;
    }
    Ok(path)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    #[test]
    fn request_frames_escape_newlines_and_match_response_ids() {
        let request = worker::Request::Open {
            path: "repo\nwith quotes \" and spaces".into(),
        };
        let mut input = Vec::new();
        let mut output = Cursor::new(b"{\"id\":7,\"result\":{\"ok\":true}}\n".as_slice());
        assert_eq!(
            transact(&mut input, &mut output, 7, &request)
                .unwrap()
                .into_result()
                .unwrap()["ok"],
            true
        );
        assert_eq!(input.iter().filter(|&&byte| byte == b'\n').count(), 1);
        let frame: Value = serde_json::from_slice(&input).unwrap();
        assert_eq!(frame["id"], 7);
        assert_eq!(frame["path"], "repo\nwith quotes \" and spaces");
    }

    #[test]
    fn stale_truncated_and_invalid_responses_are_rejected() {
        for (response, expected) in [
            ("{\"id\":8,\"result\":null}\n", "unexpected request ID"),
            ("", "closed its output"),
            ("{\"id\":7,\"result\":null}", "incomplete response frame"),
            ("{\"id\":7,\n", "Invalid Git storage worker response"),
        ] {
            let error = transact(
                &mut Vec::new(),
                &mut Cursor::new(response),
                7,
                &worker::Request::Hello,
            )
            .unwrap_err();
            assert!(error.contains(expected), "{error}");
        }
    }

    #[test]
    fn native_git_failures_remain_domain_errors() {
        let response = transact(
            &mut Vec::new(),
            &mut Cursor::new("{\"id\":2,\"error\":\"missing revision\"}\n"),
            2,
            &worker::Request::Hello,
        )
        .unwrap();
        assert_eq!(response.into_result().unwrap_err(), "missing revision");
    }

    #[cfg(unix)]
    #[test]
    fn a_git_failure_does_not_disconnect_the_persistent_child() {
        let mut command = Command::new("/bin/sh");
        command.args([
            "-c",
            r#"IFS= read -r line; printf '{"id":1,"error":"missing revision"}\n';
            IFS= read -r line; printf '{"id":2,"result":"still connected"}\n'; IFS= read -r line"#,
        ]);
        let mut connection = Connection::start(command).unwrap();
        assert_eq!(
            connection.request(&worker::Request::Hello).unwrap_err(),
            "missing revision"
        );
        assert!(connection.valid);
        assert_eq!(
            connection.request(&worker::Request::Hello).unwrap(),
            "still connected"
        );
    }

    #[cfg(unix)]
    #[test]
    fn a_protocol_failure_stops_and_reaps_only_the_owned_child() {
        let mut command = Command::new("/bin/sh");
        command.args([
            "-c",
            r#"IFS= read -r line; printf '{"id":999,"result":null}\n'; IFS= read -r line"#,
        ]);
        let mut connection = Connection::start(command).unwrap();
        assert!(connection
            .request(&worker::Request::Hello)
            .unwrap_err()
            .contains("unexpected request ID"));
        assert!(!connection.valid);
        assert!(connection.child.try_wait().unwrap().is_some());
    }

    #[cfg(unix)]
    #[test]
    fn blocked_search_preparation_does_not_queue_foreground_requests() {
        use std::{
            os::unix::fs::PermissionsExt,
            time::{Duration, Instant},
        };
        let directory = tempfile::tempdir().unwrap();
        let root = directory.path().join("repo");
        fs::create_dir(&root).unwrap();
        for args in [
            &["init", "-qb", "main"][..],
            &["config", "user.name", "Reader Test"],
            &["config", "user.email", "reader@example.invalid"],
            &["config", "commit.gpgsign", "false"],
        ] {
            super::super::git(&root, args).unwrap();
        }
        fs::write(root.join("file"), "base\n").unwrap();
        super::super::git(&root, &["add", "."]).unwrap();
        super::super::git(&root, &["commit", "-qm", "base"]).unwrap();
        super::super::git(&root, &["switch", "-qc", "review"]).unwrap();
        fs::write(root.join("file"), "review\n").unwrap();
        super::super::git(&root, &["commit", "-qam", "review"]).unwrap();
        let mut repo = super::super::open_repo(&root).unwrap();
        let comparison =
            super::super::compare(&repo, "refs/heads/main", "refs/heads/review").unwrap();
        let opened = serde_json::to_string(&worker::OpenResult {
            repo: repo.clone(),
            git_executable: None,
        })
        .unwrap();
        let compared = serde_json::to_string(&worker::WireComparison::from(comparison)).unwrap();
        let counter = directory.path().join("counter");
        let blocked = directory.path().join("blocked");
        let release = directory.path().join("release");
        let program = directory.path().join("fixture-worker");
        let quote = |value: &str| serde_json::to_string(value).unwrap();
        let script = format!(
            r#"#!/usr/bin/python3
import json, os, pathlib, sys, time
counter = pathlib.Path({counter})
instance = int(counter.read_text()) + 1 if counter.exists() else 1
counter.write_text(str(instance))
blocked, release = pathlib.Path({blocked}), pathlib.Path({release})
for line in sys.stdin:
    call = json.loads(line)
    if call['op'] == 'hello':
        result = {{'protocol':{protocol}, 'os':'{os}', 'pid':os.getpid()}}
    elif call['op'] == 'open':
        result = json.loads({opened})
    elif call['op'] == 'compare':
        if instance > 1:
            blocked.write_text('search preparation is running')
            deadline = time.monotonic() + 2
            while not release.exists() and time.monotonic() < deadline:
                time.sleep(.005)
        result = json.loads({compared})
    else:
        raise RuntimeError('Unexpected fixture operation')
    print(json.dumps({{'id':call['id'], 'result':result}}), flush=True)
"#,
            counter = quote(counter.to_str().unwrap()),
            blocked = quote(blocked.to_str().unwrap()),
            release = quote(release.to_str().unwrap()),
            protocol = worker::PROTOCOL,
            os = std::env::consts::OS,
            opened = quote(&opened),
            compared = quote(&compared)
        );
        fs::write(&program, script).unwrap();
        fs::set_permissions(&program, fs::Permissions::from_mode(0o755)).unwrap();
        repo.native = None;
        repo.remote = Some(Arc::new(
            Worker::start(Location::Fixture {
                root: root.clone(),
                program,
            })
            .unwrap(),
        ));
        let reader = repo.search_reader().unwrap();
        assert_eq!(reader.root, repo.root);
        assert_eq!(reader.refs, repo.refs);
        assert!(!Arc::ptr_eq(
            reader.remote.as_ref().unwrap(),
            repo.remote.as_ref().unwrap()
        ));
        let background = std::thread::spawn(move || {
            super::super::compare(&reader, "refs/heads/main", "refs/heads/review").unwrap()
        });
        let deadline = Instant::now() + Duration::from_secs(3);
        while !blocked.exists() && Instant::now() < deadline {
            std::thread::sleep(Duration::from_millis(5));
        }
        assert!(
            blocked.exists(),
            "Search never reached the blocked preparation"
        );
        let started = Instant::now();
        let foreground =
            super::super::compare(&repo, "refs/heads/main", "refs/heads/review").unwrap();
        assert!(started.elapsed() < Duration::from_millis(250));
        assert!(
            !background.is_finished(),
            "Foreground waited until search preparation finished"
        );
        fs::write(release, "continue").unwrap();
        assert_eq!(foreground.head, background.join().unwrap().head);
    }

    #[test]
    fn cached_worker_is_verified_and_corruption_is_replaced_atomically() {
        let directory = tempfile::tempdir().unwrap();
        let bytes = b"owned worker fixture";
        let path = materialize(directory.path(), bytes).unwrap();
        assert_eq!(fs::read(&path).unwrap(), bytes);
        fs::write(&path, b"corrupted executable").unwrap();
        assert_eq!(materialize(directory.path(), bytes).unwrap(), path);
        assert_eq!(fs::read(path).unwrap(), bytes);
    }

    #[cfg(windows)]
    #[test]
    fn wsl_worker_command_keeps_storage_cwd_and_helper_as_separate_arguments() {
        let checkout = super::super::windows::WslCheckout::from_path(Path::new(
            r"\\wsl.localhost\Ubuntu-26.04\home\réview space\repo;$(noop)",
        ))
        .unwrap();
        let helper = Path::new(r"C:\Users\max\worker's cache\git-worker");
        let command = Location::Wsl(checkout).command(helper).unwrap();
        assert_eq!(
            command.get_args().collect::<Vec<_>>(),
            [
                OsStr::new("--distribution"),
                OsStr::new("Ubuntu-26.04"),
                OsStr::new("--cd"),
                OsStr::new("/home/réview space/repo;$(noop)"),
                OsStr::new("--exec"),
                OsStr::new("/bin/sh"),
                OsStr::new("-c"),
                OsStr::new(r#"exec "$(wslpath -u "$1")" --stdio"#),
                OsStr::new("branchline-git-worker"),
                helper.as_os_str(),
            ]
        );
        assert_eq!(command.get_current_dir(), None);
    }

    #[cfg(target_os = "linux")]
    #[test]
    #[ignore = "Requires WSL path translation; run explicitly inside WSL"]
    fn windows_worker_command_maps_its_storage_cwd_before_interop() {
        assert!(env::var_os("WSL_DISTRO_NAME").is_some());
        let normal = OsStr::new(r"C:\Windows");
        let expected = wslpath("-u", normal).unwrap();
        for root in [normal, OsStr::new(r"\\?\C:\Windows")] {
            let command = Location::Windows(root.to_owned())
                .command(Path::new("/tmp/owned-helper.exe"))
                .unwrap();
            assert_eq!(command.get_current_dir(), Some(expected.as_path()));
            assert_eq!(
                command.get_args().collect::<Vec<_>>(),
                [OsStr::new("--stdio")]
            );
        }
    }

    #[cfg(windows)]
    #[test]
    fn wsl_logical_roots_preserve_legacy_raw_preference_and_draft_keys() {
        for (input, execution, expected) in [
            (
                r"\\wsl.localhost\Ubuntu-26.04\home\max\repo",
                "/home/max/repo",
                r"//wsl.localhost/Ubuntu-26.04\home\max\repo",
            ),
            (
                r"\\?\UNC\WSL$\Debian\home\réview space\Repo",
                "/home/réview space/Repo",
                r"//WSL$/Debian\home\réview space\Repo",
            ),
            (
                r"\\wSl.LoCaLhOsT\UbUnTu\Home\MAX\Repo",
                "/Home/MAX/Repo",
                r"//wSl.LoCaLhOsT/UbUnTu\Home\MAX\Repo",
            ),
        ] {
            let checkout = super::super::windows::WslCheckout::from_path(Path::new(input)).unwrap();
            let logical = Location::Wsl(checkout)
                .logical_path(Path::new(execution))
                .unwrap();
            assert_eq!(logical.as_os_str(), OsStr::new(expected));
        }
        let checkout = super::super::windows::WslCheckout::from_path(Path::new(
            r"\\wsl.localhost\Ubuntu\home\max\repo",
        ))
        .unwrap();
        let location = Location::Wsl(checkout);
        for invalid in [
            "/home/../repo",
            "/home/./repo",
            "/home/colon:repo",
            r"/home/back\slash",
        ] {
            assert!(
                location.logical_path(Path::new(invalid)).is_err(),
                "{invalid}"
            );
        }
    }

    #[test]
    fn only_drive_absolute_paths_identify_windows_storage() {
        assert!(windows_drive_path(r"C:\Users\max\repo"));
        assert!(windows_drive_path("d:/repo"));
        assert!(!windows_drive_path(r"\\wsl.localhost\Ubuntu\home\max\repo"));
        assert!(!windows_drive_path("C:relative"));
        assert!(!windows_drive_path("/home/max/repo"));
    }
}
