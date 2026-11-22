//! Local Git plumbing for immutable branch and working-tree review snapshots.
mod patch_data;

use serde::Serialize;
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::ffi::{OsStr, OsString};
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

pub const EMPTY: &str = ":empty:";
pub const WORKTREE: &str = ":worktree:";
type Result<T> = std::result::Result<T, String>;

#[derive(Clone, Debug, Serialize)]
pub struct Repository {
    #[serde(serialize_with = "serialize_root")]
    pub root: PathBuf,
    pub refs: BTreeMap<String, String>,
    pub initial: Vec<String>,
    pub default_branch: Option<String>,
    pub checkout: String,
}

#[derive(Clone, Debug, Serialize)]
pub struct Change {
    pub status: String,
    pub old: String,
    pub path: String,
    pub added: Option<usize>,
    pub removed: Option<usize>,
    pub old_mode: String,
    pub mode: String,
    pub old_oid: String,
    pub oid: String,
    pub group: String,
    #[serde(skip)]
    local_sections: Vec<Vec<u8>>,
}

#[derive(Clone, Debug, Serialize)]
pub struct Comparison {
    pub left: String,
    pub right: String,
    pub left_tip: String,
    pub base: String,
    pub head: String,
    pub files: Vec<Change>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Line {
    pub kind: String,
    pub text: String,
    pub old: Option<usize>,
    pub new: Option<usize>,
    pub hunk: usize,
}

#[derive(Clone, Debug, Serialize)]
pub struct Commit {
    pub sha: String,
    pub author: String,
    pub date: String,
    pub subject: String,
}

// A webview cannot represent arbitrary Unix path bytes. Reserve one printable
// prefix and escape names starting with it too, so two files never collide.
const BYTE_PREFIX: &str = "␛git:";
pub(crate) fn name(bytes: &[u8]) -> String {
    if let Ok(s) = std::str::from_utf8(bytes) {
        if !s.starts_with(BYTE_PREFIX) {
            return s.to_owned();
        }
    }
    use std::fmt::Write;
    let mut s = BYTE_PREFIX.to_string();
    for b in bytes {
        write!(s, "{b:02x}").unwrap();
    }
    s
}

// Unix permits arbitrary bytes in a checkout path. Carry the same reversible
// representation across IPC that we use for Git filenames.
pub(crate) fn path_name(path: &Path) -> String {
    #[cfg(unix)]
    {
        use std::os::unix::ffi::OsStrExt;
        name(path.as_os_str().as_bytes())
    }
    #[cfg(not(unix))]
    {
        name(path.to_string_lossy().as_bytes())
    }
}

fn serialize_root<S: serde::Serializer>(
    path: &Path,
    serializer: S,
) -> std::result::Result<S::Ok, S::Error> {
    serializer.serialize_str(&path_name(path))
}

pub(crate) fn path_arg(s: &str) -> Result<OsString> {
    let Some(hex) = s.strip_prefix(BYTE_PREFIX) else {
        return Ok(s.into());
    };
    if hex.len() % 2 != 0 || !hex.is_ascii() {
        return Err("Invalid Git path encoding.".into());
    }
    let bytes = (0..hex.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&hex[i..i + 2], 16))
        .collect::<std::result::Result<Vec<_>, _>>()
        .map_err(|_| "Invalid Git path encoding.")?;
    #[cfg(unix)]
    {
        use std::os::unix::ffi::OsStringExt;
        Ok(OsString::from_vec(bytes))
    }
    #[cfg(not(unix))]
    {
        String::from_utf8(bytes)
            .map(OsString::from)
            .map_err(|_| "Invalid Git path encoding.".into())
    }
}

pub fn working_path(root: &Path, s: &str) -> Result<PathBuf> {
    Ok(root.join(path_arg(s)?))
}

