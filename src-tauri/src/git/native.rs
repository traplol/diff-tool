//! Read-only libgit2 operations. Git remains the compatibility path for
//! repository formats and diff semantics libgit2 cannot reproduce.
use super::{name, path_arg, Change, Commit, RevisionFile, EMPTY};
use git2::{
    Delta, Diff, DiffFindOptions, DiffOptions, FileMode, ObjectType, Oid, Patch, Repository, Tree,
};
use std::{
    collections::{BTreeMap, BTreeSet, HashSet},
    path::{Path, PathBuf},
    sync::{Arc, Mutex, MutexGuard},
};

type Result<T> = std::result::Result<T, git2::Error>;

pub(super) fn open(path: &Path) -> Result<Repository> {
    match discover(path) {
        #[cfg(windows)]
        Err(error) if error.code() == git2::ErrorCode::Owner => wsl_trust::open(path, error),
        other => other,
    }
}

fn discover(path: &Path) -> Result<Repository> {
    Repository::open_ext(
        path,
        git2::RepositoryOpenFlags::CROSS_FS,
        std::iter::empty::<&std::ffi::OsStr>(),
    )
}

#[derive(Clone)]
pub(super) struct Handle {
    root: PathBuf,
    repo: Arc<Mutex<Repository>>,
}

impl std::fmt::Debug for Handle {
    fn fmt(&self, format: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        format.write_str("libgit2 repository")
    }
}

pub(super) enum Access<'a> {
    Cached(MutexGuard<'a, Repository>),
    Independent(Repository),
}

impl std::ops::Deref for Access<'_> {
    type Target = Repository;

    fn deref(&self) -> &Repository {
        match self {
            Self::Cached(repo) => repo,
            Self::Independent(repo) => repo,
        }
    }
}

impl Handle {
    pub(super) fn new(root: PathBuf, repo: Repository) -> Self {
        Self {
            root,
            repo: Arc::new(Mutex::new(repo)),
        }
    }

    pub(super) fn access(&self, root: &Path) -> Option<Access<'_>> {
        if root != self.root {
            return open(root).ok().map(Access::Independent);
        }
        match self.repo.try_lock() {
            Ok(repo) => Some(Access::Cached(repo)),
            // A concurrent search may hold the cached handle while reading
            // blobs. Give the foreground request its own handle in that case.
            Err(_) => open(root).ok().map(Access::Independent),
        }
    }
}

#[cfg(windows)]
pub(super) use wsl_trust::configure;

#[cfg(windows)]
mod wsl_trust {
    use super::{discover, Repository, Result};
    use crate::git::{self, windows::WslCheckout};
    use std::{
        path::{Path, PathBuf},
        sync::{Mutex, OnceLock},
    };

    static CONFIG: OnceLock<Mutex<PathBuf>> = OnceLock::new();

    // Called at process entry before creating threads or opening repositories.
    // Keep the actual Windows global config as an include. Libgit2 alone reads
    // the private overlay, and Git subprocesses retain their ordinary config.
    pub fn configure() -> Result<tempfile::TempDir> {
        let original = git2::Config::find_global().ok();
        let directory = tempfile::tempdir().map_err(|e| git2::Error::from_str(&e.to_string()))?;
        let path = directory.path().join(".gitconfig");
        let mut config = git2::Config::open(&path)?;
        if let Some(original) = original {
            let value = original
                .to_str()
                .ok_or_else(|| git2::Error::from_str("Unsupported Git config path"))?;
            config.set_str("include.path", value)?;
        } else {
            std::fs::write(&path, b"").map_err(|e| git2::Error::from_str(&e.to_string()))?;
        }
        unsafe {
            git2::opts::set_search_path(git2::ConfigLevel::Global, directory.path())?;
        }
        CONFIG
            .set(Mutex::new(path))
            .map_err(|_| git2::Error::from_str("Git configuration already initialized"))?;
        Ok(directory)
    }

