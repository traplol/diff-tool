//! Search frozen review snapshots outside the workspace lock.
use crate::{
    git::{self, Comparison, Repository, WORKTREE},
    service::Workspace,
};
use regex::{Regex, RegexBuilder};
use serde::{Deserialize, Serialize};
use std::{
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

#[derive(Serialize)]
struct Hit {
    pair: [String; 2],
    base: String,
    head: String,
    revision: Option<String>,
    path: String,
    group: String,
    row: Option<usize>,
    side: &'static str,
    line: usize,
    from: usize,
    to: usize,
    text: String,
}

struct Location<'a> {
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

    fn line(&mut self, c: &Comparison, loc: Location<'_>, text: &str) {
        let mut previous_byte = 0;
        let mut previous_utf16 = 0;
        for hit in self.pattern.find_iter(text) {
            if self.result.hits.len() == LIMIT {
                self.result.truncated = true;
                return;
            }
            let from = previous_utf16 + text[previous_byte..hit.start()].encode_utf16().count();
            let to = from + hit.as_str().encode_utf16().count();
            previous_byte = hit.end();
            previous_utf16 = to;
            let prefix = &text[..hit.start()];
            let start = prefix.char_indices().rev().nth(39).map_or(0, |(i, _)| i);
            let end = text[start..]
                .char_indices()
                .nth(160)
                .map_or(text.len(), |(i, _)| start + i);
            let mut snippet = String::new();
            if start > 0 {
                snippet.push('…');
            }
            snippet.push_str(&text[start..end]);
            if end < text.len() {
                snippet.push('…');
            }
            self.result.hits.push(Hit {
                pair: [c.left.clone(), c.right.clone()],
                base: c.base.clone(),
                head: c.head.clone(),
                revision: loc.row.is_none().then(|| c.branch_tip().to_owned()),
                path: loc.path.into(),
                group: loc.group.into(),
                row: loc.row,
                side: if loc.new.is_some() { "new" } else { "old" },
                line: loc.new.or(loc.old).expect("searchable source line"),
                from,
                to,
                text: snippet,
            });
        }
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
                self.line(
                    c,
                    Location {
                        path: &file.path,
                        group: &file.group,
                        row: Some(row),
                        old: line.old,
                        new: line.new,
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
            self.line(
                c,
                Location {
                    path: &git::name(name),
                    group: "",
                    row: None,
                    old: None,
                    new: Some(n),
                },
                &text,
            );
            if self.result.truncated {
                return Ok(());
            }
        }
    }
}

impl Source {
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
            Scope::Branch => search.tree(&self.repo, c, query)?,
            Scope::Comparison => search.patch(&self.repo, c)?,
            Scope::Stack => {
                let local = c.right == WORKTREE
                    || self.stack.iter().any(|branch| {
                        branch == &self.repo.checkout
                            || (branch == "HEAD" && self.repo.checkout.starts_with("HEAD@"))
                    });
                let layers = self
                    .stack
                    .windows(2)
                    .map(|pair| (pair[0].as_str(), pair[1].as_str()));
                for (left, right) in
                    layers.chain(local.then_some((self.repo.checkout.as_str(), WORKTREE)))
                {
                    search.check()?;
                    if left == c.left && right == c.right {
                        search.patch(&self.repo, c)?;
                    } else {
                        let layer = git::compare(&self.repo, left, right)?;
                        search.patch(&self.repo, &layer)?;
                    }
                    if search.result.truncated {
                        break;
                    }
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
            "😀 NEE[D]LE nee[d]le\nſample\n".as_bytes(),
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
        let find =
            |source: &Source, scope, query| source.search(scope, query, &|| false).unwrap().hits;
        let hits = find(&source, Scope::Branch, "nee[d]le");
        assert_eq!(hits.len(), 2);
        for hit in &hits {
            assert_eq!(hit.path, "unchanged file");
            assert_eq!((hit.row, hit.side, hit.line), (None, "new", 1));
            assert_eq!(hit.revision.as_deref(), Some(source.current.head.as_str()));
        }
        assert_eq!(
            (hits[0].from, hits[0].to, hits[1].from, hits[1].to),
            (3, 11, 12, 20)
        );
        assert_eq!(find(&source, Scope::Branch, "sample")[0].line, 2);
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
