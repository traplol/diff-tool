use crate::{
    git::{self, Change, Comparison, Repository, WORKTREE},
    review::{self, Store},
    suggestions, tracking,
};
use serde::Deserialize;
use serde_json::{json, Value};
use std::{
    collections::{BTreeMap, HashSet},
    path::PathBuf,
};

type Pair = [String; 2];

#[derive(Deserialize)]
#[serde(tag = "op", rename_all = "snake_case")]
pub enum Request {
    Open {
        path: String,
        pair: Option<Pair>,
    },
    Compare {
        pair: Pair,
    },
    Discover {
        base: String,
        branch: String,
    },
    SetStack {
        refs: Vec<String>,
    },
    Patch {
        file: usize,
    },
    DisplayPatch {
        file: usize,
    },
    Commits,
    Details {
        sha: String,
    },
    Viewed {
        file: usize,
        value: bool,
    },
    Width {
        width: i64,
    },
    Create {
        file: usize,
        rows: Vec<usize>,
        side: String,
        body: String,
        suggestion: Option<String>,
    },
    Edit {
        original: Value,
        body: String,
        suggestion: Option<String>,
    },
    Resolve {
        id: i64,
        value: bool,
    },
    Delete {
        id: i64,
    },
    Apply {
        file: usize,
        original: Value,
    },
    Export {
        entire: bool,
    },
}

#[derive(Default)]
pub struct Workspace {
    snapshot: u64,
    session: Option<Session>,
}

struct Session {
    repo: Repository,
    stack: Vec<String>,
    current: Option<Comparison>,
    notes: Vec<Value>,
    locations: BTreeMap<i64, Vec<Value>>,
}

fn pairs(repo: &Repository, stack: &[String]) -> Vec<Pair> {
    let mut pairs: Vec<_> = review::comparisons(stack)
        .into_iter()
        .map(|(left, right)| [left.to_owned(), right.to_owned()])
        .collect();
    pairs.push([repo.checkout.clone(), WORKTREE.into()]);
    pairs
}