    pub fn open(path: &Path, original: git2::Error) -> Result<Repository> {
        let Some(wsl) = WslCheckout::from_path(path) else {
            return Err(original);
        };
        let Some(config) = CONFIG.get() else {
            return Err(original);
        };
        let config = config
            .lock()
            .map_err(|_| git2::Error::from_str("Git configuration lock failed"))?;
        if let Ok(repo) = discover(path) {
            return Ok(repo);
        }
        // Validate as the Linux user before trusting an exact Windows path.
        // Linux Git does its normal safe.directory/ownership check here.
        let output = git::git(path, &["rev-parse", "--show-toplevel"])
            .map_err(|e| git2::Error::from_str(&e))?;
        let bytes = output.strip_suffix(b"\n").unwrap_or(&output);
        let linux = std::str::from_utf8(bytes)
            .map_err(|_| git2::Error::from_str("Unsupported WSL checkout path"))?;
        let root = wsl
            .host_path(Path::new(linux))
            .map_err(|e| git2::Error::from_str(&e))?;
        let safe = root
            .to_str()
            .ok_or_else(|| git2::Error::from_str("Unsupported WSL checkout path"))?
            .replace('\\', "/");
        git2::Config::open(&*config)?.set_multivar("safe.directory", "a^", &safe)?;
        discover(&root)
    }
}

pub(super) struct Metadata {
    pub refs: BTreeMap<String, String>,
    pub remotes: BTreeMap<String, String>,
    pub checkout: String,
    pub head: Option<String>,
    pub parent: Option<String>,
    pub empty: String,
}

pub(super) fn checkout(repo: &Repository) -> Result<(String, Option<String>)> {
    let reference = repo.find_reference("HEAD")?;
    let head = match reference.resolve() {
        Ok(head) => head.target().map(|oid| oid.to_string()),
        Err(error) if error.code() == git2::ErrorCode::NotFound => None,
        Err(error) => return Err(error),
    };
    let checkout = reference
        .symbolic_target_bytes()
        .map(name)
        .unwrap_or_else(|| {
            head.as_ref()
                .map_or_else(|| "HEAD".into(), |head| format!("HEAD@{head}"))
        });
    Ok((checkout, head))
}

pub(super) fn metadata(repo: &Repository) -> Result<Metadata> {
    let (checkout, head) = checkout(repo)?;
    let mut refs = BTreeMap::new();
    let mut remotes = BTreeMap::new();
    for reference in repo.references()? {
        let reference = reference?;
        let key = name(reference.name_bytes());
        if !(key.starts_with("refs/heads/") || key.starts_with("refs/remotes/")) {
            continue;
        }
        if let Some(oid) = reference.target() {
            refs.insert(key, oid.to_string());
        } else if key.starts_with("refs/remotes/") && key.ends_with("/HEAD") {
            if let Some(target) = reference.symbolic_target_bytes().map(name) {
                let remote = key.trim_end_matches("HEAD");
                if target.starts_with(remote) {
                    remotes.insert(remote.into(), target);
                }
            }
        }
    }
    let parent = head.as_deref().and_then(|head| {
        let commit = repo.find_commit(Oid::from_str(head).ok()?).ok()?;
        commit.parent_id(0).ok().map(|oid| oid.to_string())
    });
    let empty = Oid::hash_object_ext(ObjectType::Tree, b"", repo.object_format())?.to_string();
    Ok(Metadata {
        refs,
        remotes,
        checkout,
        head,
        parent,
        empty,
    })
}

pub(super) fn tips(
    repo: &Repository,
    filter: &str,
    names: &BTreeMap<String, String>,
) -> Result<BTreeSet<String>> {
    let (mode, target) = filter
        .split_once('=')
        .ok_or_else(|| git2::Error::from_str("Invalid stack filter"))?;
    let target = Oid::from_str(target)?;
    let mut found = BTreeSet::new();
    for candidate in names.keys() {
        let oid = Oid::from_str(candidate)?;
        let (head, base) = if mode == "--merged" {
            (target, oid)
        } else {
            (oid, target)
        };
        if head == base || repo.graph_descendant_of(head, base)? {
            found.insert(candidate.clone());
        }
    }
    Ok(found)
}

pub(super) fn merge_base(repo: &Repository, a: &str, b: &str) -> Result<String> {
    repo.merge_base(Oid::from_str(a)?, Oid::from_str(b)?)
        .map(|oid| oid.to_string())
}

pub(super) fn descends(repo: &Repository, origin: &str, head: &str) -> Result<bool> {
    repo.graph_descendant_of(Oid::from_str(head)?, Oid::from_str(origin)?)
}

pub(super) fn blob(repo: &Repository, object: &str) -> Result<Vec<u8>> {
    Ok(repo.find_blob(Oid::from_str(object)?)?.content().to_vec())
}

