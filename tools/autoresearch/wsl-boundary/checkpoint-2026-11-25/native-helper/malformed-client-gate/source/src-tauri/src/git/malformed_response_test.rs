//! Manual native integration gate; the production remote.rs prefix is unchanged.
use super::*;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

#[cfg(windows)]
fn wsl_python(location: &Location, code: &str, arguments: &[String]) -> Value {
    let Location::Wsl(checkout) = location;
    let output = checkout.launcher().unwrap()
        .args(["--exec", "/usr/bin/python3", "-c", code])
        .args(arguments).output().unwrap();
    assert!(output.status.success(), "{}", String::from_utf8_lossy(&output.stderr));
    serde_json::from_slice(&output.stdout).unwrap()
}

#[cfg(windows)]
fn native_snapshot(location: &Location, pid: u64, image: &str) -> Value {
    wsl_python(location, r#"import ctypes,hashlib,json,os,pathlib,sys
p=pathlib.Path('/proc')/sys.argv[1];image=pathlib.Path(sys.argv[2]);result=None
try:
 f=(p/'stat').read_text().rsplit(') ',1)[1].split()
 result={'pid':int(sys.argv[1]),'identity':f[19],'state':f[0]}
 result.update(exe=os.readlink(p/'exe'),expected_exe=os.path.realpath('/usr/bin/python3'),
               args=(p/'cmdline').read_bytes().decode().split('\0'))
 buf=ctypes.create_string_buffer(512);assert ctypes.CDLL(None).statfs(os.fsencode(image),buf)==0
 result.update(image=str(image),sha256=hashlib.sha256(image.read_bytes()).hexdigest(),
               filesystem_type=hex(ctypes.c_long.from_buffer(buf).value))
except (FileNotFoundError,ProcessLookupError):pass
print(json.dumps(result))"#, &[pid.to_string(), image.to_owned()])
}

#[cfg(target_os = "linux")]
fn native_snapshot(_location: &Location, pid: u64, _image: &str) -> Value {
    // Only the parsed integer is interpolated; no path is PowerShell source.
    let script = format!("[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); $p=Get-CimInstance Win32_Process -Filter 'ProcessId={pid}'; if($p){{@{{pid=[int]$p.ProcessId;identity=$p.CreationDate.ToString('o');exe=$p.ExecutablePath}}|ConvertTo-Json -Compress}}else{{[Console]::Write('null')}}");
    let output = Command::new("powershell.exe")
        .args(["-NoLogo", "-NoProfile", "-NonInteractive", "-Command", &script])
        .stdin(Stdio::null()).output().unwrap();
    assert!(output.status.success(), "{}", String::from_utf8_lossy(&output.stderr));
    serde_json::from_slice(&output.stdout).unwrap()
}

#[cfg(windows)]
fn prepare() -> (Location, PathBuf, String) {
    let root = Path::new(r"\\wsl.localhost\Ubuntu-26.04\home\max\benchmarks\branchline-boundary");
    let location = Location::Wsl(super::super::windows::WslCheckout::from_path(root).unwrap());
    let directory = PathBuf::from(env::var_os("LOCALAPPDATA").unwrap()).join("Branchline/git-workers");
    let mut bytes = include_bytes!("fixtures/malformed-linux.py").to_vec();
    bytes.extend_from_slice(format!("\n# owned-malformed-gate-{}-{}\n", std::process::id(),
        SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos()).as_bytes());
    install(location, directory, bytes)
}

#[cfg(target_os = "linux")]
fn prepare() -> (Location, PathBuf, String) {
    let directory = windows_worker_cache().unwrap();
    let root = wslpath("-w", directory.as_os_str()).unwrap();
    let location = Location::Windows(root.into_os_string());
    // Built once from the adjacent dependency-free Rust fixture after VM release.
    let mut bytes = include_bytes!("fixtures/malformed-windows.exe").to_vec();
    bytes.extend_from_slice(format!("\nowned-malformed-gate-{}-{}\n", std::process::id(),
        SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos()).as_bytes());
    install(location, directory, bytes)
}

fn install(location: Location, directory: PathBuf, bytes: Vec<u8>) -> (Location, PathBuf, String) {
    let digest = format!("{:x}", Sha256::digest(&bytes));
    let extension = if cfg!(windows) { "" } else { ".exe" };
    let expected = directory.join(format!("branchline-git-worker-{digest}{extension}"));
    assert!(!expected.exists(), "Unique fixture cache path already exists");
    let helper = materialize(&directory, &bytes).unwrap();
    assert_eq!(helper, expected);
    assert_eq!(fs::read(&helper).unwrap(), bytes);
    println!("{}", serde_json::json!({"phase":"fixture-installed", "client_pid":std::process::id(),
        "owned_helper":helper,"owned_digest":digest}));
    (location, helper, digest)
}

#[test]
#[ignore = "Requires the released Windows/WSL VM and the built owned PE fixture"]
fn malformed_response_reaps_native_worker_before_connection_drop() {
    let (location, helper, digest) = prepare();
    let command = location.command(&helper).unwrap();
    let program = command.get_program().to_owned();
    let mut connection = Connection::start(command).unwrap();
    let hello = connection.request(&worker::Request::Hello).unwrap();
    assert_eq!(hello["protocol"], 1);
    assert_eq!(hello["os"], location.os());
    let pid = hello["pid"].as_u64().unwrap();
    #[cfg(windows)]
    let image = hello["image"].as_str().unwrap().to_owned();
    #[cfg(target_os = "linux")]
    let image = wslpath("-w", helper.as_os_str()).unwrap().to_str().unwrap().to_owned();
    let before = native_snapshot(&location, pid, &image);
    assert!(!before.is_null(), "Hello native PID is absent");
    assert_eq!(before["pid"], pid);
    #[cfg(windows)]
    {
        assert_eq!(before["exe"], before["expected_exe"]);
        assert_eq!(before["sha256"], digest);
        assert_eq!(before["filesystem_type"], "0xef53");
        assert!(image.ends_with(&format!("/branchline/git-workers/branchline-git-worker-{digest}")));
        assert!(before["args"].as_array().unwrap().iter().any(|a| a.as_str() == Some(image.as_str())));
    }
    #[cfg(target_os = "linux")]
    assert_eq!(normal_windows_path(OsStr::new(before["exe"].as_str().unwrap())).unwrap()
        .to_string_lossy().to_ascii_lowercase(), image.to_ascii_lowercase());
    println!("{}", serde_json::json!({"phase":"before-malformed-response", "hello":hello,
        "native_identity":before,"launcher_pid":connection.child.id(),"launcher_program":program.to_string_lossy(),
        "owned_helper":helper,"owned_digest":digest}));
    let error = connection.request(&worker::Request::Hello).unwrap_err();
    assert!(error.contains("unexpected request ID"), "{error}");
    assert!(!connection.valid);
    let launcher_exit = connection.child.try_wait().unwrap();
    assert!(launcher_exit.is_some(), "request did not reap the owned launcher");
    assert!(connection.input.is_some(), "Test must retain stdin until native-death proof");
    // Keep Connection, stdin, and stdout alive throughout this check. Drop would
    // close these pipes and could conceal an interop orphan after request().
    let deadline = Instant::now() + Duration::from_secs(6);
    let last = loop {
        let observed = native_snapshot(&location, pid, &image);
        if observed.is_null() || observed["identity"] != before["identity"] {
            break observed;
        }
        assert!(Instant::now() < deadline,
            "Native child survived malformed response while Connection retained pipes: before={before}; live={observed}; launcher={launcher_exit:?}; error={error}");
        std::thread::sleep(Duration::from_millis(50));
    };
    assert!(connection.request(&worker::Request::Hello).unwrap_err().contains("disconnected"));
    println!("{}", serde_json::json!({"phase":"passed-before-connection-drop",
        "native_before":before,"native_after":last,"launcher_pid":connection.child.id(),
        "launcher_exit":format!("{launcher_exit:?}"),"connection_valid":connection.valid,
        "retained_stdin":connection.input.is_some(),"error":error,"owned_helper":helper,"owned_digest":digest}));
    drop(connection);
    // Remove only this run's unique SHA-named input, never a cache directory.
    assert_eq!(format!("{:x}", Sha256::digest(fs::read(&helper).unwrap())), digest);
    fs::remove_file(&helper).unwrap();
    #[cfg(windows)]
    {
        let result = wsl_python(&location, r#"import hashlib,json,pathlib,sys
p=pathlib.Path(sys.argv[1]);digest=sys.argv[2]
assert p.name=='branchline-git-worker-'+digest
assert hashlib.sha256(p.read_bytes()).hexdigest()==digest
p.unlink();print(json.dumps({'removed_owned_native_cache':str(p)}))"#, &[image, digest]);
        println!("{result}");
    }
}
