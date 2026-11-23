//! Search frozen review snapshots outside the workspace lock.
use crate::{
    git::{self, Comparison, Repository, WORKTREE},
    service::Workspace,
};
use regex::{Regex, RegexBuilder};
use serde::{Deserialize, Serialize};
use std::{
    collections::{HashMap, HashSet},
    fmt::Write,
    io::{BufRead, BufReader},
    process::Stdio,
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc, Mutex,
    },
};
use tauri::{AppHandle, Manager};

const LIMIT: usize = 200;
static LATEST: AtomicU64 = AtomicU64::new(0);

#[derive(Clone, Copy, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Scope {
    Comparison,
    Branch,
    Stack,
    All,
}

pub type PreparedComparisons = Arc<Mutex<HashMap<[String; 2], Arc<Comparison>>>>;

pub struct Source {
    pub repo: Repository,
    pub stack: Vec<String>,
    pub current: Arc<Comparison>,
    pub comparisons: PreparedComparisons,
}

#[derive(Default, Serialize)]
pub struct Results {
    hits: Vec<Hit>,
    truncated: bool,
}

#[derive(Clone, Copy, Default, Serialize)]
#[serde(rename_all = "lowercase")]
enum Kind {
    #[default]
    Text,
    Path,
    Commit,
}

#[derive(Serialize)]
struct Hit {
    kind: Kind,
    #[serde(skip_serializing_if = "Option::is_none")]
    sha: Option<String>,
    pair: [String; 2],
    base: String,
    head: String,
    revision: Option<String>,
    path: String,
    group: String,
    row: Option<usize>,
    side: &'static str,
    line: Option<usize>,
    from: usize,
    to: usize,
    snippet_from: usize,
    snippet_to: usize,
    text: String,
}

#[derive(Clone, Copy, Default)]
struct Location<'a> {
    kind: Kind,
    sha: Option<&'a str>,
    revision: Option<&'a str>,
    path: &'a str,
    group: &'a str,
    row: Option<usize>,
    old: Option<usize>,
    new: Option<usize>,
}

struct Search<'a> {
    pattern: Regex,
    cancelled: &'a dyn Fn() -> bool,
    result: Results,
}