pub(super) fn revision_file(
    repo: &Repository,
    revision: &str,
    path: &Path,
) -> super::Result<RevisionFile> {
    let git_error = |e: git2::Error| e.to_string();
    let tree = repo
        .revparse_single(revision)
        .and_then(|object| object.peel_to_tree())
        .map_err(git_error)?;
    let entry = tree
        .get_path(path)
        .map_err(|_| "This path is no longer available at this revision.")?;
    if entry.filemode() == 0o160000 {
        return Ok(RevisionFile::Submodule {
            oid: entry.id().to_string(),
        });
    }
    let blob = repo.find_blob(entry.id()).map_err(git_error)?;
    let data = blob.content();
    if data.contains(&0) {
        Ok(RevisionFile::Binary { bytes: data.len() })
    } else {
        Ok(RevisionFile::Text {
            lines: super::text_lines(data)?,
        })
    }
}

fn tree<'a>(repo: &'a Repository, value: &str, empty: &str) -> Result<Option<Tree<'a>>> {
    if value == empty {
        return Ok(None);
    }
    repo.find_object(Oid::from_str(value)?, None)?
        .peel_to_tree()
        .map(Some)
}

fn options() -> DiffOptions {
    let mut options = DiffOptions::new();
    options
        .include_typechange(true)
        .context_lines(3)
        .id_abbrev(40)
        .indent_heuristic(true);
    options
}

fn rename(diff: &mut Diff<'_>) -> Result<()> {
    let mut options = DiffFindOptions::new();
    diff.find_similar(Some(options.renames(true)))
}

pub(super) fn branch_diff<'a>(
    repo: &'a Repository,
    base: &str,
    head: &str,
    empty: &str,
) -> Result<Diff<'a>> {
    let old = tree(repo, base, empty)?;
    let new = tree(repo, head, empty)?;
    let mut diff = repo.diff_tree_to_tree(old.as_ref(), new.as_ref(), Some(&mut options()))?;
    rename(&mut diff)?;
    Ok(diff)
}

fn format_mode(mode: FileMode) -> String {
    let value: i32 = mode.into();
    format!("{value:06o}")
}

fn changes(
    diff: &Diff<'_>,
    group: &str,
    untracked: Option<&HashSet<String>>,
) -> Result<Vec<Change>> {
    let mut changes = Vec::new();
    for i in 0..diff.deltas().len() {
        let delta = diff
            .get_delta(i)
            .ok_or_else(|| git2::Error::from_str("Missing diff entry"))?;
        let status = match delta.status() {
            Delta::Added | Delta::Untracked => "A",
            Delta::Deleted => "D",
            Delta::Modified => "M",
            Delta::Renamed => "R",
            Delta::Copied => "C",
            _ => return Err(git2::Error::from_str("Unsupported native diff entry")),
        };
        let old = delta.old_file();
        let new = delta.new_file();
        if old.mode() == FileMode::Commit || new.mode() == FileMode::Commit {
            return Err(git2::Error::from_str("Use Git for submodule patches"));
        }
        let old_path = old
            .path_bytes()
            .or_else(|| new.path_bytes())
            .unwrap_or_default();
        let path = new.path_bytes().unwrap_or(old_path);
        if old_path.is_empty() || path.is_empty() {
            return Err(git2::Error::from_str("Missing diff path"));
        }
        let untracked_file = delta.status() == Delta::Untracked;
        let path = name(path);
        if untracked_file && untracked.is_some_and(|paths| !paths.contains(&path)) {
            continue;
        }
        let group = if untracked_file { "Untracked" } else { group };
        let mut patch = Patch::from_diff(diff, i)?;
        // Generating the patch resolves binary flags and hashes working files.
        let delta = diff.get_delta(i).unwrap();
        let old = delta.old_file();
        let new = delta.new_file();
        let binary = delta.flags().contains(git2::DiffFlags::BINARY);
        let (added, removed) = match &patch {
            _ if binary => (None, None),
            Some(patch) => {
                let (_, added, removed) = patch.line_stats()?;
                (Some(added), Some(removed))
            }
            None => (Some(0), Some(0)),
        };
        let local_sections = match &mut patch {
            Some(patch) if !group.is_empty() => vec![patch.to_buf()?.to_vec()],
            _ => Vec::new(),
        };
        changes.push(Change {
            status: status.into(),
            old: name(old_path),
            path,
            added,
            removed,
            old_mode: format_mode(old.mode()),
            mode: format_mode(new.mode()),
            old_oid: old.id().to_string(),
            oid: if new.mode() != FileMode::Unreadable && new.id().is_zero() && !group.is_empty() {
                return Err(git2::Error::from_str("Missing native working file hash"));
            } else {
                new.id().to_string()
            },
            group: group.into(),
            local_sections,
        });
    }
    Ok(changes)
}