#[cfg(windows)]
fn git_executable(directory: &Path) -> Result<PathBuf> {
    let dirs: Vec<_> = [std::env::current_dir().ok(), directory.canonicalize().ok()]
        .into_iter()
        .flatten()
        .filter_map(|p| p.canonicalize().ok())
        .collect();
    let checkouts: Vec<_> = dirs
        .iter()
        .flat_map(|p| p.ancestors())
        .filter(|p| p.join(".git").is_file() || p.join(".git/HEAD").is_file())
        .collect();
    std::env::split_paths(&std::env::var_os("PATH").unwrap_or_default())
        .filter(|p| p.is_absolute())
        .filter_map(|p| p.join("git.exe").canonicalize().ok())
        .find(|p| {
            p.is_file()
                && !dirs.iter().any(|d| Some(d.as_path()) == p.parent())
                && !checkouts.iter().any(|d| p.starts_with(d))
        })
        .ok_or_else(|| {
            "Install Git and add its installation directory to PATH, then reopen Branchline.".into()
        })
}

fn run_git<S: AsRef<OsStr>>(root: &Path, args: &[S], diff_exit: bool) -> Result<Vec<u8>> {
    #[cfg(windows)]
    let mut cmd = {
        use std::os::windows::process::CommandExt;
        let mut cmd = Command::new(git_executable(root)?);
        cmd.creation_flags(0x08000000);
        cmd
    };
    #[cfg(not(windows))]
    let mut cmd = Command::new("git");
    let output = cmd
        .args(["--no-pager", "--literal-pathspecs", "-C"])
        .arg(root)
        .args(args)
        .env("GIT_NO_LAZY_FETCH", "1")
        .env("GIT_TERMINAL_PROMPT", "0")
        .env("GIT_OPTIONAL_LOCKS", "0")
        .stdin(Stdio::null())
        .output()
        .map_err(|e| format!("Could not start Git. Check your PATH. {e}"))?;
    if output.status.success()
        || (diff_exit && output.status.code() == Some(1) && !output.stdout.is_empty())
    {
        return Ok(output.stdout);
    }
    let message = String::from_utf8_lossy(&output.stderr).trim().to_owned();
    Err(if message.is_empty() {
        "Git could not read this revision.".into()
    } else {
        message
    })
}

pub fn git(root: &Path, args: &[&str]) -> Result<Vec<u8>> {
    run_git(root, args, false)
}

fn git_text(root: &Path, args: &[&str]) -> Result<String> {
    let data = git(root, args)?;
    Ok(String::from_utf8_lossy(&data)
        .trim_end_matches(['\r', '\n'])
        .to_string())
}

pub fn ref_name(s: &str) -> String {
    match s {
        EMPTY => "Empty tree".into(),
        WORKTREE => "Working tree".into(),
        _ if s.starts_with("HEAD@") => format!(
            "Detached HEAD {}",
            s[5..].chars().take(8).collect::<String>()
        ),
        _ if s.starts_with("refs/remotes/") => format!("{} (remote)", &s[13..]),
        _ => s.strip_prefix("refs/heads/").unwrap_or(s).to_owned(),
    }
}

pub fn checkout_state(root: &Path) -> (String, Option<String>) {
    let head = git_text(root, &["rev-parse", "--verify", "HEAD"]).ok();
    let branch = git(root, &["symbolic-ref", "--quiet", "HEAD"])
        .ok()
        .map(|v| name(v.strip_suffix(b"\n").unwrap_or(&v)))
        .unwrap_or_else(|| {
            head.as_ref()
                .map_or_else(|| "HEAD".into(), |h| format!("HEAD@{h}"))
        });
    (branch, head)
}