impl Search<'_> {
    fn check(&self) -> Result<(), String> {
        if (self.cancelled)() {
            Err("Search superseded.".into())
        } else {
            Ok(())
        }
    }

    fn add_matches(&mut self, c: &Comparison, loc: Location<'_>, text: &str) -> bool {
        let mut found = false;
        let mut previous_byte = 0;
        let mut previous_utf16 = 0;
        let crop = text.chars().nth(160).is_some();
        for hit in self.pattern.find_iter(text) {
            found = true;
            if self.result.hits.len() == LIMIT {
                self.result.truncated = true;
                return true;
            }
            let from = previous_utf16 + text[previous_byte..hit.start()].encode_utf16().count();
            let to = from + hit.as_str().encode_utf16().count();
            previous_byte = hit.end();
            previous_utf16 = to;
            let (start, end) = if crop {
                let start = text[..hit.start()]
                    .char_indices()
                    .rev()
                    .nth(23)
                    .map_or(0, |(i, _)| i);
                let end = text[start..]
                    .char_indices()
                    .nth(160)
                    .map_or(text.len(), |(i, _)| start + i)
                    .max(hit.end());
                (start, end)
            } else {
                (0, text.len())
            };
            let snippet_from =
                usize::from(start > 0) + text[start..hit.start()].encode_utf16().count();
            let snippet_to = snippet_from + to - from;
            let mut snippet = String::new();
            if start > 0 {
                snippet.push('…');
            }
            snippet.push_str(&text[start..end]);
            if end < text.len() {
                snippet.push('…');
            }
            self.result.hits.push(Hit {
                kind: loc.kind,
                sha: loc.sha.map(str::to_owned),
                pair: [c.left.clone(), c.right.clone()],
                base: c.base.clone(),
                head: c.head.clone(),
                revision: loc.revision.map(str::to_owned),
                path: loc.path.into(),
                group: loc.group.into(),
                row: loc.row,
                side: if loc.new.is_none() && loc.old.is_some() {
                    "old"
                } else {
                    "new"
                },
                line: loc.new.or(loc.old),
                from,
                to,
                snippet_from,
                snippet_to,
                text: snippet,
            });
            if !matches!(loc.kind, Kind::Text) {
                break;
            }
        }
        found
    }

    fn changed_paths(&mut self, c: &Comparison) -> Result<(), String> {
        for file in &c.files {
            self.check()?;
            let location = Location {
                kind: Kind::Path,
                path: &file.path,
                group: &file.group,
                ..Location::default()
            };
            if !self.add_matches(c, location, &path_text(&file.path)) && file.old != file.path {
                self.add_matches(c, location, &path_text(&file.old));
            }
            if self.result.truncated {
                break;
            }
        }
        Ok(())
    }

    fn tracked_paths(&mut self, repo: &Repository, c: &Comparison) -> Result<(), String> {
        let tip = c.branch_tip();
        let output = git::git(
            &repo.root,
            &["ls-tree", "-r", "-z", "--name-only", tip, "--"],
        )?;
        for bytes in output.split(|&b| b == 0).filter(|path| !path.is_empty()) {
            self.check()?;
            let path = git::name(bytes);
            self.add_matches(
                c,
                Location {
                    kind: Kind::Path,
                    path: &path,
                    revision: Some(tip),
                    ..Location::default()
                },
                &display_path(bytes),
            );
            if self.result.truncated {
                break;
            }
        }
        Ok(())
    }

    fn commits(
        &mut self,
        repo: &Repository,
        c: &Comparison,
        seen: &mut HashSet<String>,
    ) -> Result<(), String> {
        for commit in git::commits(repo, c)? {
            self.check()?;
            if !seen.insert(commit.sha.clone()) {
                continue;
            }
            let location = Location {
                kind: Kind::Commit,
                sha: Some(&commit.sha),
                ..Location::default()
            };
            if !self.add_matches(c, location, &commit.subject) {
                self.add_matches(c, location, &commit.sha);
            }
            if self.result.truncated {
                break;
            }
        }
        Ok(())
    }

    fn patch(&mut self, repo: &Repository, c: &Comparison) -> Result<(), String> {
        self.check()?;
        let cancelled = self.cancelled;
        let start = self.result.hits.len();
        git::visit_patches(repo, c, cancelled, |file, row, line| {
            self.check()?;
            if line.old.is_none() && line.new.is_none() {
                return Ok(true);
            }
            self.add_matches(
                c,
                Location {
                    path: &file.path,
                    group: &file.group,
                    row: Some(row),
                    old: line.old,
                    new: line.new,
                    ..Location::default()
                },
                &line.text,
            );
            Ok(!self.result.truncated)
        })?;
        let order: HashMap<_, _> = c
            .files
            .iter()
            .enumerate()
            .map(|(i, file)| ((file.path.as_str(), file.group.as_str()), i))
            .collect();
        self.result.hits[start..].sort_by_key(|hit| {
            (
                order[&(hit.path.as_str(), hit.group.as_str())],
                hit.row,
                hit.from,
            )
        });
        Ok(())
    }

    fn tree(&mut self, repo: &Repository, c: &Comparison, query: &str) -> Result<(), String> {
        // Skip irrelevant ASCII lines in Git. Keep all non-ASCII lines for Rust's
        // Unicode case folding (e.g. "s" also matches "ſ"), regardless of locale.
        let fragment = query
            .split(|c: char| !c.is_ascii_alphanumeric())
            .max_by_key(|s| s.len())
            .unwrap_or("");
        let tip = c.branch_tip();
        let mut child = git::command(&repo.root)?
            .env("LC_ALL", "C")
            .args([
                "grep",
                "-I",
                "-n",
                "-z",
                "--no-color",
                "--no-column",
                "--no-heading",
                "--no-break",
                "--no-recurse-submodules",
                "--no-textconv",
                "-Ei",
                "-e",
                fragment,
                "-e",
                "[^\t -~]",
                tip,
                "--",
            ])
            .stdout(Stdio::piped())
            .spawn()
            .map_err(|e| format!("Could not start Git: {e}"))?;
        let output = BufReader::new(child.stdout.take().expect("piped Git output"));
        let read = self.tree_lines(c, output);
        if read.is_err() || self.result.truncated {
            let _ = child.kill();
        }
        let status = child.wait().map_err(|e| e.to_string())?;
        read?;
        if self.result.truncated || status.success() || status.code() == Some(1) {
            Ok(())
        } else {
            Err(format!("Git could not search revision {tip} ({status})."))
        }
    }

    fn tree_lines(&mut self, c: &Comparison, mut output: impl BufRead) -> Result<(), String> {
        let prefix = format!("{}:", c.branch_tip());
        let mut path = Vec::new();
        let mut number = Vec::new();
        let mut line = Vec::new();
        let read_error = |e: std::io::Error| format!("Could not read Git search results: {e}");
        loop {
            self.check()?;
            path.clear();
            if output.read_until(0, &mut path).map_err(read_error)? == 0 {
                return Ok(());
            }
            let name = path
                .strip_suffix(&[0])
                .and_then(|p| p.strip_prefix(prefix.as_bytes()))
                .ok_or("Git returned an invalid search path.")?;
            number.clear();
            output.read_until(0, &mut number).map_err(read_error)?;
            let n = number
                .strip_suffix(&[0])
                .and_then(|n| std::str::from_utf8(n).ok())
                .and_then(|n| n.parse::<usize>().ok())
                .ok_or("Git returned an invalid line number.")?;
            line.clear();
            if output.read_until(b'\n', &mut line).map_err(read_error)? == 0 {
                return Err("Git returned an incomplete search result.".into());
            }
            let bytes = line.strip_suffix(b"\n").unwrap_or(&line);
            let text = String::from_utf8_lossy(bytes.strip_suffix(b"\r").unwrap_or(bytes));
            self.add_matches(
                c,
                Location {
                    path: &git::name(name),
                    revision: Some(c.branch_tip()),
                    new: Some(n),
                    ..Location::default()
                },
                &text,
            );
            if self.result.truncated {
                return Ok(());
            }
        }
    }
}