// Some Git configuration changes patch ordering, text classification, or
// worktree conversion. Preserve Git's behavior for those checkouts.
pub(super) fn supports_diff(repo: &Repository) -> bool {
    let Ok(config) = repo.config() else {
        return false;
    };
    for key in [
        "diff.orderFile",
        "diff.algorithm",
        "diff.renames",
        "diff.renameLimit",
        "core.attributesFile",
    ] {
        if config.get_entry(key).is_ok() {
            return false;
        }
    }
    true
}

pub(super) fn working_changes(
    repo: &Repository,
    base: &str,
    empty: &str,
    untracked: Option<&HashSet<String>>,
) -> Result<Vec<Change>> {
    let mut index = repo.index()?;
    index.read(true)?;
    if index.has_conflicts() {
        return Err(git2::Error::from_str("Use Git for unmerged index entries"));
    }
    let base = tree(repo, base, empty)?;
    let mut staged = repo.diff_tree_to_index(base.as_ref(), Some(&index), Some(&mut options()))?;
    rename(&mut staged)?;
    let mut result = changes(&staged, "Staged", None)?;
    let include_untracked = untracked.is_none_or(|paths| !paths.is_empty());
    let mut opts = options();
    opts.update_index(false)
        .include_untracked(include_untracked)
        .recurse_untracked_dirs(include_untracked)
        .show_untracked_content(include_untracked);
    let unstaged = repo.diff_index_to_workdir(Some(&index), Some(&mut opts))?;
    let (mut untracked_changes, mut modified): (Vec<_>, Vec<_>) =
        changes(&unstaged, "Unstaged", untracked)?
            .into_iter()
            .partition(|change| change.group == "Untracked");
    result.append(&mut modified);
    result.append(&mut untracked_changes);
    Ok(result)
}

pub(super) fn branch_changes(
    repo: &Repository,
    base: &str,
    head: &str,
    empty: &str,
) -> Result<Vec<Change>> {
    changes(&branch_diff(repo, base, head, empty)?, "", None)
}

pub(super) fn branch_patch(
    repo: &Repository,
    base: &str,
    head: &str,
    empty: &str,
    file: &Change,
) -> Result<Vec<u8>> {
    if file.status == "T" || file.old_mode == "160000" || file.mode == "160000" {
        return Err(git2::Error::from_str("Use Git for this patch"));
    }
    let old = tree(repo, base, empty)?;
    let new = tree(repo, head, empty)?;
    let mut opts = options();
    opts.disable_pathspec_match(true);
    for encoded in [&file.old, &file.path] {
        opts.pathspec(path_arg(encoded).map_err(|error| git2::Error::from_str(&error))?);
    }
    let mut diff = repo.diff_tree_to_tree(old.as_ref(), new.as_ref(), Some(&mut opts))?;
    rename(&mut diff)?;
    for (i, delta) in diff.deltas().enumerate() {
        if delta.old_file().id().to_string() == file.old_oid
            && delta.new_file().id().to_string() == file.oid
        {
            return Ok(match Patch::from_diff(&diff, i)? {
                Some(mut patch) => patch.to_buf()?.to_vec(),
                None => vec![],
            });
        }
    }
    Err(git2::Error::from_str(
        "Native patch differs from the comparison",
    ))
}

pub(super) fn commits(repo: &Repository, head: &str, base: Option<&str>) -> Result<Vec<Commit>> {
    let mut walk = repo.revwalk()?;
    walk.push(Oid::from_str(head)?)?;
    walk.set_sorting(git2::Sort::TIME)?;
    if let Some(base) = base {
        walk.hide(Oid::from_str(base)?)?;
    }
    walk.map(|oid| {
        let oid = oid?;
        let commit = repo.find_commit(oid)?;
        let author = commit.author();
        Ok(Commit {
            sha: oid.to_string(),
            author: String::from_utf8_lossy(author.name_bytes()).into_owned(),
            date: short_date(author.when()),
            subject: String::from_utf8_lossy(commit.summary_bytes().unwrap_or_default())
                .into_owned(),
        })
    })
    .collect()
}

