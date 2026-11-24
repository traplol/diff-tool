//! Local Git plumbing for immutable branch and working-tree review snapshots.
mod native;
mod patch_data;
#[cfg(windows)]
mod windows;

use serde::Serialize;
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::ffi::{OsStr, OsString};
use std::fs;
use std::io::{self, BufRead, Read};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError};
use std::time::Duration;

pub const EMPTY: &str = ":empty:";
pub const WORKTREE: &str = ":worktree:";
type Result<T> = std::result::Result<T, String>;

#[cfg(windows)]
pub(crate) fn configure_native() -> Option<tempfile::TempDir> {
    native::configure().ok()
}

#[derive(Clone, Debug, Serialize)]
pub struct Repository {
    #[serde(serialize_with = "serialize_root")]
    pub root: PathBuf,
    pub refs: BTreeMap<String, String>,
    pub initial: Vec<String>,
    pub default_branch: Option<String>,
    pub checkout: String,
    #[serde(skip)]
    native: Option<native::Handle>,
}

impl Repository {
    fn native(&self) -> Option<native::Access<'_>> {
        self.native.as_ref()?.access(&self.root)
    }
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

impl Comparison {
    pub fn branch_tip(&self) -> &str {
        if self.right == WORKTREE {
            &self.base
        } else {
            &self.head
        }
    }
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
pub(crate) fn command(root: &Path) -> Result<Command> {
    windows::command(root)
}

#[cfg(not(windows))]
pub(crate) fn command(root: &Path) -> Result<Command> {
    let mut cmd = Command::new("git");
    cmd.args(["--no-pager", "--literal-pathspecs", "-C"])
        .arg(root)
        .env("GIT_NO_LAZY_FETCH", "1")
        .env("GIT_TERMINAL_PROMPT", "0")
        .env("GIT_OPTIONAL_LOCKS", "0")
        .stdin(Stdio::null());
    Ok(cmd)
}

fn run_git<S: AsRef<OsStr>>(root: &Path, args: &[S], diff_exit: bool) -> Result<Vec<u8>> {
    let output = command(root)?
        .args(args)
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
    if let Ok(state) = native::open(root).and_then(|repo| native::checkout(&repo)) {
        return state;
    }
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
    if let Ok(repo) = native::open(path) {
        if let (Some(root), Ok(metadata)) = (repo.workdir(), native::metadata(&repo)) {
            #[cfg(unix)]
            let root = fs::canonicalize(root).map_err(|e| e.to_string())?;
            #[cfg(windows)]
            let root: PathBuf = root.components().collect();
            let native = native::Handle::new(root.clone(), repo);
            return Ok(finish_repository(root, metadata, Some(native)));
        }
    }
    let answer = git(path, &["rev-parse", "--show-toplevel"])?;
    let top = PathBuf::from(path_arg(&name(
        answer.strip_suffix(b"\n").unwrap_or(&answer),
    ))?);
    #[cfg(windows)]
    let root = match windows::WslCheckout::from_path(path) {
        Some(wsl) => wsl.host_path(&top)?,
        None => top.components().collect(),
    };
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
    let empty = git_text(&root, &["hash-object", "-t", "tree", "--stdin"])?;
    let parent = head
        .as_ref()
        .and_then(|head| git_text(&root, &["rev-parse", "--verify", &format!("{head}^")]).ok());
    Ok(finish_repository(
        root,
        native::Metadata {
            refs,
            remotes: advertised,
            checkout,
            head,
            parent,
            empty,
        },
        None,
    ))
}

fn finish_repository(
    root: PathBuf,
    metadata: native::Metadata,
    native: Option<native::Handle>,
) -> Repository {
    let native::Metadata {
        mut refs,
        remotes: advertised,
        checkout,
        head,
        parent,
        empty,
    } = metadata;
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
    refs.insert(EMPTY.into(), empty);
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
    if let Some(parent) = parent {
        refs.insert("HEAD^".into(), parent);
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
    Repository {
        root,
        refs,
        initial,
        default_branch,
        checkout,
        native,
    }
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
    let native_repo = repo.native();
    let mut cache = HashMap::new();
    let mut tips = |filter: String| -> Result<BTreeSet<String>> {
        if let Some(found) = cache.get(&filter) {
            return Ok(BTreeSet::clone(found));
        }
        if let Some(repo) = &native_repo {
            if let Ok(found) = native::tips(repo, &filter, &names) {
                cache.insert(filter, found.clone());
                return Ok(found);
            }
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
        merge_base(repo, tip, head).map_err(|_| {
            "These branches have no common ancestor. Choose another base or use Empty tree."
        })?
    };
    compare_trees(repo, left, right, tip, &base, head)
}

pub fn merge_base(repo: &Repository, a: &str, b: &str) -> Result<String> {
    if let Some(base) = repo
        .native()
        .and_then(|repo| native::merge_base(&repo, a, b).ok())
    {
        return Ok(base);
    }
    git_text(&repo.root, &["merge-base", "--", a, b])
}

pub fn descends(repo: &Repository, origin: &str, head: &str) -> Result<bool> {
    if let Some(result) = repo
        .native()
        .and_then(|repo| native::descends(&repo, origin, head).ok())
    {
        return Ok(result);
    }
    let range = format!("{origin}..{head}");
    Ok(!git(
        &repo.root,
        &["rev-list", "--ancestry-path", "--max-count=1", &range, "--"],
    )?
    .is_empty())
}

pub fn blob_bytes(root: &Path, object: &str) -> Result<Vec<u8>> {
    if let Ok(data) = native::open(root).and_then(|repo| native::blob(&repo, object)) {
        return Ok(data);
    }
    git(root, &["cat-file", "blob", object])
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
    let files = match repo
        .native()
        .filter(|repo| native::supports_diff(repo))
        .and_then(|native| {
            native::branch_changes(&native, base, head, native::empty_oid(repo)).ok()
        }) {
        Some(files) => files,
        None => {
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
            parse_changes(&data, false)?
        }
    };
    Ok(Comparison {
        left: left.into(),
        right: right.into(),
        left_tip: tip.into(),
        base: base.into(),
        head: head.into(),
        files,
    })
}

fn valid_oid(oid: &str) -> bool {
    matches!(oid.len(), 40 | 64) && oid.bytes().all(|b| b.is_ascii_hexdigit())
}

fn parse_raw_changes<'a>(
    it: &mut std::iter::Peekable<impl Iterator<Item = &'a [u8]>>,
) -> Result<Vec<Change>> {
    let bad = "Git returned incomplete file summary data. Refresh the review.";
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
    Ok(files)
}

fn parse_changes(data: &[u8], skip_stale_stats: bool) -> Result<Vec<Change>> {
    let bad = "Git returned incomplete file summary data. Refresh the review.";
    let mut it = data.split(|&b| b == 0).peekable();
    let files = parse_raw_changes(&mut it)?;
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
    files
        .into_iter()
        .filter_map(|mut f| {
            if let Some(count) = counts.remove(&f.path) {
                (f.added, f.removed) = count;
                return Some(Ok(f));
            }
            // With index auto-refresh disabled, Git's raw output can include
            // stat-only changes that its content-based numstat omits.
            if skip_stale_stats
                && f.status == "M"
                && f.old_mode == f.mode
                && f.oid.bytes().all(|b| b == b'0')
            {
                return None;
            }
            Some(Err(bad.into()))
        })
        .collect()
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
    let mut cmd = Vec::new();
    if local && !no_index {
        // Git diff can refresh the real index even with GIT_OPTIONAL_LOCKS=0.
        cmd.extend(["-c", "diff.autoRefreshIndex=false"].map(OsStr::new));
    }
    cmd.extend(PATCH_ARGS.iter().map(OsStr::new));
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
    let mut files = parse_changes(&data[..=boundary], group == "Unstaged")?;
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
    let native_repo = repo.native().filter(|repo| native::supports_diff(repo));
    let native_index = native_repo
        .as_ref()
        .and_then(|repo| repo.index().ok())
        .and_then(|index| index.path().map(Path::to_path_buf));
    let index_path = if let Some(path) = native_index {
        path
    } else {
        let index_data = git(&repo.root, &["rev-parse", "--git-path", "index"])?;
        let index = PathBuf::from(path_arg(&name(
            index_data.strip_suffix(b"\n").unwrap_or(&index_data),
        ))?);
        #[cfg(windows)]
        let index = match windows::WslCheckout::from_path(&repo.root) {
            Some(wsl) if index_data.starts_with(b"/") => wsl.host_path(&index)?,
            _ => index,
        };
        repo.root.join(index)
    };
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
    let files = if let Some(files) = native_repo.as_ref().and_then(|native| {
        native::working_changes(native, base, native::empty_oid(repo), untracked_paths).ok()
    }) {
        files
    } else {
        working_changes_cli(repo, base, untracked_paths)?
    };
    let current = native_repo
        .as_ref()
        .and_then(|repo| native::checkout(repo).ok())
        .unwrap_or_else(|| checkout_state(&repo.root));
    if current != (checkout.to_string(), head.cloned()) || index_state()? != initial_index {
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

fn working_changes_cli(
    repo: &Repository,
    base: &str,
    untracked_paths: Option<&HashSet<String>>,
) -> Result<Vec<Change>> {
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
                    #[cfg(windows)]
                    let wsl = windows::WslCheckout::from_path(&repo.root);
                    #[cfg(windows)]
                    let scratch = if let Some(wsl) = &wsl {
                        tempfile::tempdir_in(wsl.host_path(Path::new("/tmp"))?)
                    } else {
                        tempfile::tempdir()
                    };
                    #[cfg(not(windows))]
                    let scratch = tempfile::tempdir();
                    temp = scratch.map_err(|e| e.to_string())?;
                    let native_link = || {
                        fs::read_link(&target)
                            .map(|path| path.as_os_str().as_encoded_bytes().to_vec())
                            .map_err(|e| e.to_string())
                    };
                    #[cfg(windows)]
                    let link = match &wsl {
                        Some(wsl) => wsl.link_target(&arg)?,
                        None => native_link()?,
                    };
                    #[cfg(not(windows))]
                    let link = native_link()?;
                    let source = temp.path().join("link");
                    fs::write(&source, link).map_err(|e| e.to_string())?;
                    #[cfg(windows)]
                    if wsl.is_some() {
                        windows::WslCheckout::from_path(&source)
                            .ok_or("Could not resolve the WSL temporary file.")?
                            .directory
                    } else {
                        source.into_os_string()
                    }
                    #[cfg(not(windows))]
                    source.into_os_string()
                } else {
                    let mut source = OsString::from("./");
                    source.push(&arg);
                    source
                };
                let mut added = local_changes(
                    repo,
                    "Untracked",
                    &[
                        "--no-index".as_ref(),
                        "--".as_ref(),
                        "/dev/null".as_ref(),
                        &source,
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
    Ok(files)
}

fn with_patch_sections<T>(
    repo: &Repository,
    c: &Comparison,
    file: &Change,
    read: impl FnOnce(&[&[u8]]) -> T,
) -> Result<T> {
    if file.group.is_empty() {
        if let Some(data) = repo
            .native()
            .filter(|repo| native::supports_diff(repo))
            .and_then(|native| {
                native::branch_patch(&native, &c.base, &c.head, native::empty_oid(repo), file).ok()
            })
        {
            return Ok(read(&[&data]));
        }
    }
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

fn patch_lines(chunks: &[&[u8]]) -> Vec<Line> {
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
}

pub fn patch(repo: &Repository, c: &Comparison, file: &Change) -> Result<Vec<Line>> {
    with_patch_sections(repo, c, file, patch_lines)
}

struct PatchReader<'a> {
    receiver: Receiver<io::Result<Vec<u8>>>,
    bytes: Vec<u8>,
    offset: usize,
    cancelled: &'a dyn Fn() -> bool,
}

impl BufRead for PatchReader<'_> {
    fn fill_buf(&mut self) -> io::Result<&[u8]> {
        loop {
            if (self.cancelled)() {
                return Err(io::Error::other("Search superseded."));
            }
            if self.offset < self.bytes.len() {
                return Ok(&self.bytes[self.offset..]);
            }
            match self.receiver.recv_timeout(Duration::from_millis(20)) {
                Ok(bytes) => {
                    self.bytes = bytes?;
                    self.offset = 0;
                }
                Err(RecvTimeoutError::Timeout) => {}
                Err(RecvTimeoutError::Disconnected) => return Ok(&[]),
            }
        }
    }

    fn consume(&mut self, amount: usize) {
        self.offset = (self.offset + amount).min(self.bytes.len());
    }
}

impl Read for PatchReader<'_> {
    fn read(&mut self, output: &mut [u8]) -> io::Result<usize> {
        let bytes = self.fill_buf()?;
        let count = bytes.len().min(output.len());
        output[..count].copy_from_slice(&bytes[..count]);
        self.consume(count);
        Ok(count)
    }
}

fn visit_patch_line(
    file: &Change,
    row: &mut usize,
    decoder: &mut patch_data::Decoder,
    bytes: &[u8],
    visit: &mut impl FnMut(&Change, usize, &Line) -> Result<bool>,
) -> Result<bool> {
    let mut result = Ok(true);
    decoder.line(
        &String::from_utf8_lossy(bytes),
        |kind, text, old, new, hunk| {
            result = visit(
                file,
                *row,
                &Line {
                    kind: kind.into(),
                    text: text.into(),
                    old: matches!(kind, "-" | " ").then_some(old),
                    new: matches!(kind, "+" | " ").then_some(new),
                    hunk,
                },
            );
            *row += 1;
        },
    );
    result
}

fn read_branch_patches(
    output: &mut impl BufRead,
    c: &Comparison,
    visit: &mut impl FnMut(&Change, usize, &Line) -> Result<bool>,
) -> Result<bool> {
    let bad = "Git returned inconsistent review patches. Refresh the review.";
    let mut header = Vec::new();
    loop {
        let start = header.len();
        if output
            .read_until(0, &mut header)
            .map_err(|e| e.to_string())?
            == 0
        {
            return Err(bad.into());
        }
        if header.len() == start + 1 {
            break;
        }
    }
    let files = parse_raw_changes(&mut header[..header.len() - 1].split(|&b| b == 0).peekable())?;
    let mut expected: HashMap<_, _> = c
        .files
        .iter()
        .map(|file| ((file.old.as_str(), file.path.as_str()), file))
        .collect();
    let mut ordered = Vec::new();
    for file in &files {
        let original = expected
            .remove(&(file.old.as_str(), file.path.as_str()))
            .ok_or(bad)?;
        if file.status != original.status
            || file.old_mode != original.old_mode
            || file.mode != original.mode
            || file.old_oid != original.old_oid
            || file.oid != original.oid
        {
            return Err(bad.into());
        }
        ordered.push(original);
    }
    if !expected.is_empty() || ordered.len() != c.files.len() {
        return Err(bad.into());
    }
    drop(files);
    drop(header);
    let mut next = 0;
    let mut remaining = 0;
    let mut row = 0;
    let mut decoder = patch_data::Decoder::default();
    let mut line = Vec::new();
    loop {
        line.clear();
        if output
            .read_until(b'\n', &mut line)
            .map_err(|e| e.to_string())?
            == 0
        {
            break;
        }
        let bytes = line.strip_suffix(b"\n").unwrap_or(&line);
        if bytes.starts_with(b"diff --git ") {
            if remaining == 0 {
                let file = ordered.get(next).ok_or(bad)?;
                next += 1;
                remaining = if file.status == "T" { 2 } else { 1 };
                row = 0;
                decoder = patch_data::Decoder::default();
            }
            remaining -= 1;
            decoder.section();
        }
        let file = next
            .checked_sub(1)
            .and_then(|i| ordered.get(i))
            .ok_or(bad)?;
        if file.added.is_some()
            && file.removed.is_some()
            && !visit_patch_line(file, &mut row, &mut decoder, bytes, visit)?
        {
            return Ok(false);
        }
    }
    if next != ordered.len() || remaining != 0 {
        return Err(bad.into());
    }
    Ok(true)
}

// Stream a branch with one Git process. Keep at most a few read buffers and one
// physical line, so an early hit never materializes the rest of a large patch.
// Working-tree sections already belong to the frozen comparison.
pub fn visit_patches(
    repo: &Repository,
    c: &Comparison,
    cancelled: &dyn Fn() -> bool,
    mut visit: impl FnMut(&Change, usize, &Line) -> Result<bool>,
) -> Result<()> {
    if cancelled() {
        return Err("Search superseded.".into());
    }
    if c.files.is_empty() {
        return Ok(());
    }
    if c.right == WORKTREE {
        for file in &c.files {
            if file.added.is_none() || file.removed.is_none() {
                continue;
            }
            let mut decoder = patch_data::Decoder::default();
            let mut row = 0;
            for section in &file.local_sections {
                decoder.section();
                for bytes in section.split(|&b| b == b'\n') {
                    if cancelled() {
                        return Err("Search superseded.".into());
                    }
                    if !visit_patch_line(file, &mut row, &mut decoder, bytes, &mut visit)? {
                        return Ok(());
                    }
                }
            }
        }
        return Ok(());
    }
    if let Some(result) = visit_native_patches(repo, c, cancelled, &mut visit) {
        return result;
    }
    let child = command(&repo.root)?
        .args(PATCH_ARGS)
        .args(["--raw", "--no-abbrev", "-z", &c.base, &c.head, "--"])
        .stdout(Stdio::piped())
        .spawn()
        .map_err(|e| format!("Could not start Git: {e}"))?;
    read_patch_process(child, c, cancelled, &mut visit)
}

fn visit_native_patches(
    repo: &Repository,
    c: &Comparison,
    cancelled: &dyn Fn() -> bool,
    visit: &mut impl FnMut(&Change, usize, &Line) -> Result<bool>,
) -> Option<Result<()>> {
    let native = repo.native().filter(|repo| native::supports_diff(repo))?;
    let diff = native::branch_diff(&native, &c.base, &c.head, native::empty_oid(repo)).ok()?;
    let positions: HashMap<_, _> = diff
        .deltas()
        .enumerate()
        .map(|(index, delta)| {
            let old = delta.old_file();
            let new = delta.new_file();
            (
                (
                    name(old.path_bytes().unwrap_or_default()),
                    name(new.path_bytes().unwrap_or_default()),
                ),
                index,
            )
        })
        .collect();
    let ordered: Option<Vec<_>> = c
        .files
        .iter()
        .map(|file| {
            if file.status == "T" || file.mode == "160000" || file.old_mode == "160000" {
                return None;
            }
            let index = *positions.get(&(file.old.clone(), file.path.clone()))?;
            let delta = diff.get_delta(index)?;
            (delta.old_file().id().to_string() == file.old_oid
                && delta.new_file().id().to_string() == file.oid)
                .then_some((file, index))
        })
        .collect();
    let ordered = ordered?;
    Some((|| {
        for (file, index) in ordered {
            if cancelled() {
                return Err("Search superseded.".into());
            }
            if file.added.is_none() || file.removed.is_none() {
                continue;
            }
            let patch = native::patch_at(&diff, index).map_err(|error| error.to_string())?;
            let mut decoder = patch_data::Decoder::default();
            let mut row = 0;
            for bytes in patch.split(|&byte| byte == b'\n') {
                if cancelled() {
                    return Err("Search superseded.".into());
                }
                if !visit_patch_line(file, &mut row, &mut decoder, bytes, visit)? {
                    return Ok(());
                }
            }
        }
        Ok(())
    })())
}

fn read_patch_process(
    mut child: std::process::Child,
    c: &Comparison,
    cancelled: &dyn Fn() -> bool,
    visit: &mut impl FnMut(&Change, usize, &Line) -> Result<bool>,
) -> Result<()> {
    let mut stdout = child.stdout.take().expect("piped Git patch output");
    std::thread::scope(|scope| {
        let (sender, receiver) = mpsc::sync_channel(2);
        scope.spawn(move || loop {
            let mut bytes = vec![0; 64 * 1024];
            let read = stdout.read(&mut bytes);
            if matches!(read, Ok(0)) {
                break;
            }
            let result = read.map(|count| {
                bytes.truncate(count);
                bytes
            });
            let failed = result.is_err();
            if sender.send(result).is_err() || failed {
                break;
            }
        });
        let mut output = PatchReader {
            receiver,
            bytes: Vec::new(),
            offset: 0,
            cancelled,
        };
        let read = read_branch_patches(&mut output, c, visit);
        drop(output);
        if !matches!(read, Ok(true)) {
            let _ = child.kill();
        }
        let status = child.wait().map_err(|e| e.to_string())?;
        if !read? || status.success() {
            Ok(())
        } else {
            Err("Git could not read review patches.".into())
        }
    })
}

fn blob_lines(repo: &Repository, object: &OsStr) -> Result<Vec<String>> {
    let object = object.to_str().ok_or("Invalid blob ID.")?;
    let data = match repo
        .native()
        .and_then(|repo| native::blob(&repo, object).ok())
    {
        Some(bytes) => bytes,
        None => git(&repo.root, &["cat-file", "blob", object])?,
    };
    text_lines(&data)
}

fn text_lines(data: &[u8]) -> Result<Vec<String>> {
    if data.contains(&0) {
        return Err("This file contains binary data.".into());
    }
    Ok(String::from_utf8_lossy(data)
        .split_terminator('\n')
        .map(|line| line.strip_suffix('\r').unwrap_or(line).to_owned())
        .collect())
}

#[derive(Debug, Serialize)]
#[serde(tag = "kind", rename_all = "lowercase")]
pub enum RevisionFile {
    Text { lines: Vec<String> },
    Binary { bytes: usize },
    Submodule { oid: String },
}

pub fn revision_file(repo: &Repository, revision: &str, path: &str) -> Result<RevisionFile> {
    let path = path_arg(path)?;
    if let Some(native) = repo.native() {
        if let Ok(file) = native::revision_file(&native, revision, Path::new(&path)) {
            return Ok(file);
        }
    }
    let entry = run_git(
        &repo.root,
        &[
            "ls-tree".as_ref(),
            "-z".as_ref(),
            revision.as_ref(),
            "--".as_ref(),
            path.as_os_str(),
        ],
        false,
    )?;
    let header = entry.split(|&b| b == b'\t').next().unwrap_or_default();
    let fields: Vec<_> = header.split(|&b| b == b' ').collect();
    if fields.len() != 3 || !entry.ends_with(&[0]) {
        return Err("This path is no longer available at this revision.".into());
    }
    if fields[0] == b"160000" {
        return Ok(RevisionFile::Submodule {
            oid: String::from_utf8_lossy(fields[2]).into_owned(),
        });
    }
    let mut object = OsString::from(format!("{revision}:"));
    object.push(path);
    let data = run_git(
        &repo.root,
        &["cat-file".as_ref(), "blob".as_ref(), object.as_os_str()],
        false,
    )?;
    if data.contains(&0) {
        Ok(RevisionFile::Binary { bytes: data.len() })
    } else {
        Ok(RevisionFile::Text {
            lines: text_lines(&data)?,
        })
    }
}

pub fn file_contents(repo: &Repository, file: &Change) -> Result<Vec<String>> {
    if file.added.is_none() || file.removed.is_none() {
        return Err("This file contains binary data.".into());
    }
    if file.old_mode == "160000" || file.mode == "160000" {
        return Err("A Git submodule has no file text.".into());
    }
    if file.mode == "000000" {
        return Ok(vec![]);
    }
    if matches!(file.group.as_str(), "" | "Staged") || file.oid == file.old_oid {
        return blob_lines(repo, file.oid.as_ref());
    }
    let old = if file.old_mode == "000000" {
        vec![]
    } else {
        blob_lines(repo, file.old_oid.as_ref())?
    };
    // Git may never have stored the working copy as a blob. Rebuild it
    // from the frozen patch and its immutable index preimage.
    let mismatch = "The patch does not match the saved file contents. Refresh the review.";
    let mut output = Vec::new();
    let mut consumed = 0;
    let chunks: Vec<_> = file.local_sections.iter().map(Vec::as_slice).collect();
    for line in patch_lines(&chunks) {
        let gap = if let Some(number) = line.old {
            number.checked_sub(consumed + 1)
        } else if let Some(number) = line.new {
            number.checked_sub(output.len() + 1)
        } else {
            continue;
        }
        .ok_or(mismatch)?;
        let end = consumed.checked_add(gap).ok_or(mismatch)?;
        output.extend_from_slice(old.get(consumed..end).ok_or(mismatch)?);
        consumed = end;
        if line.old.is_some() {
            if old.get(consumed) != Some(&line.text) {
                return Err(mismatch.into());
            }
            consumed += 1;
        }
        if line.new.is_some() {
            output.push(line.text);
        }
    }
    output.extend_from_slice(&old[consumed..]);
    Ok(output)
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
    if let Some(commits) = repo.native().and_then(|repo| {
        native::commits(&repo, &c.head, (c.left != EMPTY).then_some(c.base.as_str())).ok()
    }) {
        return Ok(commits);
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

pub fn visit_revision(
    repo: &Repository,
    revision: &str,
    contents: bool,
    mut visit: impl FnMut(&[u8], Option<&[u8]>) -> Result<bool>,
) -> Option<Result<()>> {
    let opened = repo.native()?;
    Some(native::visit_tree(
        &opened,
        revision,
        native::empty_oid(repo),
        contents,
        &mut visit,
    ))
}

pub fn commit_details(repo: &Repository, sha: &str) -> Result<String> {
    if !valid_oid(sha) {
        return Err("Choose a commit from the comparison.".into());
    }
    if let Some(details) = repo
        .native()
        .and_then(|repo| native::commit_details(&repo, sha).ok())
    {
        return Ok(details);
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