// Match and highlight the same escaped bytes the review can display.
fn path_text(path: &str) -> String {
    match git::path_arg(path) {
        Ok(decoded) => display_path(decoded.as_encoded_bytes()),
        Err(_) => display_path(path.as_bytes()),
    }
}

fn display_path(bytes: &[u8]) -> String {
    let mut text = String::new();
    for chunk in bytes.utf8_chunks() {
        for c in chunk.valid().chars() {
            match c {
                '\n' => text.push_str("\\n"),
                '\r' => text.push_str("\\r"),
                '\t' => text.push_str("\\t"),
                _ => text.push(c),
            }
        }
        for byte in chunk.invalid() {
            write!(text, "\\x{byte:02x}").expect("writing to a string");
        }
    }
    text
}

impl Source {
    fn comparison(
        &self,
        left: &str,
        right: &str,
        cancelled: &dyn Fn() -> bool,
    ) -> Result<Arc<Comparison>, String> {
        if left == self.current.left && right == self.current.right {
            return Ok(self.current.clone());
        }
        let key = [left.to_owned(), right.to_owned()];
        let lock_error = |_| "Reopen the review to search again.";
        if let Some(comparison) = self
            .comparisons
            .lock()
            .map_err(lock_error)?
            .get(&key)
            .cloned()
        {
            return Ok(comparison);
        }
        let comparison = Arc::new(git::compare(&self.repo, left, right)?);
        let mut comparisons = self.comparisons.lock().map_err(lock_error)?;
        if cancelled() {
            return Err("Search superseded.".into());
        }
        Ok(comparisons.entry(key).or_insert(comparison).clone())
    }

    fn search(
        &self,
        scope: Scope,
        query: &str,
        cancelled: &dyn Fn() -> bool,
    ) -> Result<Results, String> {
        if query.is_empty() {
            return Ok(Results::default());
        }
        let pattern = RegexBuilder::new(&regex::escape(query))
            .case_insensitive(true)
            .build()
            .map_err(|e| e.to_string())?;
        let mut search = Search {
            pattern,
            cancelled,
            result: Results::default(),
        };
        search.check()?;
        let c = &self.current;
        match scope {
            Scope::Branch => {
                search.tracked_paths(&self.repo, c)?;
                if !search.result.truncated {
                    search.tree(&self.repo, c, query)?;
                }
            }
            Scope::Comparison => {
                search.changed_paths(c)?;
                if !search.result.truncated {
                    search.patch(&self.repo, c)?;
                }
            }
            Scope::Stack | Scope::All => {
                let all = matches!(scope, Scope::All);
                let includes_checkout = self.stack.iter().any(|branch| {
                    branch == &self.repo.checkout
                        || (branch == "HEAD" && self.repo.checkout.starts_with("HEAD@"))
                });
                let local = c.right == WORKTREE || includes_checkout;
                let local_only = all && c.right == WORKTREE && !includes_checkout;
                let layers = self
                    .stack
                    .windows(2)
                    .filter(|_| !local_only)
                    .map(|pair| (pair[0].as_str(), pair[1].as_str()));
                let mut comparisons = Vec::new();
                for (left, right) in
                    layers.chain(local.then_some((self.repo.checkout.as_str(), WORKTREE)))
                {
                    search.check()?;
                    let layer = self.comparison(left, right, cancelled)?;
                    search.changed_paths(&layer)?;
                    comparisons.push(layer);
                    if search.result.truncated {
                        return Ok(search.result);
                    }
                }
                if all && !local_only {
                    let mut seen = HashSet::new();
                    if let (Some(left), Some(right)) = (self.stack.first(), self.stack.last()) {
                        if left != right && (left != &c.left || right != &c.right) {
                            let full = self.comparison(left, right, cancelled)?;
                            search.commits(&self.repo, &full, &mut seen)?;
                        }
                    }
                    if !search.result.truncated {
                        search.commits(&self.repo, c, &mut seen)?;
                    }
                }
                for layer in comparisons {
                    if search.result.truncated {
                        break;
                    }
                    search.patch(&self.repo, &layer)?;
                }
            }
        }
        search.check()?;
        Ok(search.result)
    }
}