// Proleptic Gregorian civil date from Unix days, including the author's offset.
fn short_date(time: git2::Time) -> String {
    let days = (time.seconds() + i64::from(time.offset_minutes()) * 60).div_euclid(86400) + 719468;
    let era = days.div_euclid(146097);
    let doe = days.rem_euclid(146097);
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = yoe + era * 400 + i64::from(month <= 2);
    format!("{year:04}-{month:02}-{day:02}")
}

pub(super) fn empty_oid(repo: &super::Repository) -> &str {
    &repo.refs[EMPTY]
}

// Traverse tree entries using their byte paths. File contents are only
// opened for text searches and traversal stops as soon as the caller is done.
pub(super) fn visit_tree(
    repo: &Repository,
    revision: &str,
    empty: &str,
    contents: bool,
    visit: &mut impl FnMut(&[u8], Option<&[u8]>) -> super::Result<bool>,
) -> super::Result<()> {
    if let Some(tree) = tree(repo, revision, empty).map_err(|error| error.to_string())? {
        walk_tree(repo, &tree, &mut Vec::new(), contents, visit)?;
    }
    Ok(())
}

fn walk_tree(
    repo: &Repository,
    tree: &Tree<'_>,
    path: &mut Vec<u8>,
    contents: bool,
    visit: &mut impl FnMut(&[u8], Option<&[u8]>) -> super::Result<bool>,
) -> super::Result<bool> {
    for entry in tree.iter() {
        let len = path.len();
        path.extend_from_slice(entry.name_bytes());
        let entry_mode = entry.filemode();
        let keep_going = if entry_mode == 0o040000 {
            path.push(b'/');
            let subtree = repo.find_tree(entry.id()).map_err(|e| e.to_string())?;
            walk_tree(repo, &subtree, path, contents, visit)?
        } else if !contents {
            visit(path, None)?
        } else if matches!(entry_mode, 0o100644 | 0o100755) {
            let blob = repo.find_blob(entry.id()).map_err(|e| e.to_string())?;
            visit(path, (!blob.is_binary()).then(|| blob.content()))?
        } else {
            visit(path, None)?
        };
        path.truncate(len);
        if !keep_going {
            return Ok(false);
        }
    }
    Ok(true)
}

pub(super) fn commit_details(repo: &Repository, sha: &str) -> Result<String> {
    use std::fmt::Write as _;
    let commit = repo.find_commit(Oid::from_str(sha)?)?;
    let author = commit.author();
    let committer = commit.committer();
    let mut text = format!(
        "commit {sha}\nAuthor:     {} <{}>\nAuthorDate: {}\nCommit:     {} <{}>\nCommitDate: {}\n\n",
        String::from_utf8_lossy(author.name_bytes()),
        String::from_utf8_lossy(author.email_bytes()),
        iso_date(author.when()),
        String::from_utf8_lossy(committer.name_bytes()),
        String::from_utf8_lossy(committer.email_bytes()),
        iso_date(committer.when())
    );
    for line in String::from_utf8_lossy(commit.message_bytes()).lines() {
        let _ = writeln!(text, "    {line}");
    }
    if commit.parent_count() <= 1 {
        let old = match commit.parent_count() {
            0 => None,
            _ => Some(commit.parent(0)?.tree()?),
        };
        let new = commit.tree()?;
        let mut diff = repo.diff_tree_to_tree(old.as_ref(), Some(&new), Some(&mut options()))?;
        rename(&mut diff)?;
        let stats = diff.stats()?.to_buf(git2::DiffStatsFormat::FULL, 80)?;
        text.push('\n');
        text.push_str(&String::from_utf8_lossy(&stats));
    }
    Ok(text.trim_end_matches('\n').to_owned())
}

fn iso_date(time: git2::Time) -> String {
    let offset = time.offset_minutes();
    let local = (time.seconds() + i64::from(offset) * 60).rem_euclid(86400);
    let sign = if offset < 0 { '-' } else { '+' };
    let offset = offset.unsigned_abs();
    format!(
        "{} {:02}:{:02}:{:02} {sign}{:02}{:02}",
        short_date(time),
        local / 3600,
        local / 60 % 60,
        local % 60,
        offset / 60,
        offset % 60
    )
}

pub(super) fn patch_at(diff: &Diff<'_>, index: usize) -> Result<Vec<u8>> {
    Ok(match Patch::from_diff(diff, index)? {
        Some(mut patch) => patch.to_buf()?.to_vec(),
        None => vec![],
    })
}