pub fn open_repo(path: &Path) -> Result<Repository> {
    let answer = git(path, &["rev-parse", "--show-toplevel"])?;
    let top = path_arg(&name(answer.strip_suffix(b"\n").unwrap_or(&answer)))?;
    #[cfg(windows)]
    let root: PathBuf = PathBuf::from(top).components().collect();
    #[cfg(not(windows))]
    let root = fs::canonicalize(top).map_err(|e| e.to_string())?;
    let mut refs = BTreeMap::new();
    let mut advertised = BTreeMap::new();
    let branches = git(
        &root,
        &[
            "for-each-ref",
            "--format=%(refname)%00%(objectname)%00%(symref)",
            "refs/heads",
            "refs/remotes",
        ],
    )?;
    for line in branches.split(|&b| b == b'\n').filter(|v| !v.is_empty()) {
        let fields: Vec<_> = line.split(|&b| b == 0).collect();
        let [r, h, s] = fields.as_slice() else {
            return Err("Invalid branch data from Git.".into());
        };
        let r = name(r);
        if s.is_empty() {
            refs.insert(r, name(h));
        } else if r.starts_with("refs/remotes/") && r.ends_with("/HEAD") {
            let remote = r.trim_end_matches("HEAD");
            let target = name(s);
            if target.starts_with(remote) {
                advertised.insert(remote.to_owned(), target);
            }
        }
    }
    let (checkout, head) = checkout_state(&root);
    let mut branch = if checkout.starts_with("HEAD@") {
        "HEAD".to_owned()
    } else {
        checkout.clone()
    };
    if let Some(h) = head.as_ref() {
        refs.insert(branch.clone(), h.clone());
    } else if let Some(first) = refs.keys().next() {
        branch = first.clone();
    }
    let has_refs = !refs.is_empty();
    refs.insert(
        EMPTY.into(),
        git_text(&root, &["hash-object", "-t", "tree", "--stdin"])?,
    );
    let mut candidates = Vec::new();
    let mut remotes: Vec<_> = advertised.into_iter().collect();
    remotes.sort_by_key(|(r, _)| (r != "refs/remotes/origin/", r.clone()));
    for (remote, target) in remotes {
        if let Some(oid) = refs.get(&target) {
            let local = format!("refs/heads/{}", &target[remote.len()..]);
            candidates.push(if refs.get(&local) == Some(oid) {
                local
            } else {
                target
            });
        }
    }
    candidates.extend(
        [
            "refs/heads/main",
            "refs/heads/master",
            "refs/heads/trunk",
            "refs/heads/develop",
            "refs/remotes/origin/main",
            "refs/remotes/origin/master",
            "refs/remotes/origin/trunk",
        ]
        .map(str::to_owned),
    );
    let default_branch = candidates.into_iter().find(|r| refs.contains_key(r));
    if let Some(head) = &head {
        if let Ok(parent) = git_text(&root, &["rev-parse", "--verify", &format!("{head}^")]) {
            refs.insert("HEAD^".into(), parent);
        }
    }
    let mut initial = Vec::new();
    if has_refs {
        let base = default_branch
            .as_deref()
            .filter(|&r| r != branch)
            .unwrap_or(
                if refs.contains_key("HEAD^") && head.as_ref() == refs.get(&branch) {
                    "HEAD^"
                } else {
                    EMPTY
                },
            );
        initial = vec![base.into(), branch];
    }
    Ok(Repository {
        root,
        refs,
        initial,
        default_branch,
        checkout,
    })
}

fn revision<'a>(repo: &'a Repository, r: &str) -> Result<&'a str> {
    repo.refs
        .get(r)
        .map(String::as_str)
        .ok_or_else(|| format!("Unknown branch {r}. Refresh the repository."))
}