impl Session {
    fn comparison(&self) -> Result<&Comparison, String> {
        self.current
            .as_ref()
            .ok_or_else(|| "Choose a comparison first.".into())
    }
    fn file(&self, index: usize) -> Result<(&Comparison, &Change), String> {
        let c = self.comparison()?;
        Ok((
            c,
            c.files
                .get(index)
                .ok_or("The selected file has changed. Refresh and try again.")?,
        ))
    }
    fn reload_notes(&mut self, store: &Store) -> Result<Value, String> {
        self.notes = store.notes(&self.repo)?;
        self.locations =
            tracking::locate_notes(&self.repo, &self.stack, self.current.as_ref(), &self.notes);
        if let Some(c) = &self.current {
            for note in &self.notes {
                let Some(id) = note["id"].as_i64() else {
                    continue;
                };
                if let Some(f) = c
                    .files
                    .iter()
                    .find(|f| review::note_matches_file(c, f, note))
                {
                    let locations = self.locations.entry(id).or_default();
                    if !locations
                        .iter()
                        .any(|d| d["left"] == c.left && d["right"] == c.right)
                    {
                        locations.push(tracking::location_for(c, f, note));
                    }
                }
            }
        }
        Ok(json!({"notes":self.notes,"locations":self.locations}))
    }
    fn load(
        repo: Repository,
        stack: Vec<String>,
        pair: Pair,
        store: &Store,
        token: u64,
    ) -> Result<(Self, Value), String> {
        let mut next = Self {
            repo,
            stack,
            current: None,
            notes: vec![],
            locations: BTreeMap::new(),
        };
        let result = git::compare(&next.repo, &pair[0], &pair[1]);
        let error = result.as_ref().err().cloned();
        next.current = result.ok();
        next.reload_notes(store)?;
        let viewed = next
            .current
            .as_ref()
            .map(|c| store.viewed(&next.repo, c))
            .transpose()?
            .unwrap_or_default();
        let response = json!({"snapshot":token,"repo":next.repo,"stack":next.stack,"pair":pair,
            "comparison":next.current,"notes":next.notes,"locations":next.locations,"viewed":viewed,
            "width":store.sidebar_width()?,"error":error});
        Ok((next, response))
    }
    fn export(&self, store: Option<&Store>, entire: bool) -> Result<Value, String> {
        let saved = store.and_then(|s| s.notes(&self.repo).ok());
        let cached = saved.is_none();
        let all_notes = saved.unwrap_or_else(|| {
            self.notes
                .iter()
                .cloned()
                .map(|mut note| {
                    if let Some(id) = note["id"].as_i64() {
                        review::restore_receipt(&self.repo, id, &mut note);
                    }
                    note
                })
                .collect()
        });
        let review_pairs = pairs(&self.repo, &self.stack);
        let includes_checkout = self.stack.iter().any(|r| {
            r == &self.repo.checkout || (r == "HEAD" && self.repo.checkout.starts_with("HEAD@"))
        });
        let local_only =
            self.current.as_ref().is_some_and(|c| c.right == WORKTREE) && !includes_checkout;
        let notes: Vec<_> = all_notes
            .into_iter()
            .filter(|n| {
                if entire {
                    return true;
                }
                if local_only {
                    return n["left"] == self.repo.checkout && n["right"] == WORKTREE;
                }
                review_pairs
                    .iter()
                    .take(review_pairs.len() - 1)
                    .any(|p| n["left"] == p[0] && n["right"] == p[1])
                    || (n["right"] == WORKTREE
                        && self.stack.iter().any(|r| {
                            n["left"] == *r || (r == "HEAD" && n["left"] == self.repo.checkout)
                        }))
            })
            .collect();
        let locations = git::open_repo(&self.repo.root)
            .map(|fresh| {
                let refs = if self.stack.iter().all(|r| fresh.refs.contains_key(r)) {
                    self.stack.as_slice()
                } else {
                    &[]
                };
                tracking::locate_notes(&fresh, refs, None, &notes)
            })
            .unwrap_or_default();
        let scope = if entire {
            None
        } else if local_only {
            Some(&[][..])
        } else {
            Some(self.stack.as_slice())
        };
        Ok(
            json!({"full":review::markdown(&self.repo,scope,&notes,&locations,false),
            "open":review::markdown(&self.repo,scope,&notes,&locations,true),"cached":cached}),
        )
    }
}

impl Workspace {
    pub fn execute(&mut self, request: Request, snapshot: Option<u64>) -> Result<Value, String> {
        let mut store = match Store::open() {
            Ok(store) => store,
            Err(e) => {
                if let (Some(s), Request::Export { entire }) = (&self.session, &request) {
                    if snapshot == Some(self.snapshot) {
                        return s.export(None, *entire);
                    }
                }
                return Err(e);
            }
        };
        self.with_store(request, snapshot, &mut store)
    }