#[tauri::command]
pub async fn search_review(
    app: AppHandle,
    snapshot: u64,
    scope: Scope,
    query: String,
) -> Result<Results, String> {
    let ticket = LATEST.fetch_add(1, Ordering::Relaxed).wrapping_add(1);
    if query.is_empty() {
        return Ok(Results::default());
    }
    tauri::async_runtime::spawn_blocking(move || {
        let state = app.state::<Mutex<Workspace>>();
        let source = state
            .lock()
            .map_err(|_| "Reopen the review to search again.")?
            .search_source(snapshot)?;
        source.search(scope, &query, &|| LATEST.load(Ordering::Relaxed) != ticket)
    })
    .await
    .map_err(|e| e.to_string())?
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::tempdir;

    #[test]
    fn repeated_queries_keep_local_snapshot_until_the_review_is_refreshed() {
        let dir = tempdir().unwrap();
        let root = dir.path();
        let git = |args: &[&str]| git::git(root, args).unwrap();
        git(&["init", "-qb", "main"]);
        git(&["config", "user.name", "Reviewer"]);
        git(&["config", "user.email", "review@example.test"]);
        git(&["config", "commit.gpgsign", "false"]);
        fs::write(root.join("code"), "base\n").unwrap();
        git(&["add", "-A"]);
        git(&["commit", "-qm", "base"]);
        git(&["switch", "-qc", "review"]);
        fs::write(root.join("code"), "review\n").unwrap();
        git(&["commit", "-qam", "review"]);
        let source = || {
            let repo = git::open_repo(root).unwrap();
            Source {
                current: Arc::new(git::compare(&repo, "refs/heads/main", &repo.checkout).unwrap()),
                stack: vec!["refs/heads/main".into(), repo.checkout.clone()],
                repo,
                comparisons: Default::default(),
            }
        };
        let first = source();
        fs::write(root.join("code"), "frozen-marker staged\n").unwrap();
        git(&["add", "code"]);
        fs::write(root.join("code"), "frozen-marker local\n").unwrap();
        fs::write(root.join("draft"), "frozen-marker draft\n").unwrap();
        let hits = first
            .search(Scope::All, "frozen-marker", &|| false)
            .unwrap();
        assert_eq!(hits.hits.len(), 4);
        let local = first
            .comparison(&first.repo.checkout, WORKTREE, &|| false)
            .unwrap();
        fs::write(root.join("code"), "new commit\n").unwrap();
        git(&["add", "code"]);
        git(&["commit", "-qm", "advance review"]);
        fs::write(root.join("code"), "fresh-marker staged\n").unwrap();
        git(&["add", "code"]);
        fs::write(root.join("code"), "fresh-marker local\n").unwrap();
        fs::write(root.join("draft"), "fresh-marker draft\n").unwrap();
        let next_query = Source {
            repo: first.repo.clone(),
            stack: first.stack.clone(),
            current: first.current.clone(),
            comparisons: first.comparisons.clone(),
        };
        let same = next_query
            .comparison(&first.repo.checkout, WORKTREE, &|| false)
            .unwrap();
        assert!(Arc::ptr_eq(&local, &same));
        let frozen = next_query
            .search(Scope::All, "frozen-marker", &|| false)
            .unwrap();
        assert_eq!(frozen.hits.len(), 4);
        assert!(frozen.hits.iter().all(|hit| hit.head == local.head));
        assert!(next_query
            .search(Scope::All, "fresh-marker", &|| false)
            .unwrap()
            .hits
            .is_empty());
        let refreshed = source();
        assert_ne!(refreshed.current.head, first.current.head);
        let fresh = refreshed
            .search(Scope::All, "fresh-marker", &|| false)
            .unwrap();
        assert_eq!(fresh.hits.len(), 4);
        assert!(fresh
            .hits
            .iter()
            .all(|hit| hit.base == refreshed.current.head && hit.head != local.head));
    }

    #[test]
    fn cancelled_and_failed_comparison_preparation_can_be_retried() {
        let dir = tempdir().unwrap();
        let root = dir.path();
        let git = |args: &[&str]| git::git(root, args).unwrap();
        git(&["init", "-qb", "main"]);
        git(&["config", "user.name", "Reviewer"]);
        git(&["config", "user.email", "review@example.test"]);
        git(&["config", "commit.gpgsign", "false"]);
        fs::write(root.join("code"), "base\n").unwrap();
        git(&["add", "-A"]);
        git(&["commit", "-qm", "base"]);
        git(&["switch", "-qc", "review"]);
        fs::write(root.join("code"), "review\n").unwrap();
        git(&["commit", "-qam", "review"]);
        let repo = git::open_repo(root).unwrap();
        let mut source = Source {
            current: Arc::new(git::compare(&repo, "refs/heads/main", &repo.checkout).unwrap()),
            repo,
            stack: vec![],
            comparisons: Default::default(),
        };
        assert!(Arc::ptr_eq(
            &source.current,
            &source
                .comparison("refs/heads/main", "refs/heads/review", &|| false)
                .unwrap()
        ));
        let pair = [source.repo.checkout.clone(), WORKTREE.into()];
        assert_eq!(
            source.comparison(&pair[0], &pair[1], &|| true).unwrap_err(),
            "Search superseded."
        );
        assert!(source.comparisons.lock().unwrap().is_empty());
        source.repo.root = root.join("missing");
        assert!(source.comparison(&pair[0], &pair[1], &|| false).is_err());
        assert!(source.comparisons.lock().unwrap().is_empty());
        source.repo.root = root.into();
        fs::write(root.join("draft"), "retry marker\n").unwrap();
        let prepared = source.comparison(&pair[0], &pair[1], &|| false).unwrap();
        assert_eq!(prepared.files[0].path, "draft");
        assert!(Arc::ptr_eq(
            &prepared,
            &source.comparison(&pair[0], &pair[1], &|| false).unwrap()
        ));
    }

    #[test]
    fn patch_search_keeps_review_rows_for_renames_literal_paths_and_frozen_local_edits() {
        let dir = tempdir().unwrap();
        let root = dir.path();
        let git = |args: &[&str]| git::git(root, args).unwrap();
        let record = || {
            git(&["add", "-A"]);
            git(&["commit", "-qm", "snapshot"]);
        };
        git(&["init", "-qb", "main"]);
        git(&["config", "user.name", "Reviewer"]);
        git(&["config", "user.email", "review@example.test"]);
        git(&["config", "commit.gpgsign", "false"]);
        git(&["config", "core.autocrlf", "false"]);
        let original = (1..=40).map(|i| format!("line {i}\n")).collect::<String>();
        let literal = "literal[1]\n\té";
        fs::write(root.join("before"), &original).unwrap();
        fs::write(root.join(literal), &original).unwrap();
        fs::write(root.join("removed"), "needle removed\n").unwrap();
        fs::write(root.join("type"), "needle regular\n").unwrap();
        #[cfg(unix)]
        let raw = {
            use std::os::unix::ffi::OsStrExt;
            std::ffi::OsStr::from_bytes(b"raw-\xff")
        };
        #[cfg(unix)]
        fs::write(root.join(raw), "before\n").unwrap();
        record();
        git(&["mv", "before", "after"]);
        fs::write(
            root.join("after"),
            original.replace("line 3\n", "😀 NEEDLE renamed\n"),
        )
        .unwrap();
        fs::write(
            root.join(literal),
            original
                .replace("line 3\n", "needle first\ninserted\n")
                .replace("line 37\n", "needle last"),
        )
        .unwrap();
        fs::remove_file(root.join("removed")).unwrap();
        fs::write(root.join("binary"), b"needle\0binary").unwrap();
        fs::write(root.join("empty"), b"").unwrap();
        #[cfg(unix)]
        {
            std::os::unix::fs::symlink("needle target", root.join("link")).unwrap();
            fs::remove_file(root.join("type")).unwrap();
            std::os::unix::fs::symlink("needle replacement", root.join("type")).unwrap();
            fs::write(root.join(raw), "needle raw path\n").unwrap();
        }
        record();
        let repo = git::open_repo(root).unwrap();
        let branch = git::compare(&repo, "HEAD^", &repo.checkout).unwrap();
        fs::write(root.join("after"), "needle staged\n").unwrap();
        git(&["add", "after"]);
        fs::write(root.join("after"), "needle unstaged\n").unwrap();
        fs::write(root.join("draft"), "needle untracked\n").unwrap();
        let local = git::compare(&repo, &repo.checkout, WORKTREE).unwrap();
        fs::write(root.join("after"), "replacement\n").unwrap();
        fs::write(root.join("draft"), "different draft\n").unwrap();
        record();
        fs::write(root.join(".git/search-order"), "type\nremoved\n*\n").unwrap();
        git(&["config", "diff.orderFile", ".git/search-order"]);
        for current in [branch, local] {
            let mut expected = Vec::new();
            for file in &current.files {
                if file.added.is_none() || file.removed.is_none() {
                    continue;
                }
                for (row, line) in git::patch(&repo, &current, file)
                    .unwrap()
                    .iter()
                    .enumerate()
                {
                    if (line.old.is_some() || line.new.is_some())
                        && line.text.to_lowercase().contains("needle")
                    {
                        expected.push((
                            file.path.clone(),
                            file.group.clone(),
                            row,
                            line.old,
                            line.new,
                            line.text.clone(),
                        ));
                    }
                }
            }
            assert!(!expected.is_empty());
            let source = Source {
                comparisons: Default::default(),
                current: Arc::new(current),
                repo: repo.clone(),
                stack: vec![],
            };
            let result = source
                .search(Scope::Comparison, "needle", &|| false)
                .unwrap();
            assert!(!result.truncated);
            let actual = result
                .hits
                .iter()
                .map(|hit| {
                    assert!(matches!(hit.kind, Kind::Text));
                    assert_eq!(hit.base, source.current.base);
                    assert_eq!(hit.head, source.current.head);
                    (
                        hit.path.clone(),
                        hit.group.clone(),
                        hit.row.unwrap(),
                        hit.side,
                        hit.line,
                        hit.text.clone(),
                    )
                })
                .collect::<Vec<_>>();
            let expected = expected
                .into_iter()
                .map(|(path, group, row, old, new, text)| {
                    (
                        path,
                        group,
                        row,
                        if new.is_none() && old.is_some() {
                            "old"
                        } else {
                            "new"
                        },
                        new.or(old),
                        text,
                    )
                })
                .collect::<Vec<_>>();
            assert_eq!(actual, expected);
        }
    }

    #[test]
    fn all_scope_stays_within_review_stack_changes() {
        let dir = tempdir().unwrap();
        let root = dir.path();
        let git = |args: &[&str]| git::git(root, args).unwrap();
        git(&["init", "-qb", "main"]);
        git(&["config", "user.name", "Reviewer"]);
        git(&["config", "user.email", "review@example.test"]);
        git(&["config", "commit.gpgsign", "false"]);
        fs::write(root.join("needle unchanged"), "needle unchanged content\n").unwrap();
        fs::write(root.join("outside"), "base\n").unwrap();
        git(&["add", "-A"]);
        git(&["commit", "-qm", "base"]);
        git(&["switch", "-qc", "review"]);
        fs::write(root.join("needle changed"), "needle review content\n").unwrap();
        git(&["add", "-A"]);
        git(&["commit", "-qm", "review change"]);
        git(&["switch", "-qc", "unrelated", "main"]);
        fs::write(root.join("outside"), "needle staged\n").unwrap();
        git(&["add", "outside"]);
        fs::write(root.join("outside"), "needle unstaged\n").unwrap();
        fs::write(root.join("needle untracked"), "needle untracked content\n").unwrap();
        let repo = git::open_repo(root).unwrap();
        let mut source = Source {
            comparisons: Default::default(),
            current: Arc::new(git::compare(&repo, "refs/heads/main", "refs/heads/review").unwrap()),
            repo,
            stack: vec!["refs/heads/main".into(), "refs/heads/review".into()],
        };
        let all = source.search(Scope::All, "needle", &|| false).unwrap();
        assert!(
            all.hits.iter().all(|hit| hit.path == "needle changed"),
            "default search escaped the review stack: {}",
            serde_json::to_string(&all).unwrap()
        );
        assert_eq!(all.hits.len(), 2);
        let branch = source.search(Scope::Branch, "needle", &|| false).unwrap();
        assert!(branch.hits.iter().any(|hit| hit.path == "needle unchanged"));
        assert!(branch
            .hits
            .iter()
            .any(|hit| hit.text == "needle unchanged content"));
        assert!(branch
            .hits
            .iter()
            .all(|hit| hit.path != "outside" && hit.path != "needle untracked"));
        source.current =
            Arc::new(git::compare(&source.repo, &source.repo.checkout, WORKTREE).unwrap());
        let local = source.search(Scope::All, "needle", &|| false).unwrap();
        assert!(
            local
                .hits
                .iter()
                .all(|hit| hit.path == "outside" || hit.path == "needle untracked"),
            "an off-stack working-tree review searched the saved stack: {}",
            serde_json::to_string(&local).unwrap()
        );
        assert_eq!(local.hits.len(), 5);
        assert!(source
            .search(Scope::All, "review change", &|| false)
            .unwrap()
            .hits
            .is_empty());
    }

    #[test]
    fn searches_branch_blobs_layer_patches_and_frozen_working_tree() {
        let dir = tempdir().unwrap();
        let root = dir.path();
        let git = |args: &[&str]| git::git(root, args).unwrap();
        let write = |path: &str, bytes: &[u8]| fs::write(root.join(path), bytes).unwrap();
        let record = || {
            git(&["add", "-A"]);
            git(&["commit", "-qm", "snapshot"]);
        };
        git(&["init", "-qb", "main"]);
        git(&["config", "user.name", "Reviewer"]);
        git(&["config", "user.email", "review@example.test"]);
        git(&["config", "commit.gpgsign", "false"]);
        write(
            "unchanged file",
            format!(
                "😀 NEE[D]LE nee[d]le\nſample\n{}🧭 needle end\n",
                "😀".repeat(170)
            )
            .as_bytes(),
        );
        write("binary", b"\0nee[d]le");
        write("changed", b"before\n");
        record();
        git(&["switch", "-qc", "one"]);
        write("changed", b"intermediate\n");
        record();
        git(&["switch", "-qc", "two"]);
        write("changed", b"after\n");
        record();
        let repo = git::open_repo(root).unwrap();
        let stack = ["refs/heads/main", "refs/heads/one", "refs/heads/two"];
        let mut source = Source {
            comparisons: Default::default(),
            current: Arc::new(git::compare(&repo, stack[0], stack[2]).unwrap()),
            repo,
            stack: stack.map(String::from).into(),
        };
        let find =
            |source: &Source, scope, query| source.search(scope, query, &|| false).unwrap().hits;
        let hits = find(&source, Scope::Branch, "nee[d]le");
        assert_eq!(hits.len(), 2);
        for hit in &hits {
            assert_eq!(hit.path, "unchanged file");
            assert_eq!((hit.row, hit.side, hit.line), (None, "new", Some(1)));
            assert_eq!(hit.revision.as_deref(), Some(source.current.head.as_str()));
        }
        assert_eq!(
            (hits[0].from, hits[0].to, hits[1].from, hits[1].to),
            (3, 11, 12, 20)
        );
        assert_eq!((hits[0].snippet_from, hits[1].snippet_from), (3, 12));
        let long = find(&source, Scope::Branch, "needle");
        assert_eq!(long.len(), 1);
        let hit = &long[0];
        assert_eq!((hit.from, hit.to), (343, 349));
        assert!(hit.text.starts_with('…'));
        let snippet: Vec<_> = hit.text.encode_utf16().collect();
        assert_eq!(
            String::from_utf16(&snippet[hit.snippet_from..hit.snippet_to]).unwrap(),
            "needle"
        );
        assert_eq!(find(&source, Scope::Branch, "sample")[0].line, Some(2));
        assert!(find(&source, Scope::Comparison, "nee[d]le").is_empty());
        assert!(find(&source, Scope::Comparison, "intermediate").is_empty());
        let hits = find(&source, Scope::Stack, "intermediate");
        assert_eq!(hits.len(), 2);
        assert_eq!(hits[0].pair, stack[..2]);
        assert_eq!(hits[1].pair, stack[1..]);
        for hit in &hits {
            let c = git::compare(&source.repo, &hit.pair[0], &hit.pair[1]).unwrap();
            let rows = git::patch(&source.repo, &c, &c.files[0]).unwrap();
            assert_eq!(rows[hit.row.unwrap()].text, "intermediate");
        }
        assert_eq!((hits[0].side, hits[1].side), ("new", "old"));

        write("changed", b"staged marker\n");
        git(&["add", "changed"]);
        write("changed", b"local marker\n");
        write("draft", b"draft marker\n");
        source.comparisons = Default::default(); // Refresh the review after local edits.
        let hits = find(&source, Scope::Stack, "marker");
        assert!(hits.iter().all(|hit| hit.pair == [stack[2], WORKTREE]));
        assert_eq!(hits.len(), 4); // staged also appears on the old side of the unstaged patch
        source.stack.pop();
        assert!(find(&source, Scope::Stack, "marker").is_empty());

        source.current = Arc::new(git::compare(&source.repo, stack[2], WORKTREE).unwrap());
        write("changed", b"different contents\n");
        write("draft", b"another draft\n");
        for (query, group) in [("local marker", "Unstaged"), ("draft marker", "Untracked")] {
            let hits = find(&source, Scope::Comparison, query);
            assert_eq!(hits.len(), 1);
            assert_eq!(hits[0].group, group);
        }
        assert!(find(&source, Scope::Branch, "marker").is_empty());
        assert_eq!(
            find(&source, Scope::Branch, "sample")[0]
                .revision
                .as_deref(),
            Some(source.current.base.as_str())
        );
    }

    #[test]
    fn palette_search_prioritizes_paths_and_preserves_scope_provenance() {
        let dir = tempdir().unwrap();
        let root = dir.path();
        let git = |args: &[&str]| git::git(root, args).unwrap();
        let write = |path: &str, text: &str| fs::write(root.join(path), text).unwrap();
        let record = |message| {
            git(&["add", "-A"]);
            git(&["commit", "-qm", message]);
        };
        git(&["init", "-qb", "main"]);
        git(&["config", "user.name", "Reviewer"]);
        git(&["config", "user.email", "review@example.test"]);
        git(&["config", "commit.gpgsign", "false"]);
        write("😀 needle docs", "needle only in unchanged file\n");
        write("prior-name", "same content after rename\n");
        write("needle mixed", "base\n");
        record("base");
        git(&["switch", "-qc", "one"]);
        git(&["mv", "prior-name", "new-name"]);
        write("needle first", "needle in first layer\n");
        record("needle first commit");
        git(&["switch", "-qc", "two"]);
        write("needle final", "needle in second layer\n");
        record("needle second commit");
        git(&["switch", "-qc", "other", "main"]);
        write("needle mixed", "needle staged\n");
        git(&["add", "needle mixed"]);
        write("needle mixed", "needle unstaged\n");
        write("needle draft", "needle untracked\n");

        let repo = git::open_repo(root).unwrap();
        let branches = ["refs/heads/main", "refs/heads/one", "refs/heads/two"];
        let mut source = Source {
            comparisons: Default::default(),
            current: Arc::new(git::compare(&repo, branches[0], branches[2]).unwrap()),
            repo,
            stack: branches.map(String::from).into(),
        };
        let find =
            |source: &Source, scope, query: &str| source.search(scope, query, &|| false).unwrap();
        let all = find(&source, Scope::All, "needle");
        assert!(!all.truncated);
        let (paths, rest) = all.hits.split_at(
            all.hits
                .iter()
                .position(|hit| !matches!(hit.kind, Kind::Path))
                .unwrap(),
        );
        assert_eq!(paths.len(), 2);
        assert_eq!(paths[0].pair, branches[..2]);
        assert_eq!(paths[1].pair, branches[1..]);
        assert_eq!(rest[0].sha.as_deref(), Some(source.current.head.as_str()));
        assert!(matches!(rest[0].kind, Kind::Commit));
        assert_eq!(rest[0].text, "needle second commit");
        assert_eq!(
            rest.iter()
                .filter(|h| matches!(h.kind, Kind::Commit))
                .count(),
            2
        );
        assert!(rest
            .iter()
            .all(|h| !h.text.contains("only in unchanged file")));
        assert!(rest.iter().all(|h| h.group.is_empty()));
        let serialized = serde_json::to_value(&paths[0]).unwrap();
        assert_eq!(serialized["kind"], "path");
        assert!(serialized["line"].is_null());

        let prefix = &source.current.head[..12];
        let sha_hit = find(&source, Scope::All, prefix);
        assert!(sha_hit.hits.iter().any(|h| {
            matches!(h.kind, Kind::Commit)
                && h.text == source.current.head
                && (h.from, h.to) == (0, 12)
        }));
        let old = find(&source, Scope::Comparison, "prior-name");
        assert_eq!(old.hits.len(), 1);
        assert_eq!(old.hits[0].path, "new-name");
        assert_eq!(old.hits[0].text, "prior-name");
        assert!(find(&source, Scope::Stack, "needle draft").hits.is_empty());

        let branch = find(&source, Scope::Branch, "needle");
        assert!(branch
            .hits
            .iter()
            .any(|h| h.path == "😀 needle docs" && matches!(h.kind, Kind::Path)));
        assert!(branch
            .hits
            .iter()
            .any(|h| h.text.contains("only in unchanged file") && matches!(h.kind, Kind::Text)));

        source.current =
            Arc::new(git::compare(&source.repo, &source.repo.checkout, WORKTREE).unwrap());
        write("needle mixed", "replacement\n");
        let frozen = find(&source, Scope::All, "needle unstaged");
        assert_eq!(frozen.hits.len(), 1);
        assert_eq!(frozen.hits[0].head, source.current.head);
        assert_eq!(frozen.hits[0].group, "Unstaged");
    }

    #[test]
    fn palette_paths_use_the_shared_budget_before_patch_contents() {
        let dir = tempdir().unwrap();
        let root = dir.path();
        git::git(root, &["init", "-qb", "main"]).unwrap();
        fs::write(root.join("a"), "x".repeat(LIMIT + 1)).unwrap();
        fs::write(root.join("z-x"), "no match here").unwrap();
        let repo = git::open_repo(root).unwrap();
        let source = Source {
            comparisons: Default::default(),
            current: Arc::new(git::compare(&repo, &repo.checkout, WORKTREE).unwrap()),
            repo,
            stack: vec![],
        };
        let result = source.search(Scope::All, "x", &|| false).unwrap();
        assert!(result.truncated);
        assert_eq!(result.hits.len(), LIMIT);
        assert!(matches!(result.hits[0].kind, Kind::Path));
        assert_eq!(result.hits[0].path, "z-x");
        assert!(matches!(result.hits[1].kind, Kind::Text));
        assert!(source.search(Scope::All, "x", &|| true).is_err());
    }

    #[test]
    fn result_limit_distinguishes_an_exact_count_from_overflow() {
        let dir = tempdir().unwrap();
        git::git(dir.path(), &["init", "-qb", "main"]).unwrap();
        let repo = git::open_repo(dir.path()).unwrap();
        let compare = |count| {
            fs::write(dir.path().join("draft"), "x".repeat(count)).unwrap();
            Source {
                comparisons: Default::default(),
                current: Arc::new(git::compare(&repo, &repo.checkout, WORKTREE).unwrap()),
                repo: repo.clone(),
                stack: vec![],
            }
        };
        for (count, truncated) in [(LIMIT, false), (LIMIT + 1, true)] {
            let source = compare(count);
            let result = source.search(Scope::Comparison, "X", &|| false).unwrap();
            assert_eq!(result.hits.len(), LIMIT);
            assert_eq!(result.truncated, truncated);
            assert_eq!(result.hits.last().unwrap().to, LIMIT);
            assert!(source.search(Scope::Stack, "x", &|| true).is_err());
            assert!(source
                .search(Scope::Branch, "x", &|| false)
                .unwrap()
                .hits
                .is_empty());
        }
    }
}