pub fn discover_stack(
    repo: &Repository,
    base: &str,
    branch: &str,
) -> Result<(Vec<String>, Vec<String>)> {
    let base_oid = revision(repo, base)?;
    if branch == EMPTY {
        return Ok((vec![base.into()], vec![]));
    }
    let start = revision(repo, branch)?;
    let mut names = BTreeMap::new();
    for (r, h) in &repo.refs {
        if r.starts_with("refs/heads/") || r.starts_with("refs/remotes/") {
            names.entry(h.clone()).or_insert_with(|| r.clone());
        }
    }
    names.insert(start.into(), branch.into());
    let mut cache = HashMap::new();
    let mut tips = |filter: String| -> Result<BTreeSet<String>> {
        if let Some(found) = cache.get(&filter) {
            return Ok(BTreeSet::clone(found));
        }
        let data = git_text(
            &repo.root,
            &[
                "for-each-ref",
                &filter,
                "--format=%(objectname)",
                "refs/heads",
                "refs/remotes",
            ],
        )?;
        let found: BTreeSet<_> = data
            .lines()
            .filter(|v| names.contains_key(*v))
            .map(str::to_owned)
            .collect();
        cache.insert(filter, found.clone());
        Ok(found)
    };
    let excluded = if base.starts_with("refs/") {
        tips(format!("--merged={base_oid}"))?
    } else {
        BTreeSet::new()
    };
    if start != base_oid && excluded.contains(start) {
        return Ok((vec![base.into(), branch.into()], vec![]));
    }
    let mut parents = &tips(format!("--merged={start}"))? - &excluded;
    let mut descendants = tips(format!("--contains={start}"))?;
    parents.remove(start);
    descendants.remove(start);
    let mut before = Vec::new();
    let mut forks = Vec::new();
    while !parents.is_empty() {
        let mut nearest = parents.clone();
        for tip in &parents {
            for pred in tips(format!("--merged={tip}"))? {
                if pred != *tip {
                    nearest.remove(&pred);
                }
            }
        }
        if nearest.len() != 1 {
            forks.extend(nearest.iter().map(|id| names[id].clone()));
            break;
        }
        let tip = nearest.pop_first().unwrap();
        before.push(names[&tip].clone());
        parents = &parents & &tips(format!("--merged={tip}"))?;
        parents.remove(&tip);
    }
    let mut after = Vec::new();
    while !descendants.is_empty() {
        let mut children = Vec::new();
        for tip in &descendants {
            let parents = tips(format!("--merged={tip}"))?;
            if !parents.intersection(&descendants).any(|p| p != tip) {
                children.push(tip.clone());
            }
        }
        if children.len() != 1 {
            forks.extend(children.iter().map(|id| names[id].clone()));
            break;
        }
        let tip = &children[0];
        after.push(names[tip].clone());
        descendants = &descendants & &tips(format!("--contains={tip}"))?;
        descendants.remove(tip);
    }
    let mut stack = Vec::new();
    if base.starts_with("refs/") || (before.is_empty() && after.is_empty()) {
        stack.push(base.into());
    }
    stack.extend(before.into_iter().rev());
    if stack.last().map(String::as_str) != Some(branch) {
        stack.push(branch.into());
    }
    stack.extend(after);
    forks.sort();
    Ok((stack, forks))
}

pub fn compare(repo: &Repository, left: &str, right: &str) -> Result<Comparison> {
    if right == WORKTREE {
        return working_tree(repo, left, None);
    }
    let tip = revision(repo, left)?;
    let head = revision(repo, right)?;
    let base = if left == EMPTY {
        tip.to_string()
    } else {
        git_text(&repo.root, &["merge-base", tip, head]).map_err(|_| {
            "These branches have no common ancestor. Choose another base or use Empty tree."
        })?
    };
    compare_trees(repo, left, right, tip, &base, head)
}

pub fn compare_trees(
    repo: &Repository,
    left: &str,
    right: &str,
    tip: &str,
    base: &str,
    head: &str,
) -> Result<Comparison> {
    if !valid_oid(base) || !valid_oid(head) {
        return Err("Invalid Git object ID.".into());
    }
    let data = git(
        &repo.root,
        &[
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--find-renames",
            "--ignore-submodules=none",
            "--raw",
            "--no-abbrev",
            "--numstat",
            "-z",
            base,
            head,
            "--",
        ],
    )?;
    Ok(Comparison {
        left: left.into(),
        right: right.into(),
        left_tip: tip.into(),
        base: base.into(),
        head: head.into(),
        files: parse_changes(&data)?,
    })
}

fn valid_oid(oid: &str) -> bool {
    matches!(oid.len(), 40 | 64) && oid.bytes().all(|b| b.is_ascii_hexdigit())
}

