use crate::{
    config::{self, Layout, RepoSettings, Settings},
    git::{self, Change, Comparison, Repository, WORKTREE},
    review::{self, Store},
    suggestions, tracking,
};
use serde::Deserialize;
use serde_json::{json, Value};
use std::{
    collections::{BTreeMap, HashSet},
    path::{Path, PathBuf},
    sync::Arc,
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
    FileContents {
        file: usize,
    },
    BranchFile {
        path: String,
        revision: String,
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
    Layout {
        layout: Layout,
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
    config_path: Option<PathBuf>,
}

struct Session {
    repo: Repository,
    stack: Vec<String>,
    current: Option<Arc<Comparison>>,
    search_comparisons: crate::search::PreparedComparisons,
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

fn repo_settings(
    repo: &Repository,
    store: &Store,
    path: &Path,
) -> Result<(Settings, Option<String>), String> {
    let key = git::path_name(&repo.root);
    let (existing, warning) = match config::read(path) {
        Ok(Some(settings))
            if settings.sidebar_width.is_some() && settings.repositories.contains_key(&key) =>
        {
            return Ok((settings, None))
        }
        Ok(existing) => (existing, None),
        Err(e) => (None, Some(e)),
    };
    // Keep the user's base even if an old SQLite stack names a deleted layer.
    let mut imported = RepoSettings::default();
    if let Some(stack) = store.saved_stack(repo)? {
        imported.base_branch = stack[0].clone();
        if stack.iter().all(|r| repo.refs.contains_key(r)) {
            imported.layers = stack[1..].to_vec();
        }
    } else if let Some(base) = &repo.default_branch {
        imported.base_branch = base.clone();
    }
    let legacy_width = if existing.as_ref().and_then(|s| s.sidebar_width).is_none() {
        Some(store.sidebar_width()?)
    } else {
        None
    };
    let migrate = |settings: &mut Settings| {
        if let Some(width) = legacy_width {
            settings.sidebar_width.get_or_insert(width.clamp(150, 800));
        }
        settings
            .repositories
            .entry(key.clone())
            .or_insert_with(|| imported.clone());
    };
    let warning = match warning {
        Some(e) => e,
        None => match config::update(path, migrate) {
            Ok(settings) => return Ok((settings, None)),
            Err(e) => e,
        },
    };
    // A malformed or unwritable config should still allow reading the review.
    let mut fallback = existing.unwrap_or_default();
    migrate(&mut fallback);
    Ok((fallback, Some(warning)))
}

fn open_stack(repo: &Repository, saved: &RepoSettings) -> Result<Vec<String>, String> {
    if repo.initial.len() < 2 {
        return Ok(repo.initial.clone());
    }
    let resolve = |name: &str| {
        [
            name.to_owned(),
            format!("refs/heads/{name}"),
            format!("refs/remotes/{name}"),
        ]
        .into_iter()
        .find(|r| repo.refs.contains_key(r))
    };
    let preferred = resolve(&saved.base_branch);
    if let Some(base) = &preferred {
        let mut stack = vec![base.clone()];
        for layer in &saved.layers {
            let Some(r) = resolve(layer) else {
                break;
            };
            if r == git::EMPTY || stack.contains(&r) {
                break;
            }
            stack.push(r);
        }
        if stack.len() >= 2 && stack.len() == saved.layers.len() + 1 {
            return Ok(stack);
        }
    }
    let base = preferred
        .as_ref()
        .or(repo.default_branch.as_ref())
        .unwrap_or(&repo.initial[0]);
    let head = &repo.initial[1];
    let (mut refs, _) = git::discover_stack(repo, base, head)?;
    if preferred.is_some() && base != head && !refs.contains(base) {
        refs.insert(0, base.clone());
    }
    // A chosen base can outlive every layer. Keep it in the stack editor and
    // offer the working tree while the base itself is checked out.
    let chosen_base_only = preferred.as_ref() == Some(head)
        && (!saved.layers.is_empty() || preferred != repo.default_branch);
    Ok(if refs.len() >= 2 || chosen_base_only {
        refs
    } else {
        repo.initial.clone()
    })
}

impl Session {
    fn comparison(&self) -> Result<&Comparison, String> {
        self.current
            .as_deref()
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
        self.locations = tracking::locate_notes(
            &self.repo,
            &self.stack,
            self.current.as_deref(),
            &self.notes,
        );
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
            search_comparisons: Default::default(),
            notes: vec![],
            locations: BTreeMap::new(),
        };
        let result = git::compare(&next.repo, &pair[0], &pair[1]);
        let error = result.as_ref().err().cloned();
        next.current = result.ok().map(Arc::new);
        next.reload_notes(store)?;
        let viewed = next
            .current
            .as_ref()
            .map(|c| store.viewed(&next.repo, c))
            .transpose()?
            .unwrap_or_default();
        let response = json!({"snapshot":token,"repo":next.repo,"stack":next.stack,"pair":pair,
            "comparison":next.current.as_deref(),"notes":next.notes,"locations":next.locations,"viewed":viewed,
            "error":error});
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
    pub(crate) fn search_source(&self, snapshot: u64) -> Result<crate::search::Source, String> {
        if self.snapshot != snapshot {
            return Err("The review changed. Run the search again.".into());
        }
        let session = self
            .session
            .as_ref()
            .ok_or("Open a Git repository first.")?;
        Ok(crate::search::Source {
            repo: session.repo.clone(),
            stack: session.stack.clone(),
            current: session
                .current
                .clone()
                .ok_or("Choose a comparison first.")?,
            comparisons: session.search_comparisons.clone(),
        })
    }

    fn settings_file(&self) -> Result<PathBuf, String> {
        self.config_path.clone().map_or_else(config::path, Ok)
    }

    pub fn execute(&mut self, request: Request, snapshot: Option<u64>) -> Result<Value, String> {
        match request {
            Request::Layout { layout } => {
                config::update(&self.settings_file()?, |settings| {
                    settings.diff_layout = layout
                })?;
                return Ok(Value::Null);
            }
            Request::Width { width } => {
                config::update(&self.settings_file()?, |settings| {
                    settings.sidebar_width = Some(width.clamp(150, 800))
                })?;
                return Ok(Value::Null);
            }
            _ => {}
        }
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
            let (settings, warning) = repo_settings(&repo, store, &self.settings_file()?)?;
            let stack = open_stack(&repo, &settings.repositories[&git::path_name(&repo.root)])?;
            let choices = pairs(&repo, &stack);
            let pair = match pair {
                Some(previous) if previous[1] == WORKTREE => {
                    [repo.checkout.clone(), WORKTREE.into()]
                }
                Some(previous) if choices.contains(&previous) => previous,
                _ => choices[0].clone(),
            };
            let token = self.snapshot + 1;
            let (session, mut data) = Session::load(repo, stack, pair, store, token)?;
            data["width"] = json!(settings.sidebar_width.unwrap_or(320));
            data["diff_layout"] = json!(settings.diff_layout);
            data["config_warning"] = json!(warning);
            self.snapshot = token;
            self.session = Some(session);
            return Ok(data);
        }
        if snapshot != Some(self.snapshot) {
            return Err("The review changed. Open the file again.".into());
        }
        let config_path = self.config_path.as_deref();
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
                let path = config_path
                    .map(PathBuf::from)
                    .map_or_else(config::path, Ok)?;
                config::update(&path, |settings| {
                    let repo = settings
                        .repositories
                        .entry(git::path_name(&next.repo.root))
                        .or_default();
                    repo.base_branch = next.stack[0].clone();
                    repo.layers = next.stack[1..].to_vec();
                })?;
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
            Request::FileContents { file } => {
                let (_, f) = s.file(file)?;
                return Ok(json!(git::file_contents(&s.repo, f)?));
            }
            Request::BranchFile { path, revision } => {
                if revision != s.comparison()?.branch_tip() {
                    return Err("The branch changed. Search again.".into());
                }
                return Ok(json!(git::revision_file(&s.repo, &revision, &path)?));
            }
            Request::Commits => return Ok(json!(git::commits(&s.repo, s.comparison()?)?)),
            Request::Details { sha } => return Ok(json!(git::commit_details(&s.repo, &sha)?)),
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
            Request::Open { .. } | Request::Width { .. } | Request::Layout { .. } => unreachable!(),
        }
        s.reload_notes(store)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{fs, process::Command};

    fn workspace_in(dir: &Path) -> Workspace {
        Workspace {
            config_path: Some(dir.join("config/branchline/config.json")),
            ..Workspace::default()
        }
    }

    #[test]
    fn search_preparation_is_shared_only_within_the_loaded_session() {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path().join("repo");
        fs::create_dir(&root).unwrap();
        let git = |args: &[&str]| git::git(&root, args).unwrap();
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
        let refs = ["refs/heads/main".into(), "refs/heads/review".into()];
        let open = || Request::Open {
            path: git::path_name(&root),
            pair: Some(refs.clone()),
        };
        let mut store = Store::at(&dir.path().join("reviews")).unwrap();
        let mut workspace = workspace_in(dir.path());
        let first = workspace.with_store(open(), None, &mut store).unwrap();
        let first_token = first["snapshot"].as_u64().unwrap();
        let before = workspace.search_source(first_token).unwrap();
        let next_query = workspace.search_source(first_token).unwrap();
        assert!(Arc::ptr_eq(&before.comparisons, &next_query.comparisons));
        fs::write(root.join("code"), "new commit\n").unwrap();
        git(&["commit", "-qam", "advance review"]);
        fs::write(root.join("code"), "new staged\n").unwrap();
        git(&["add", "code"]);
        fs::write(root.join("code"), "new local\n").unwrap();
        let refresh = workspace.with_store(open(), None, &mut store).unwrap();
        let fresh_token = refresh["snapshot"].as_u64().unwrap();
        let refreshed = workspace.search_source(fresh_token).unwrap();
        assert!(!Arc::ptr_eq(&before.comparisons, &refreshed.comparisons));
        assert_ne!(before.current.head, refreshed.current.head);
        before
            .comparisons
            .lock()
            .unwrap()
            .insert(refs.clone(), before.current.clone());
        assert!(refreshed.comparisons.lock().unwrap().is_empty());
        let local = workspace
            .with_store(
                Request::Compare {
                    pair: ["refs/heads/review".into(), WORKTREE.into()],
                },
                Some(fresh_token),
                &mut store,
            )
            .unwrap();
        let local_token = local["snapshot"].as_u64().unwrap();
        let selected = workspace.search_source(local_token).unwrap();
        assert!(!Arc::ptr_eq(&refreshed.comparisons, &selected.comparisons));
        assert_eq!(selected.current.base, refreshed.current.head);
        for (group, text) in [("Staged", "new staged"), ("Unstaged", "new local")] {
            let file = selected
                .current
                .files
                .iter()
                .find(|f| f.group == group)
                .unwrap();
            assert!(git::patch(&selected.repo, &selected.current, file)
                .unwrap()
                .iter()
                .any(|line| line.text == text));
        }
        let stack = workspace
            .with_store(
                Request::SetStack { refs: refs.into() },
                Some(local_token),
                &mut store,
            )
            .unwrap();
        let reset = workspace
            .search_source(stack["snapshot"].as_u64().unwrap())
            .unwrap();
        assert!(!Arc::ptr_eq(&selected.comparisons, &reset.comparisons));
        assert!(reset.comparisons.lock().unwrap().is_empty());
    }
    #[test]
    fn migrates_preferences_and_keeps_the_selected_base_after_a_layer_is_deleted() {
        let dir = tempfile::tempdir().unwrap();
        let repo = dir.path().join("repo");
        fs::create_dir(&repo).unwrap();
        let git = |args: &[&str]| {
            let result = Command::new("git")
                .arg("-C")
                .arg(&repo)
                .args(args)
                .output()
                .unwrap();
            assert!(
                result.status.success(),
                "{}",
                String::from_utf8_lossy(&result.stderr)
            );
        };
        git(&["init", "-b", "main"]);
        git(&[
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgSign=false",
            "commit",
            "--allow-empty",
            "-m",
            "Base",
        ]);
        git(&["branch", "integration"]);
        git(&["switch", "-c", "feature"]);
        let root = git::path_name(&git::open_repo(&repo).unwrap().root);
        let open = || Request::Open {
            path: root.clone(),
            pair: None,
        };
        let data = dir.path().join("data");
        let mut store = Store::at(&data).unwrap();
        let db = rusqlite::Connection::open(data.join("reviews.sqlite3")).unwrap();
        db.execute("INSERT INTO preferences VALUES('sidebar_width', 366)", [])
            .unwrap();
        let old_stack = json!(["refs/heads/main", "refs/heads/feature"]);
        db.execute(
            "INSERT INTO stacks VALUES(?,?)",
            rusqlite::params![root.as_bytes(), old_stack.to_string()],
        )
        .unwrap();
        let mut first = workspace_in(dir.path());
        let path = first.settings_file().unwrap();
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(&path, r#"{"hardware_acceleration":false}"#).unwrap();
        let state = first.with_store(open(), None, &mut store).unwrap();
        assert_eq!(state["stack"], old_stack);
        assert_eq!(state["width"], 366);
        assert!(!config::read(&path).unwrap().unwrap().hardware_acceleration);
        let stack = vec![
            String::from("refs/heads/integration"),
            String::from("refs/heads/feature"),
        ];
        first
            .with_store(
                Request::SetStack {
                    refs: stack.clone(),
                },
                state["snapshot"].as_u64(),
                &mut store,
            )
            .unwrap();
        first
            .execute(
                Request::Layout {
                    layout: Layout::Split,
                },
                None,
            )
            .unwrap();
        first.execute(Request::Width { width: 401 }, None).unwrap();
        let mut next = workspace_in(dir.path());
        let reopened = next.with_store(open(), None, &mut store).unwrap();
        assert_eq!(reopened["stack"], json!(stack));
        assert_eq!(reopened["width"], 401);
        assert_eq!(reopened["diff_layout"], "split");
        git(&["switch", "-c", "next-feature"]);
        git(&["branch", "-d", "feature"]);
        let reloaded = next.with_store(open(), None, &mut store).unwrap();
        assert_eq!(
            reloaded["stack"],
            json!(["refs/heads/integration", "refs/heads/next-feature"])
        );
        git(&["switch", "integration"]);
        git(&["branch", "-d", "next-feature"]);
        let base_only = next.with_store(open(), None, &mut store).unwrap();
        assert_eq!(base_only["stack"], json!(["refs/heads/integration"]));
        assert_eq!(
            base_only["pair"],
            json!(["refs/heads/integration", WORKTREE])
        );
        git(&["switch", "-c", "next-feature"]);
        let path = next.settings_file().unwrap();
        let mut manual: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        manual["repositories"][&root]["base_branch"] = json!("main");
        fs::write(&path, manual.to_string()).unwrap();
        let edited = next.with_store(open(), None, &mut store).unwrap();
        assert_eq!(edited["stack"][0], "refs/heads/main");
        fs::write(&path, r#"{"sidebar_width":320}"#).unwrap();
        let explicit = next.with_store(open(), None, &mut store).unwrap();
        assert_eq!(explicit["width"], 320);
        fs::write(&path, b"unclosed {").unwrap();
        let fallback = next.with_store(open(), None, &mut store).unwrap();
        assert!(fallback["config_warning"]
            .as_str()
            .unwrap()
            .contains("config.json"));
        assert!(fallback["comparison"].is_object());
        assert!(next.execute(Request::Width { width: 350 }, None).is_err());
        assert_eq!(fs::read(path).unwrap(), b"unclosed {");
    }

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
        let mut workspace = workspace_in(dir.path());
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
        let mut workspace = workspace_in(dir.path());
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
        // A broken viewed table fails after Git and note loading finished.
        let db = rusqlite::Connection::open(data.join("reviews.sqlite3")).unwrap();
        db.execute("ALTER TABLE viewed RENAME TO missing_viewed", [])
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
        let mut workspace = workspace_in(dir.path());
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
