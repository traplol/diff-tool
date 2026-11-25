use serde_json::{json, Value};
use std::{
    io::{BufRead, BufReader, Write},
    path::Path,
    process::{Child, ChildStdin, ChildStdout, Command, Stdio},
};

struct Worker {
    child: Child,
    input: Option<ChildStdin>,
    output: BufReader<ChildStdout>,
    serial: u64,
}

impl Worker {
    fn start() -> Self {
        let mut child = Command::new(env!("CARGO_BIN_EXE_branchline-git-worker"))
            .arg("--stdio")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()
            .unwrap();
        let input = child.stdin.take();
        let output = BufReader::new(child.stdout.take().unwrap());
        Self {
            child,
            input,
            output,
            serial: 0,
        }
    }

    fn request(&mut self, mut request: Value) -> Value {
        self.serial += 1;
        request["id"] = json!(self.serial);
        let input = self.input.as_mut().unwrap();
        writeln!(input, "{request}").unwrap();
        input.flush().unwrap();
        let mut line = String::new();
        assert!(self.output.read_line(&mut line).unwrap() > 0);
        let response: Value = serde_json::from_str(&line).unwrap();
        assert_eq!(response["id"], self.serial);
        response
    }

    fn call(&mut self, request: Value) -> Value {
        let response = self.request(request);
        assert!(response.get("error").is_none(), "{response}");
        response["result"].clone()
    }
}

impl Drop for Worker {
    fn drop(&mut self) {
        drop(self.input.take());
        assert!(self.child.wait().unwrap().success());
    }
}

fn git(root: &Path, args: &[&str]) -> String {
    let output = Command::new("git")
        .arg("-C")
        .arg(root)
        .args(args)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    String::from_utf8(output.stdout).unwrap().trim().to_owned()
}

#[test]
fn real_pipe_preserves_frozen_working_tree_payloads_and_caller_refs() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    for args in [
        &["init", "-qb", "main"][..],
        &["config", "user.name", "Worker Test"],
        &["config", "user.email", "worker@example.invalid"],
        &["config", "commit.gpgsign", "false"],
        &["config", "core.autocrlf", "false"],
    ] {
        git(root, args);
    }
    let file = root.join("file.txt");
    std::fs::write(&file, "base\n").unwrap();
    git(root, &["add", "."]);
    git(root, &["commit", "-qm", "base"]);
    git(root, &["switch", "-qc", "review"]);
    std::fs::write(&file, "review\n").unwrap();
    git(root, &["commit", "-qam", "review"]);
    let mut worker = Worker::start();
    let pid = worker.call(json!({"op":"hello"}))["pid"].clone();
    let opened = worker.call(json!({"op":"open","path":root}));
    let view = opened["repo"].clone();
    let branch = worker.call(json!({"op":"compare","view":view,
        "left":"refs/heads/main","right":"refs/heads/review"}));
    assert_eq!(branch["head"], view["refs"]["refs/heads/review"]);

    std::fs::write(&file, "staged\n").unwrap();
    git(root, &["add", "file.txt"]);
    std::fs::write(&file, "unstaged\n").unwrap();
    std::fs::write(root.join("untracked ü.txt"), "untracked\n").unwrap();
    let frozen = worker.call(json!({"op":"working_tree","view":view,
        "checkout":"refs/heads/review","untracked_paths":null}));
    let files = frozen["files"].as_array().unwrap();
    assert_eq!(files.len(), 3);
    let selected = files
        .iter()
        .find(|file| file["group"] == "Unstaged")
        .unwrap();
    assert!(selected["local_sections"][0].is_string());
    let mut header = frozen.clone();
    header.as_object_mut().unwrap().remove("files");
    let patch_request = json!({"op":"display_patch","comparison":header,"file":selected});
    let patch = worker.call(patch_request.clone());
    assert!(patch[0].as_str().unwrap().contains("+unstaged"));
    let index = std::fs::read(root.join(".git/index")).unwrap();
    let scoped = worker.call(json!({"op":"working_tree_paths","view":view,
        "checkout":"refs/heads/review","paths":["file.txt"]}));
    assert_eq!(scoped["files"].as_array().unwrap().len(), 2);
    assert_eq!(std::fs::read(root.join(".git/index")).unwrap(), index);
    let scoped_file = scoped["files"]
        .as_array()
        .unwrap()
        .iter()
        .find(|file| file["group"] == "Unstaged")
        .unwrap();
    let mut scoped_header = scoped.clone();
    scoped_header.as_object_mut().unwrap().remove("files");
    let scoped_patch = json!({"op":"display_patch","comparison":scoped_header,"file":scoped_file});
    assert_eq!(worker.call(scoped_patch.clone()), patch);
    let contents_request = json!({"op":"file_contents","file":selected});
    assert_eq!(worker.call(contents_request.clone()), json!(["unstaged"]));
    std::fs::write(&file, "changed after snapshot\n").unwrap();
    assert_eq!(worker.call(scoped_patch.clone()), patch);
    assert_eq!(worker.call(patch_request.clone()), patch);
    assert_eq!(worker.call(contents_request.clone()), json!(["unstaged"]));
    let mut invalid = patch_request.clone();
    invalid["file"]["local_sections"][0] = json!("not!base64");
    assert!(worker.request(invalid)["error"]
        .as_str()
        .unwrap()
        .contains("byte payload"));
    assert!(worker.request(json!({"op":"run_shell"}))["error"].is_string());

    git(root, &["add", "file.txt"]);
    git(root, &["commit", "-qm", "later"]);
    let fresh = worker.call(json!({"op":"open","path":root}))["repo"].clone();
    assert_eq!(worker.call(scoped_patch), patch);
    assert_ne!(
        fresh["refs"]["refs/heads/review"],
        view["refs"]["refs/heads/review"]
    );
    assert_eq!(worker.call(patch_request.clone()), patch);
    assert_eq!(worker.call(contents_request.clone()), json!(["unstaged"]));
    let mut logical_view = view;
    logical_view["root"] = json!("not-the-execution-filesystem");
    let old = worker.call(json!({"op":"compare","view":logical_view,
        "left":"refs/heads/main","right":"refs/heads/review"}));
    assert_eq!(old["head"], branch["head"]);
    let filtered = worker.call(json!({"op":"working_tree","view":fresh,
        "checkout":"refs/heads/review","untracked_paths":[]}));
    assert!(filtered["files"]
        .as_array()
        .unwrap()
        .iter()
        .all(|file| file["group"] != "Untracked"));
    assert_eq!(worker.call(json!({"op":"hello"}))["pid"], pid);
    let mut restarted = Worker::start();
    restarted.call(json!({"op":"open","path":root}));
    assert_eq!(restarted.call(patch_request), patch);
    assert_eq!(restarted.call(contents_request), json!(["unstaged"]));
}