fn parse_changes(data: &[u8]) -> Result<Vec<Change>> {
    let bad = "Git returned incomplete file summary data. Refresh the review.";
    let mut it = data.split(|&b| b == 0).peekable();
    let mut files = Vec::new();
    while it.peek().is_some_and(|p| p.starts_with(b":")) {
        let meta = std::str::from_utf8(&it.next().unwrap()[1..]).map_err(|_| bad)?;
        let fields: Vec<_> = meta.split_ascii_whitespace().collect();
        let [old_mode, mode, old_oid, oid, status] = fields.as_slice() else {
            return Err(bad.into());
        };
        let status = status.chars().next().ok_or(bad)?.to_string();
        let old = name(it.next().ok_or(bad)?);
        let path = if status == "R" || status == "C" {
            name(it.next().ok_or(bad)?)
        } else {
            old.clone()
        };
        files.push(Change {
            status,
            old,
            path,
            added: None,
            removed: None,
            old_mode: old_mode.to_string(),
            mode: mode.to_string(),
            old_oid: old_oid.to_string(),
            oid: oid.to_string(),
            group: String::new(),
            local_sections: vec![],
        });
    }
    let mut counts = HashMap::new();
    while let Some(entry) = it.next() {
        if entry.is_empty() {
            break;
        }
        let mut fields = entry.splitn(3, |&b| b == b'\t');
        let a = fields.next().ok_or(bad)?;
        let b = fields.next().ok_or(bad)?;
        let mut path = fields.next().ok_or(bad)?;
        if path.is_empty() {
            it.next().ok_or(bad)?;
            path = it.next().ok_or(bad)?;
        }
        let number = |n: &[u8]| {
            if n == b"-" {
                Ok(None)
            } else {
                std::str::from_utf8(n)
                    .ok()
                    .and_then(|s| s.parse::<usize>().ok())
                    .map(Some)
                    .ok_or(bad)
            }
        };
        counts.insert(name(path), (number(a)?, number(b)?));
    }
    for f in &mut files {
        (f.added, f.removed) = counts.remove(&f.path).ok_or(bad)?;
    }
    Ok(files)
}

const PATCH_ARGS: &[&str] = &[
    "-c",
    "core.quotePath=true",
    "-c",
    "diff.suppressBlankEmpty=false",
    "diff",
    "--patch",
    "--full-index",
    "--no-color",
    "--no-ext-diff",
    "--no-textconv",
    "--find-renames",
    "--unified=3",
    "--ignore-submodules=none",
    "--submodule=short",
    "--no-relative",
    "--output-indicator-new=+",
    "--output-indicator-old=-",
    "--output-indicator-context= ",
];

fn diff_patch(repo: &Repository, args: &[&OsStr], local: bool, no_index: bool) -> Result<Vec<u8>> {
    let mut cmd: Vec<&OsStr> = PATCH_ARGS.iter().map(OsStr::new).collect();
    if local {
        cmd.extend(["--raw", "--numstat", "--no-abbrev", "-z"].map(OsStr::new));
    }
    cmd.extend_from_slice(args);
    run_git(&repo.root, &cmd, no_index)
}

fn sections(data: &[u8]) -> Vec<&[u8]> {
    let mut offsets = Vec::new();
    let mut pos = 0;
    for line in data.split_inclusive(|&b| b == b'\n') {
        if line.starts_with(b"diff --git ") {
            offsets.push(pos);
        }
        pos += line.len();
    }
    offsets.push(data.len());
    offsets.windows(2).map(|p| &data[p[0]..p[1]]).collect()
}