    fn with_store(
        &mut self,
        request: Request,
        snapshot: Option<u64>,
        store: &mut Store,
    ) -> Result<Value, String> {
        if let Request::Open { path, pair } = request {
            let repo = git::open_repo(PathBuf::from(git::path_arg(&path)?).as_path())?;
            let stack = match store.saved_stack(&repo)? {
                Some(refs) => refs,
                None if repo.initial.len() >= 2 => {
                    let base = repo.default_branch.as_ref().unwrap_or(&repo.initial[0]);
                    let (refs, _) = git::discover_stack(&repo, base, &repo.initial[1])?;
                    if refs.len() >= 2 {
                        refs
                    } else {
                        repo.initial.clone()
                    }
                }
                None => repo.initial.clone(),
            };
            let choices = pairs(&repo, &stack);
            let pair = match pair {
                Some(previous) if previous[1] == WORKTREE => {
                    [repo.checkout.clone(), WORKTREE.into()]
                }
                Some(previous) if choices.contains(&previous) => previous,
                _ => choices[0].clone(),
            };
            let token = self.snapshot + 1;
            let (session, data) = Session::load(repo, stack, pair, store, token)?;
            self.snapshot = token;
            self.session = Some(session);
            return Ok(data);
        }
        if snapshot != Some(self.snapshot) {
            return Err("The review changed. Open the file again.".into());
        }
        let s = self
            .session
            .as_mut()
            .ok_or("Open a Git repository first.")?;
        match request {
            Request::Compare { pair } => {
                if !pairs(&s.repo, &s.stack).contains(&pair) {
                    return Err("Choose a comparison in the current stack.".into());
                }
                let (next, data) = Session::load(
                    s.repo.clone(),
                    s.stack.clone(),
                    pair,
                    store,
                    self.snapshot + 1,
                )?;
                *s = next;
                self.snapshot += 1;
                return Ok(data);
            }
            Request::SetStack { refs } => {
                if refs.len() < 2
                    || refs.iter().collect::<HashSet<_>>().len() != refs.len()
                    || refs[1..].iter().any(|r| r == git::EMPTY)
                    || !refs.iter().all(|r| s.repo.refs.contains_key(r))
                {
                    return Err("Choose a base and at least one distinct head.".into());
                }
                let pair = pairs(&s.repo, &refs)[0].clone();
                let (next, data) =
                    Session::load(s.repo.clone(), refs, pair, store, self.snapshot + 1)?;
                store.set_stack(&next.repo, &next.stack)?;
                *s = next;
                self.snapshot += 1;
                return Ok(data);
            }
            Request::Discover { base, branch } => {
                return Ok(json!(git::discover_stack(&s.repo, &base, &branch)?))
            }
            Request::Patch { file } => {
                let (c, f) = s.file(file)?;
                return Ok(json!(git::patch(&s.repo, c, f)?));
            }
            Request::DisplayPatch { file } => {
                let (c, f) = s.file(file)?;
                return Ok(json!(git::display_patch(&s.repo, c, f)?));
            }
            Request::Commits => return Ok(json!(git::commits(&s.repo, s.comparison()?)?)),
            Request::Details { sha } => return Ok(json!(git::commit_details(&s.repo, &sha)?)),
            Request::Width { width } => {
                store.set_sidebar_width(width.clamp(150, 800))?;
                return Ok(Value::Null);
            }
            Request::Viewed { file, value } => {
                let (c, f) = s.file(file)?;
                store.set_viewed(&s.repo, c, f, value)?;
                return Ok(Value::Null);
            }
            Request::Export { entire } => return s.export(Some(store), entire),
            Request::Create {
                file,
                rows,
                side,
                body,
                suggestion,
            } => {
                if !["old", "new", "both"].contains(&side.as_str()) {
                    return Err("Invalid selection side.".into());
                }
                let (c, f) = s.file(file)?;
                let patch = git::patch(&s.repo, c, f)?;
                if rows.windows(2).any(|r| r[0] >= r[1]) {
                    return Err("Select lines in patch order.".into());
                }
                let selected: Vec<_> = rows
                    .iter()
                    .map(|&i| {
                        patch
                            .get(i)
                            .cloned()
                            .ok_or("Selection changed. Refresh the file.")
                    })
                    .collect::<Result<_, _>>()?;
                let mut note = review::make_note(c, f, &selected, &side, body.trim(), &patch);
                if let Some(code) = suggestion {
                    let mut previous = None;
                    for row in &selected {
                        let n = row.new.ok_or("Select consecutive new-side lines.")?;
                        if previous.is_some_and(|(p, h)| n != p + 1 || row.hunk != h) {
                            return Err("Select consecutive lines in one hunk.".into());
                        }
                        previous = Some((n, row.hunk));
                    }
                    if side == "old"
                        || selected.is_empty()
                        || !["100644", "100755"].contains(&f.mode.as_str())
                    {
                        return Err("Select new-side lines in a regular file.".into());
                    }
                    if !code.is_empty() && code == review::suggestion_source(&note) {
                        return Err("Edit the replacement first.".into());
                    }
                    note["suggestion"] = json!(code);
                } else if body.trim().is_empty() {
                    return Err("Enter a comment.".into());
                }
                store.save(&s.repo, &note, None)?;
            }
            Request::Edit {
                original,
                body,
                suggestion,
            } => {
                let mut edited = original.clone();
                edited["body"] = json!(body.trim());
                if let Some(code) = suggestion {
                    if !code.is_empty()
                        && code == review::suggestion_source(&original)
                        && original.get("applied_location").is_none()
                    {
                        return Err("Edit the replacement first.".into());
                    }
                    edited["suggestion"] = json!(code);
                } else if body.trim().is_empty() {
                    return Err("Enter a comment.".into());
                }
                store.save(&s.repo, &edited, Some(&original))?;
            }
            Request::Resolve { id, value } => {
                if !store.set_resolved(&s.repo, id, value)? {
                    return Err("This comment was deleted. Refresh the review.".into());
                }
            }
            Request::Delete { id } => {
                store.delete(&s.repo, id)?;
            }
            Request::Apply { file, original } => {
                let (c, f) = s.file(file)?;
                let id = original["id"]
                    .as_i64()
                    .ok_or("Choose a saved suggestion.")?;
                let saved = s
                    .notes
                    .iter()
                    .find(|n| n["id"] == id)
                    .ok_or("Suggestion was removed.")?;
                if original["suggestion"] != saved["suggestion"] {
                    return Err("The suggestion changed. Reopen it first.".into());
                }
                let dest = s
                    .locations
                    .get(&id)
                    .into_iter()
                    .flatten()
                    .find(|d| {
                        d["left"] == c.left
                            && d["right"] == c.right
                            && d["path"] == f.path
                            && d["group"] == f.group
                    })
                    .ok_or("This suggestion has no verified location in the selected file.")?;
                let mut anchor = saved.clone();
                anchor["new"] = dest["new"].clone();
                anchor["old"] = dest["old"].clone();
                suggestions::apply(store, &s.repo, c, f, saved, &anchor)?;
            }
            Request::Open { .. } => unreachable!(),
        }
        s.reload_notes(store)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{fs, process::Command};

    #[test]
    fn rejects_edits_from_old_views_and_keeps_worktree_on_checkout_switch() {
        let dir = tempfile::tempdir().unwrap();
        let repo = dir.path().join("repo");
        fs::create_dir(&repo).unwrap();
        let git = |args: &[&str]| {
            assert!(Command::new("git")
                .arg("-C")
                .arg(&repo)
                .args(args)
                .output()
                .unwrap()
                .status
                .success())
        };
        git(&["init", "-b", "main"]);
        fs::write(repo.join("code"), "one\n").unwrap();
        git(&["add", "code"]);
        git(&[
            "-c",
            "user.name=Test",
            "-c",
            "user.email=a@b.test",
            "-c",
            "commit.gpgSign=false",
            "commit",
            "-m",
            "initial",
        ]);
        fs::write(repo.join("code"), "two\n").unwrap();
        let mut store = Store::at(&dir.path().join("reviews")).unwrap();
        let mut workspace = Workspace::default();
        let open = |pair| Request::Open {
            path: git::path_name(&repo),
            pair,
        };
        let first = workspace
            .with_store(
                open(Some(["refs/heads/main".into(), WORKTREE.into()])),
                None,
                &mut store,
            )
            .unwrap();
        assert_eq!(first["comparison"]["files"][0]["group"], "Unstaged");
        let token = first["snapshot"].as_u64();
        let updated = workspace
            .with_store(
                Request::Create {
                    file: 0,
                    rows: vec![],
                    side: "both".into(),
                    body: "Original review".into(),
                    suggestion: None,
                },
                token,
                &mut store,
            )
            .unwrap();
        let id = updated["notes"][0]["id"].as_i64().unwrap();
        git(&["switch", "-c", "topic"]);
        let next = workspace
            .with_store(
                open(Some(["refs/heads/main".into(), WORKTREE.into()])),
                token,
                &mut store,
            )
            .unwrap();
        assert_eq!(next["pair"], json!(["refs/heads/topic", WORKTREE]));
        assert!(workspace
            .with_store(Request::Delete { id }, token, &mut store)
            .is_err());
        let exported = workspace
            .with_store(
                Request::Export { entire: true },
                next["snapshot"].as_u64(),
                &mut store,
            )
            .unwrap();
        assert!(exported["open"]
            .as_str()
            .unwrap()
            .contains("Original review"));
    }

    #[test]
    fn failed_comparison_load_keeps_previous_snapshot_and_export() {
        let dir = tempfile::tempdir().unwrap();
        let repo = dir.path().join("repo");
        assert!(Command::new("git")
            .args(["init", "-b", "main"])
            .arg(&repo)
            .output()
            .unwrap()
            .status
            .success());
        fs::write(repo.join("new.txt"), "working file").unwrap();
        let data = dir.path().join("data");
        let mut store = Store::at(&data).unwrap();
        let mut workspace = Workspace::default();
        let reply = workspace
            .with_store(
                Request::Open {
                    path: git::path_name(&repo),
                    pair: None,
                },
                None,
                &mut store,
            )
            .unwrap();
        let token = reply["snapshot"].as_u64();
        workspace
            .with_store(
                Request::Create {
                    file: 0,
                    rows: vec![],
                    side: "both".into(),
                    body: "Keep this draft".into(),
                    suggestion: None,
                },
                token,
                &mut store,
            )
            .unwrap();
        // A broken preferences table fails after Git and note loading finished.
        let db = rusqlite::Connection::open(data.join("reviews.sqlite3")).unwrap();
        db.execute("ALTER TABLE preferences RENAME TO missing_preferences", [])
            .unwrap();
        let pair = ["refs/heads/main".into(), WORKTREE.into()];
        assert!(workspace
            .with_store(Request::Compare { pair }, token, &mut store)
            .is_err());
        let patch = workspace
            .with_store(Request::Patch { file: 0 }, token, &mut store)
            .unwrap();
        assert!(patch
            .as_array()
            .unwrap()
            .iter()
            .any(|line| line["text"] == "working file"));
        // Preserve the editable preview even if the saved checkout and database are unavailable.
        fs::rename(&repo, dir.path().join("moved")).unwrap();
        let report = workspace
            .session
            .as_ref()
            .unwrap()
            .export(None, true)
            .unwrap();
        assert_eq!(report["cached"], true);
        assert!(report["full"].as_str().unwrap().contains("Keep this draft"));
    }

    #[cfg(unix)]
    #[test]
    fn non_utf8_checkout_root_roundtrips_through_desktop_commands() {
        use std::{ffi::OsString, os::unix::ffi::OsStringExt};
        let dir = tempfile::tempdir().unwrap();
        let repo = dir.path().join(OsString::from_vec(b"repo-\xff".to_vec()));
        assert!(Command::new("git")
            .arg("init")
            .arg(&repo)
            .output()
            .unwrap()
            .status
            .success());
        let mut store = Store::at(&dir.path().join("data")).unwrap();
        let mut workspace = Workspace::default();
        let path = git::path_name(&repo);
        let result = workspace
            .with_store(
                Request::Open {
                    path: path.clone(),
                    pair: None,
                },
                None,
                &mut store,
            )
            .unwrap();
        assert_eq!(result["repo"]["root"], path);
    }
}
