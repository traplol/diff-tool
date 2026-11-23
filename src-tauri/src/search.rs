//! Search frozen review snapshots outside the workspace lock.
use crate::{
    git::{self, Comparison, Repository, WORKTREE},
    service::Workspace,
};
use regex::{Regex, RegexBuilder};
use serde::{Deserialize, Serialize};
use std::{
    collections::HashSet,
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

pub struct Source {
    pub repo: Repository,
    pub stack: Vec<String>,
    pub current: Arc<Comparison>,
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

    fn tracked_paths(
        &mut self,
        repo: &Repository,
        c: &Comparison,
        shown: &HashSet<String>,
    ) -> Result<(), String> {
        let tip = c.branch_tip();
        let output = git::git(&repo.root, &["ls-tree", "-r", "-z", "--name-only", tip, "--"])?;
        for bytes in output.split(|&b| b == 0).filter(|path| !path.is_empty()) {
            self.check()?;
            let path = git::name(bytes);
            if shown.contains(&path) {
                continue;
            }
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
        for file in &c.files {
            self.check()?;
            if file.added.is_none() || file.removed.is_none() {
                continue;
            }
            for (row, line) in git::patch(repo, c, file)?.iter().enumerate() {
                self.check()?;
                if line.old.is_none() && line.new.is_none() {
                    continue;
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
                if self.result.truncated {
                    return Ok(());
                }
            }
        }
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
    fn comparison(&self, left: &str, right: &str) -> Result<Arc<Comparison>, String> {
        if left == self.current.left && right == self.current.right {
            Ok(self.current.clone())
        } else {
            git::compare(&self.repo, left, right).map(Arc::new)
        }
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
                search.tracked_paths(&self.repo, c, &HashSet::new())?;
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
                let local = all
                    || c.right == WORKTREE
                    || self.stack.iter().any(|branch| {
                        branch == &self.repo.checkout
                            || (branch == "HEAD" && self.repo.checkout.starts_with("HEAD@"))
                    });
                let layers = self
                    .stack
                    .windows(2)
                    .map(|pair| (pair[0].as_str(), pair[1].as_str()));
                let mut comparisons = Vec::new();
                for (left, right) in
                    layers.chain(local.then_some((self.repo.checkout.as_str(), WORKTREE)))
                {
                    search.check()?;
                    let layer = self.comparison(left, right)?;
                    search.changed_paths(&layer)?;
                    comparisons.push(layer);
                    if search.result.truncated {
                        return Ok(search.result);
                    }
                }
                if all {
                    let shown = search
                        .result
                        .hits
                        .iter()
                        .map(|hit| hit.path.clone())
                        .collect();
                    search.tracked_paths(&self.repo, c, &shown)?;
                    if search.result.truncated {
                        return Ok(search.result);
                    }

                    let mut seen = HashSet::new();
                    if let (Some(left), Some(right)) = (self.stack.first(), self.stack.last()) {
                        if left != right && (left != &c.left || right != &c.right) {
                            let full = self.comparison(left, right)?;
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
        source.search(scope, &query, &|| {
            LATEST.load(Ordering::Relaxed) != ticket
        })
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
            format!("😀 NEE[D]LE nee[d]le\nſample\n{}🧭 needle end\n", "😀".repeat(170)).as_bytes(),
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
            current: Arc::new(git::compare(&repo, stack[0], stack[2]).unwrap()),
            repo,
            stack: stack.map(String::from).into(),
        };
        let find = |source: &Source, scope, query| {
            source.search(scope, query, &|| false).unwrap().hits
        };
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
            current: Arc::new(git::compare(&repo, branches[0], branches[2]).unwrap()),
            repo,
            stack: branches.map(String::from).into(),
        };
        let find = |source: &Source, scope, query: &str| {
            source.search(scope, query, &|| false).unwrap()
        };
        let all = find(&source, Scope::All, "needle");
        assert!(!all.truncated);
        let (paths, rest) = all.hits.split_at(
            all.hits
                .iter()
                .position(|hit| !matches!(hit.kind, Kind::Path))
                .unwrap(),
        );
        assert_eq!(paths.len(), 6);
        assert_eq!(paths[0].pair, branches[..2]);
        assert_eq!(paths[1].pair, branches[1..]);
        assert_eq!(paths[2].group, "Staged");
        assert_eq!(paths[3].group, "Unstaged");
        assert_eq!(paths[4].group, "Untracked");
        assert!(paths[2..5].iter().all(|hit| {
            hit.pair == [source.repo.checkout.as_str(), WORKTREE]
                && hit.revision.is_none()
                && hit.line.is_none()
                && hit.row.is_none()
        }));
        let unchanged = &paths[5];
        assert_eq!(unchanged.path, "😀 needle docs");
        assert_eq!(
            unchanged.revision.as_deref(),
            Some(source.current.head.as_str())
        );
        assert_eq!((unchanged.from, unchanged.to), (3, 9));
        assert_eq!((unchanged.snippet_from, unchanged.snippet_to), (3, 9));
        assert_eq!(rest[0].sha.as_deref(), Some(source.current.head.as_str()));
        assert!(matches!(rest[0].kind, Kind::Commit));
        assert_eq!(rest[0].text, "needle second commit");
        assert_eq!(
            rest.iter().filter(|h| matches!(h.kind, Kind::Commit)).count(),
            2
        );
        assert!(rest.iter().all(|h| !h.text.contains("only in unchanged file")));
        for group in ["Staged", "Unstaged", "Untracked"] {
            assert!(rest
                .iter()
                .any(|h| h.group == group && matches!(h.kind, Kind::Text)));
        }
        let serialized = serde_json::to_value(&paths[5]).unwrap();
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
        assert!(find(&source, Scope::Stack, "needle draft")
            .hits
            .is_empty());

        let branch = find(&source, Scope::Branch, "needle");
        assert!(branch
            .hits
            .iter()
            .any(|h| h.path == unchanged.path && matches!(h.kind, Kind::Path)));
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