fn local_changes(
    repo: &Repository,
    group: &str,
    args: &[&OsStr],
    no_index: bool,
) -> Result<Vec<Change>> {
    let data = diff_patch(repo, args, true, no_index)?;
    if data.is_empty() {
        return Ok(vec![]);
    }
    let boundary = data
        .windows(2)
        .position(|v| v == b"\0\0")
        .ok_or("Git returned an incomplete working tree diff.")?;
    let chunks = sections(&data[boundary + 2..]);
    let mut chunks = chunks.into_iter();
    let mut files = parse_changes(&data[..=boundary])?;
    for f in &mut files {
        f.group = group.into();
        for _ in 0..if f.status == "T" { 2 } else { 1 } {
            f.local_sections.push(
                chunks
                    .next()
                    .ok_or("Git returned an incomplete working tree diff.")?
                    .to_vec(),
            );
        }
        if f.oid.bytes().all(|b| b == b'0') {
            f.oid = f.old_oid.clone();
        }
        if let Some(index) = f.local_sections.last().and_then(|c| {
            c.split(|&b| b == b'\n')
                .find_map(|l| l.strip_prefix(b"index "))
        }) {
            if let Some(oid) = String::from_utf8_lossy(index)
                .split_ascii_whitespace()
                .next()
                .and_then(|s| s.split_once(".."))
                .map(|(_, n)| n)
            {
                if valid_oid(oid) {
                    f.oid = oid.to_owned();
                }
            }
        }
    }
    if chunks.next().is_some() {
        return Err("Git returned inconsistent working tree changes.".into());
    }
    Ok(files)
}

pub fn working_tree(
    repo: &Repository,
    checkout: &str,
    untracked_paths: Option<&HashSet<String>>,
) -> Result<Comparison> {
    if checkout != repo.checkout {
        return Err("The checked-out branch changed. Refresh the working tree.".into());
    }
    let head = repo.refs.get(if checkout.starts_with("HEAD@") {
        "HEAD"
    } else {
        checkout
    });
    let base = head.unwrap_or(&repo.refs[EMPTY]);
    let index_data = git(&repo.root, &["rev-parse", "--git-path", "index"])?;
    let index_path = working_path(
        &repo.root,
        &name(index_data.strip_suffix(b"\n").unwrap_or(&index_data)),
    )?;
    let index_state = || -> Result<_> {
        match fs::metadata(&index_path) {
            Ok(m) => {
                #[cfg(unix)]
                let identity = {
                    use std::os::unix::fs::MetadataExt;
                    m.ino()
                };
                #[cfg(not(unix))]
                let identity = 0_u64;
                Ok(Some((
                    identity,
                    m.len(),
                    m.modified().map_err(|e| e.to_string())?,
                )))
            }
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(None),
            Err(e) => Err(e.to_string()),
        }
    };
    let initial_index = index_state()?;
    let mut files = local_changes(
        repo,
        "Staged",
        &["--cached", "--diff-filter=u", base, "--"].map(OsStr::new),
        false,
    )?;
    let mut unstaged = local_changes(
        repo,
        "Unstaged",
        &["--ours", "--diff-filter=u", "--"].map(OsStr::new),
        false,
    )?;
    // Unmerged paths have up to three stages. Use stage 2 for the old side.
    let unmerged = git(&repo.root, &["ls-files", "--unmerged", "-z"])?;
    let mut conflicts = BTreeMap::new();
    for entry in unmerged.split(|&b| b == 0).filter(|p| !p.is_empty()) {
        let tab = entry
            .iter()
            .position(|&c| c == b'\t')
            .ok_or("Invalid unmerged index entry.")?;
        let data =
            std::str::from_utf8(&entry[..tab]).map_err(|_| "Invalid unmerged index entry.")?;
        let fields: Vec<_> = data.split_ascii_whitespace().collect();
        let [mode, oid, stage] = fields.as_slice() else {
            return Err("Invalid unmerged index entry.".into());
        };
        let info = conflicts
            .entry(name(&entry[tab + 1..]))
            .or_insert_with(|| ("000000".into(), "0".repeat(base.len())));
        if *stage == "2" {
            *info = (mode.to_string(), oid.to_string());
        }
    }
    for f in &mut unstaged {
        if conflicts.remove(&f.path).is_some() {
            f.status = "U".into();
        }
    }
    files.extend(unstaged);
    for (path, (mode, oid)) in conflicts {
        let arg = path_arg(&path)?;
        let mut remaining = local_changes(
            repo,
            "Unstaged",
            &[base.as_ref(), "--".as_ref(), &arg],
            false,
        )?;
        if remaining.is_empty() {
            files.push(Change {
                status: "U".into(),
                old: path.clone(),
                path,
                added: Some(0),
                removed: Some(0),
                old_mode: mode.clone(),
                mode,
                old_oid: oid.clone(),
                oid,
                group: "Unstaged".into(),
                local_sections: vec![],
            });
        } else {
            for f in &mut remaining {
                f.status = "U".into();
            }
            files.extend(remaining);
        }
    }
    if untracked_paths.is_none_or(|p| !p.is_empty()) {
        let others = git(
            &repo.root,
            &["ls-files", "--others", "--exclude-standard", "-z"],
        )?;
        for raw in others.split(|&b| b == 0).filter(|p| !p.is_empty()) {
            let path = name(raw.strip_suffix(b"/").unwrap_or(raw));
            if untracked_paths.is_some_and(|p| !p.contains(&path)) {
                continue;
            }
            let arg = path_arg(&path)?;
            let target = repo.root.join(&arg);
            let kind = fs::symlink_metadata(&target)
                .map_err(|e| e.to_string())?
                .file_type();
            if kind.is_dir() && target.join(".git").exists() {
                let oid = git_text(&target, &["rev-parse", "--verify", "HEAD"])
                    .unwrap_or_else(|_| "0".repeat(base.len()));
                files.push(Change {
                    status: "A".into(),
                    old: path.clone(),
                    path,
                    added: Some(0),
                    removed: Some(0),
                    old_mode: "000000".into(),
                    mode: "160000".into(),
                    old_oid: "0".repeat(oid.len()),
                    oid,
                    group: "Untracked".into(),
                    local_sections: vec![],
                });
            } else if kind.is_symlink() || kind.is_file() {
                // Pass a regular copy of link text. Git's --no-index can follow a
                // link to a directory or FIFO when the link is a command argument.
                let temp;
                let source = if kind.is_symlink() {
                    temp = tempfile::tempdir().map_err(|e| e.to_string())?;
                    let target_name = fs::read_link(&target).map_err(|e| e.to_string())?;
                    let source = temp.path().join("link");
                    fs::File::create(&source)
                        .and_then(|mut f| f.write_all(target_name.as_os_str().as_encoded_bytes()))
                        .map_err(|e| e.to_string())?;
                    source
                } else {
                    Path::new(".").join(&arg)
                };
                let mut added = local_changes(
                    repo,
                    "Untracked",
                    &[
                        "--no-index".as_ref(),
                        "--".as_ref(),
                        "/dev/null".as_ref(),
                        source.as_os_str(),
                    ],
                    true,
                )?;
                for f in &mut added {
                    f.old = path.clone();
                    f.path = path.clone();
                    if kind.is_symlink() {
                        f.mode = "120000".into();
                    }
                }
                files.extend(added);
            }
        }
    }
    if checkout_state(&repo.root) != (checkout.to_string(), head.cloned())
        || index_state()? != initial_index
    {
        return Err("The checkout or index changed. Refresh to review its current changes.".into());
    }
    let mut digest = Sha256::new();
    for f in &files {
        let old = path_arg(&f.old)?;
        let path = path_arg(&f.path)?;
        for value in [
            f.group.as_bytes(),
            f.status.as_bytes(),
            old.as_encoded_bytes(),
            path.as_encoded_bytes(),
            f.old_mode.as_bytes(),
            f.mode.as_bytes(),
            f.old_oid.as_bytes(),
            f.oid.as_bytes(),
        ] {
            digest.update(value);
            digest.update([0]);
        }
    }
    Ok(Comparison {
        left: checkout.into(),
        right: WORKTREE.into(),
        left_tip: base.clone(),
        base: base.clone(),
        head: format!("{:x}", digest.finalize()),
        files,
    })
}

fn with_patch_sections<T>(
    repo: &Repository,
    c: &Comparison,
    file: &Change,
    read: impl FnOnce(&[&[u8]]) -> T,
) -> Result<T> {
    let data;
    let mut chunks: Vec<&[u8]> = if file.group.is_empty() {
        let path = path_arg(&file.path)?;
        let old = path_arg(&file.old)?;
        let mut args = vec![c.base.as_ref(), c.head.as_ref(), "--".as_ref()];
        if old != path {
            args.push(old.as_os_str());
        }
        args.push(path.as_os_str());
        data = diff_patch(repo, &args, false, false)?;
        sections(&data)
    } else {
        file.local_sections.iter().map(Vec::as_slice).collect()
    };
    if file.group.is_empty() && chunks.len() > 1 && file.status != "T" {
        let key = format!("index {}..{}", file.old_oid, file.oid);
        chunks.retain(|s| {
            s.split(|&b| b == b'\n').any(|line| {
                line == key.as_bytes()
                    || line
                        .strip_prefix(key.as_bytes())
                        .is_some_and(|s| s.starts_with(b" "))
            })
        });
    }
    Ok(read(&chunks))
}

pub fn patch(repo: &Repository, c: &Comparison, file: &Change) -> Result<Vec<Line>> {
    with_patch_sections(repo, c, file, |chunks| {
        let mut lines = Vec::new();
        patch_data::visit(chunks, |kind, text, old, new, hunk| {
            lines.push(Line {
                kind: kind.into(),
                text: text.into(),
                old: matches!(kind, "-" | " ").then_some(old),
                new: matches!(kind, "+" | " ").then_some(new),
                hunk,
            });
        });
        lines
    })
}

pub fn display_patch(
    repo: &Repository,
    c: &Comparison,
    file: &Change,
) -> Result<(String, Vec<[usize; 2]>)> {
    with_patch_sections(repo, c, file, patch_data::encode)
}

pub fn commits(repo: &Repository, c: &Comparison) -> Result<Vec<Commit>> {
    if c.right == WORKTREE {
        return Ok(vec![]);
    }
    let exclude = format!("^{}", c.base);
    let mut args = vec![
        "log",
        "--no-show-signature",
        "-z",
        "--format=%H%x00%an%x00%as%x00%s",
        &c.head,
    ];
    if c.left != EMPTY {
        args.push(&exclude);
    }
    args.push("--");
    let data = git(&repo.root, &args)?;
    let text = String::from_utf8_lossy(&data);
    let fields: Vec<_> = text.split_terminator('\0').collect();
    if fields.len() % 4 != 0 {
        return Err("Git returned incomplete commit information.".into());
    }
    Ok(fields
        .chunks_exact(4)
        .map(|v| Commit {
            sha: v[0].into(),
            author: v[1].into(),
            date: v[2].into(),
            subject: v[3].into(),
        })
        .collect())
}

pub fn commit_details(repo: &Repository, sha: &str) -> Result<String> {
    if !valid_oid(sha) {
        return Err("Choose a commit from the comparison.".into());
    }
    git_text(
        &repo.root,
        &[
            "show",
            "--format=fuller",
            "--stat",
            "--date=iso",
            "--no-color",
            "--no-ext-diff",
            "--no-textconv",
            "--no-show-signature",
            sha,
            "--",
        ],
    )
}

#[cfg(test)]
mod tests {
    include!("git_tests.rs");

    #[test]
    fn display_patch_preserves_git_rows_and_frozen_working_tree() {
        let dir = history();
        write(&dir, "code", b"\r\n\xc3\xa9\n\xff");
        let repo = open_repo(dir.path()).unwrap();
        let c = work(&repo);
        let f = file(&c, "Untracked", "code");
        write(&dir, "code", b"changed after snapshot\n");
        let (rows, starts) = display_patch(&repo, &c, f).unwrap();
        assert_eq!(starts, [[0, 1]]);
        assert_eq!(
            rows,
            "@@ -0,0 +1,3 @@\n+\n+é\n+�\n\\ No newline at end of file\n"
        );
    }
}
