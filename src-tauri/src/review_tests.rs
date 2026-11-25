use super::*;
use crate::{git, suggestions, tracking};
use std::process::Command;
use tempfile::TempDir;

struct Checkout {
    tmp: TempDir,
    root: PathBuf,
}
impl Checkout {
    fn new() -> Self {
        let tmp = tempfile::tempdir().unwrap();
        let root = tmp.path().join("checkout");
        fs::create_dir(&root).unwrap();
        let fixture = Self { tmp, root };
        fixture.git(&["init", "-q", "-b", "main"]);
        fixture.git(&["config", "user.email", "test@example.invalid"]);
        fixture.git(&["config", "user.name", "Test"]);
        fixture.git(&["config", "core.autocrlf", "false"]);
        fixture.write("settings", "top\nlimit = 1\nbottom\n");
        fixture.commit("Base");
        fixture.git(&["switch", "-qc", "feature"]);
        fixture
    }
    fn git(&self, args: &[&str]) {
        let result = Command::new("git")
            .arg("-C")
            .arg(&self.root)
            .args(args)
            .output()
            .unwrap();
        assert!(
            result.status.success(),
            "{args:?}: {}",
            String::from_utf8_lossy(&result.stderr)
        );
    }
    fn write(&self, name: &str, text: &str) {
        fs::write(self.root.join(name), text).unwrap();
    }
    fn commit(&self, msg: &str) {
        self.git(&["add", "--all"]);
        self.git(&["commit", "-qm", msg]);
    }
    fn repo(&self) -> Repository {
        git::open_repo(&self.root).unwrap()
    }
    fn store(&self) -> Store {
        Store::at(&self.tmp.path().join("state")).unwrap()
    }
    fn diff(&self, repo: &Repository) -> Comparison {
        git::compare(repo, &repo.checkout, WORKTREE).unwrap()
    }
}
fn changed_note(repo: &Repository, c: &Comparison, file: &Change) -> Value {
    let lines = git::patch(repo, c, file).unwrap();
    let selected = lines
        .iter()
        .filter(|l| l.kind == "+")
        .cloned()
        .collect::<Vec<_>>();
    make_note(c, file, &selected, "new", "Review this", &lines)
}

#[test]
fn unchanged_modified_anchors_share_one_scoped_read_and_reuse_primary() {
    for mode in 0..3 {
        let t = Checkout::new();
        t.write("second", "base\n");
        t.commit("Add another tracked path");
        t.write("second", "changed\n");
        t.write("settings", "top\nlimit = 2\nbottom\n");
        if mode > 0 {
            t.git(&["add", "settings"]);
        }
        if mode == 2 {
            t.write("settings", "top\nlimit = 3\nbottom\n");
        }
        let repo = t.repo();
        let full = t.diff(&repo);
        let notes = (0..100)
            .map(|id| {
                let mut note = changed_note(&repo, &full, &full.files[id % full.files.len()]);
                note["id"] = json!(id as i64);
                note
            })
            .collect::<Vec<_>>();
        let index = fs::read(t.root.join(".git/index")).unwrap();
        git::take_working_tree_read_counts();
        let located = tracking::locate_notes(&repo, &repo.initial, None, &notes);
        assert_eq!(git::take_working_tree_read_counts(), (0, 1));
        assert_eq!(located.len(), 100);
        for note in &notes {
            let location = &located[&note["id"].as_i64().unwrap()][0];
            assert_eq!(location["new"], note["new"]);
            assert_eq!(location["group"], note["group"]);
        }
        assert_eq!(fs::read(t.root.join(".git/index")).unwrap(), index);
        // The visible WT snapshot is authoritative, even if the disk changes.
        t.write("settings", "external edit\n");
        let located = tracking::locate_notes(&repo, &repo.initial, Some(&full), &notes);
        assert_eq!(git::take_working_tree_read_counts(), (0, 0));
        assert!(located.values().all(|locations| locations.len() == 1));
    }
}

#[test]
fn scoped_worktree_keeps_frozen_payloads_and_never_updates_the_index() {
    for cli in [false, true] {
        let t = Checkout::new();
        if cli {
            t.git(&["config", "diff.algorithm", "minimal"]);
        }
        t.write("literal[1]", "base\n");
        t.commit("Add literal path");
        t.write("settings", "top\nlimit = 2\nbottom\n");
        t.write("literal[1]", "staged\n");
        t.git(&["add", "literal[1]"]);
        t.write("literal[1]", "unstaged\n");
        let repo = t.repo();
        let paths = HashSet::from(["literal[1]".to_string()]);
        let index = fs::read(t.root.join(".git/index")).unwrap();
        let scoped = git::working_tree_paths(&repo, &repo.checkout, &paths).unwrap();
        assert_eq!(scoped.files.len(), 2);
        assert!(scoped
            .files
            .iter()
            .all(|file| file.path == "literal[1]" && file.status == "M"));
        let patches = scoped
            .files
            .iter()
            .map(|file| git::patch(&repo, &scoped, file).unwrap())
            .collect::<Vec<_>>();
        assert_eq!(fs::read(t.root.join(".git/index")).unwrap(), index);
        t.write("literal[1]", "later\n");
        t.git(&["add", "literal[1]"]);
        for (file, patch) in scoped.files.iter().zip(patches) {
            let frozen = git::patch(&repo, &scoped, file).unwrap();
            assert_eq!(
                serde_json::to_value(frozen).unwrap(),
                serde_json::to_value(patch).unwrap()
            );
        }
        // A stale checkout view must still fail the shared checkout guard.
        t.git(&["switch", "-qc", "other"]);
        assert!(git::working_tree_paths(&repo, &repo.checkout, &paths).is_err());
    }
}

#[test]
fn changed_modified_anchors_fall_back_for_external_edits_stage_and_commit() {
    let t = Checkout::new();
    t.write("settings", "top\nlimit = 2\nbottom\n");
    let repo = t.repo();
    let full = t.diff(&repo);
    let mut note = changed_note(&repo, &full, &full.files[0]);
    note["id"] = json!(1);
    t.write("settings", "header\ntop\nlimit = 2\nbottom\n");
    for step in 0..3 {
        if step == 1 {
            t.git(&["add", "settings"]);
        }
        if step == 2 {
            t.commit("Commit reviewed change");
        }
        let current = t.repo();
        git::take_working_tree_read_counts();
        let located = tracking::locate_notes(
            &current,
            &current.initial,
            None,
            std::slice::from_ref(&note),
        );
        assert_eq!(git::take_working_tree_read_counts(), (1, 1));
        assert_eq!(located[&1].len(), 1);
        assert_eq!(located[&1][0]["new"], json!([3, 3]));
        assert_eq!(
            located[&1][0]["right"],
            if step == 2 {
                current.checkout.as_str()
            } else {
                WORKTREE
            }
        );
        if step < 2 {
            assert_eq!(
                located[&1][0]["group"],
                if step == 0 { "Unstaged" } else { "Staged" }
            );
        }
    }
}

#[test]
fn exact_modified_anchor_with_unrelated_history_uses_full_lookup() {
    let t = Checkout::new();
    t.write("settings", "top\nlimit = 2\nbottom\n");
    let repo = t.repo();
    let full = t.diff(&repo);
    let mut note = changed_note(&repo, &full, &full.files[0]);
    note["id"] = json!(1);
    let unrelated = git::git(
        &t.root,
        &["commit-tree", "HEAD^{tree}", "-m", "Unrelated root"],
    )
    .unwrap();
    note["left_tip"] = json!(String::from_utf8(unrelated).unwrap().trim());
    git::take_working_tree_read_counts();
    let located = tracking::locate_notes(&repo, &repo.initial, None, &[note]);
    assert_eq!(git::take_working_tree_read_counts(), (1, 1));
    assert_eq!(located[&1].len(), 1);
}

#[test]
fn added_and_renamed_anchors_use_full_rename_detection() {
    for rename in [false, true] {
        let t = Checkout::new();
        t.git(&["config", "diff.algorithm", "minimal"]);
        t.write("source", "unique source content\n");
        t.commit("Add rename source");
        if rename {
            t.git(&["mv", "source", "destination"]);
        } else {
            t.write("destination", "unique source content\n");
            t.git(&["add", "destination"]);
        }
        let repo = t.repo();
        let initial = t.diff(&repo);
        let file = initial
            .files
            .iter()
            .find(|file| file.path == "destination")
            .unwrap();
        assert_eq!(file.status, if rename { "R" } else { "A" });
        let mut note = changed_note(&repo, &initial, file);
        note["id"] = json!(1);
        if rename {
            t.write("aaa", "unique source content\n");
            t.git(&["add", "aaa"]);
        } else {
            t.git(&["rm", "-q", "source"]);
        }
        // Scoped rename detection can preserve the obsolete A/R identity.
        let paths = HashSet::from([file.path.clone(), file.old.clone()]);
        let scoped = git::working_tree_paths(&repo, &repo.checkout, &paths).unwrap();
        assert!(scoped
            .files
            .iter()
            .any(|file| note_matches_file(&scoped, file, &note)));
        let full = t.diff(&repo);
        assert!(!full
            .files
            .iter()
            .any(|file| note_matches_file(&full, file, &note)));
        let expected = tracking::locate_notes(
            &repo,
            &repo.initial,
            Some(&full),
            std::slice::from_ref(&note),
        );
        git::take_working_tree_read_counts();
        let actual =
            tracking::locate_notes(&repo, &repo.initial, None, std::slice::from_ref(&note));
        assert_eq!(git::take_working_tree_read_counts(), (1, 0));
        assert_eq!(actual, expected);
    }
}

#[test]
fn replies_preserve_desktop_edits_and_can_resolve_the_same_thread() {
    let t = Checkout::new();
    t.write("settings", "top\nlimit = 2\nbottom\n");
    let repo = t.repo();
    let comparison = t.diff(&repo);
    let mut desktop = t.store();
    let mut agent = t.store();
    let note = changed_note(&repo, &comparison, &comparison.files[0]);
    let id = desktop.save(&repo, &note, None).unwrap();
    let original = desktop.note(&repo, id).unwrap().unwrap();
    agent
        .reply(&repo, id, "Agent", "Changed the limit.", Some(true))
        .unwrap();
    let mut edited = original.clone();
    edited["body"] = json!("Clarified the review request");
    desktop.save(&repo, &edited, Some(&original)).unwrap();
    agent
        .reply(&repo, id, "Agent", "Checked the tests.", None)
        .unwrap();
    assert!(desktop
        .notes_after(&repo, 0, Some(false), 10)
        .unwrap()
        .is_empty());
    let saved = desktop.note(&repo, id).unwrap().unwrap();
    assert_eq!(saved["body"], edited["body"]);
    assert_eq!(saved["resolved"], true);
    assert_eq!(
        saved["replies"],
        json!([
            {"author": "Agent", "body": "Changed the limit."},
            {"author": "Agent", "body": "Checked the tests."}
        ])
    );
    assert!(agent.reply(&repo, id, "Agent", "   ", Some(false)).is_err());
    assert_eq!(desktop.note(&repo, id).unwrap().unwrap(), saved);
    assert!(desktop.set_resolved(&repo, id, false).unwrap());
    assert_eq!(
        agent.notes_after(&repo, 0, Some(false), 10).unwrap()[0]["id"],
        id
    );
    let report = markdown(&repo, None, &[saved], &Locations::new(), false);
    assert!(report.contains("Reply from Agent"));
    assert!(report.contains("Checked the tests."));
}

#[test]
fn migrates_existing_json_notes_and_merges_concurrent_edits() {
    let t = Checkout::new();
    let repo = t.repo();
    let dir = t.tmp.path().join("state");
    fs::create_dir_all(&dir).unwrap();
    let db = Connection::open(dir.join("reviews.sqlite3")).unwrap();
    db.execute_batch(
        "CREATE TABLE notes(id INTEGER PRIMARY KEY, repo BLOB NOT NULL, data TEXT NOT NULL)",
    )
    .unwrap();
    let raw = r#"{"path":"cafe\u0301","body":"Original","suggestion":"replace","new":[17,19]}"#;
    db.execute(
        "INSERT INTO notes VALUES(37,?,?)",
        params![repo_key(&repo), raw],
    )
    .unwrap();
    drop(db);
    let mut one = t.store();
    let mut two = t.store();
    one.db.execute_batch("BEGIN IMMEDIATE").unwrap();
    assert_eq!(t.store().notes(&repo).unwrap().len(), 1);
    one.db.execute_batch("ROLLBACK").unwrap();
    let old = one.notes(&repo).unwrap().pop().unwrap();
    assert_eq!(old["path"], "cafe\u{301}");
    assert_eq!(old["id"], 37);
    assert_eq!(old["resolved"], false);
    let mut edit = old.clone();
    edit["body"] = json!("Updated");
    two.save(&repo, &edit, Some(&old)).unwrap();
    let mut replacement = old.clone();
    replacement["suggestion"] = json!("better code");
    one.save(&repo, &replacement, Some(&old)).unwrap();
    two.set_resolved(&repo, 37, true).unwrap();
    let mut conflict = old.clone();
    conflict["body"] = json!("Conflicting");
    conflict["suggestion"] = json!("Changed twice");
    assert!(one.save(&repo, &conflict, Some(&old)).is_err());
    let saved = t.store().notes(&repo).unwrap().pop().unwrap();
    assert_eq!(saved["body"], "Updated");
    assert_eq!(saved["suggestion"], "better code");
    assert_eq!(saved["resolved"], true);
    one.delete(&repo, 37).unwrap();
    assert!(one.save(&repo, &edit, Some(&old)).is_err());
    assert!(one.save(&repo, &json!({"body":"other"}), None).unwrap() > 37);
}

#[test]
fn reads_python_viewed_keys_and_isolates_partial_staging() {
    let t = Checkout::new();
    t.write("café", "a\n");
    t.git(&["add", "café"]);
    t.write("café", "b\n");
    let repo = t.repo();
    let c = t.diff(&repo);
    let store = t.store();
    let (i, f) = c
        .files
        .iter()
        .enumerate()
        .find(|(_, f)| f.group == "Staged")
        .unwrap();
    let key = format!(
        r#"[["Staged", "caf\u00e9"], "caf\u00e9", ["{}", "{}", "{}", "{}"]]"#,
        f.old_oid, f.oid, f.old_mode, f.mode
    );
    store
        .db
        .execute(
            "INSERT INTO viewed VALUES(?,?,?,?)",
            params![repo_key(&repo), repo.checkout, WORKTREE, key],
        )
        .unwrap();
    assert_eq!(store.viewed(&repo, &c).unwrap(), vec![i]);
    store.set_viewed(&repo, &c, f, false).unwrap();
    assert!(store.viewed(&repo, &c).unwrap().is_empty());
    let unstaged = c.files.iter().find(|f| f.group == "Unstaged").unwrap();
    store.set_viewed(&repo, &c, unstaged, true).unwrap();
    t.write("café", "changed\n");
    assert!(store.viewed(&repo, &t.diff(&repo)).unwrap().is_empty());
}

#[test]
fn local_comment_follows_index_and_commit_without_matching_stale_duplicates() {
    let t = Checkout::new();
    t.write("settings", "top\nlimit = 2\nbottom\n");
    let repo = t.repo();
    let c = t.diff(&repo);
    let mut n = changed_note(&repo, &c, &c.files[0]);
    n["id"] = json!(9);
    t.write("settings", "header\ntop\nlimit = 2\nbottom\n");
    t.git(&["add", "settings"]);
    t.write("settings", "header\ntop\nlimit = 2\nbottom\nfooter\n");
    let lookup = |repo: &Repository, n: &Value| {
        tracking::locate_notes(repo, &repo.initial, None, std::slice::from_ref(n))
    };
    let loc = lookup(&t.repo(), &n);
    assert_eq!(loc[&9].len(), 1);
    assert_eq!(loc[&9][0]["group"], "Staged");
    assert_eq!(loc[&9][0]["new"], json!([3, 3]));
    t.commit("Increase limit");
    let current = t.repo();
    let loc = lookup(&current, &n);
    assert_eq!(loc[&9].len(), 1);
    assert_eq!(loc[&9][0]["right"], current.checkout);
    let mut ghost = n.clone();
    ghost["excerpt"] = json!("+different code");
    ghost["file_version"][1] = json!("unknown");
    assert!(lookup(&current, &ghost)[&9].is_empty());
}

#[test]
fn branch_comment_follows_an_unrelated_commit_only_at_exact_anchors() {
    let t = Checkout::new();
    t.write("settings", "top\nlimit = 2\nbottom\n");
    t.commit("Increase limit");
    let repo = t.repo();
    let stack = ["refs/heads/main", "refs/heads/feature"].map(String::from);
    let before = git::compare(&repo, &stack[0], &stack[1]).unwrap();
    let file = &before.files[0];
    let lines = git::patch(&repo, &before, file).unwrap();
    let selected: Vec<_> = lines
        .iter()
        .filter(|l| l.kind == "+" || l.kind == "-")
        .cloned()
        .collect();
    let mut notes: Vec<_> = ["old", "new", "both"]
        .into_iter()
        .map(|side| make_note(&before, file, &selected, side, "Review this", &lines))
        .collect();
    notes.push(make_note(&before, file, &[], "both", "Review file", &lines));
    for (idx, n) in notes.iter_mut().enumerate() {
        n["id"] = json!(idx as i64 + 1);
        assert!(n["file_version"].is_null());
    }

    t.write("README", "Unrelated docs\n");
    t.commit("Document usage");
    let current = t.repo();
    let loc = tracking::locate_notes(&current, &stack, None, &notes);
    for n in &notes {
        let location = &loc[&n["id"].as_i64().unwrap()];
        assert_eq!(location.len(), 1);
        let d = &location[0];
        assert_eq!(d["path"], "settings");
        assert_eq!(d["right"], stack[1]);
        assert_eq!(d["head"], current.refs[&stack[1]]);
        assert_eq!(d["old"], n["old"]);
        assert_eq!(d["new"], n["new"]);
    }

    let mut stale = notes[1].clone();
    stale["excerpt"] = json!("+different line");
    assert!(tracking::locate_notes(&current, &stack, None, &[stale]).is_empty());

    t.write("settings", "top\nlimit = 2\nbottom\nchanged blob\n");
    t.commit("Change the reviewed file");
    assert!(tracking::locate_notes(&t.repo(), &stack, None, &notes).is_empty());

    t.git(&["reset", "--hard", "main"]);
    t.write("settings", "top\nlimit = 2\nbottom\n");
    t.commit("Unrelated history with the same file bytes");
    assert!(tracking::locate_notes(&t.repo(), &stack, None, &notes).is_empty());
}

#[test]
fn committed_change_on_sibling_branch_cannot_take_a_local_note() {
    let t = Checkout::new();
    t.git(&["switch", "-qc", "top"]);
    t.write("top", "top");
    t.commit("Top");
    t.write("settings", "top\nlimit = 2\nbottom\n");
    t.commit("Independent increase");
    t.git(&["switch", "feature"]);
    t.write("settings", "top\nlimit = 2\nbottom\n");
    let repo = t.repo();
    let c = t.diff(&repo);
    let mut n = changed_note(&repo, &c, &c.files[0]);
    n["id"] = json!(1);
    let stack = ["refs/heads/main", "refs/heads/feature", "refs/heads/top"].map(String::from);
    let mut loc = tracking::locate_notes(&repo, &stack, None, std::slice::from_ref(&n));
    assert_eq!(loc[&1].len(), 1);
    assert_eq!(loc[&1][0]["right"], WORKTREE);
    t.commit("Feature increases limit");
    loc = tracking::locate_notes(&t.repo(), &stack, None, &[n]);
    assert_eq!(loc[&1].len(), 1);
    assert_eq!(loc[&1][0]["right"], stack[1]);
}

#[test]
fn apply_verifies_checkout_preserves_crlf_and_exports_current_receipt() {
    let t = Checkout::new();
    t.write("settings", "top\r\nlimit = 2\r\nbottom");
    let repo = t.repo();
    let c = t.diff(&repo);
    let f = &c.files[0];
    let lines = git::patch(&repo, &c, f).unwrap();
    let selected = lines
        .iter()
        .filter(|l| l.new == Some(2))
        .cloned()
        .collect::<Vec<_>>();
    let mut n = make_note(&c, f, &selected, "new", "Raise it", &lines);
    n["suggestion"] = json!("limit = 3");
    let mut store = t.store();
    let id = store.save(&repo, &n, None).unwrap();
    n = store.notes(&repo).unwrap().pop().unwrap();
    t.git(&["switch", "-qc", "other"]);
    assert!(suggestions::apply(&mut store, &repo, &c, f, &n, &n).is_err());
    t.git(&["switch", "feature"]);
    #[cfg(windows)]
    let stream = t.root.join("settings:review");
    #[cfg(windows)]
    fs::write(&stream, b"review metadata").unwrap();
    #[cfg(unix)]
    let has_xattr = xattr::set(
        t.root.join("settings"),
        "user.branchline-test",
        b"review metadata",
    )
    .is_ok();
    suggestions::apply(&mut store, &repo, &c, f, &n, &n).unwrap();
    assert_eq!(
        fs::read(t.root.join("settings")).unwrap(),
        b"top\r\nlimit = 3\r\nbottom"
    );
    #[cfg(windows)]
    assert_eq!(fs::read(stream).unwrap(), b"review metadata");
    #[cfg(unix)]
    if has_xattr {
        assert_eq!(
            xattr::get(t.root.join("settings"), "user.branchline-test")
                .unwrap()
                .unwrap(),
            b"review metadata"
        );
    }
    assert!(suggestions::apply(&mut store, &repo, &c, f, &n, &n).is_err());
    let mut notes = store.notes(&repo).unwrap();
    assert_eq!(notes[0]["applied_location"]["new"], json!([2, 2]));
    t.commit("Apply proposal");
    let current = t.repo();
    let loc = tracking::locate_notes(&current, &repo.initial, None, &notes);
    assert_eq!(loc[&id][0]["applied_text"], true);
    let mut historical = n.clone();
    historical["resolved"] = json!(true);
    historical["body"] = json!("Hidden history");
    notes.insert(0, historical);
    let report = markdown(&current, Some(&repo.initial), &notes, &loc, true);
    assert!(
        report.contains("**1 open**")
            && report.contains("Suggestion status: applied to working file")
            && report.contains("Current location of replacement: Committed in")
            && report.contains("Raise it")
    );
    assert!(!report.contains("Hidden history"));
}

#[test]
fn file_edit_receipt_remains_exportable_when_sqlite_update_fails() {
    let t = Checkout::new();
    t.write("settings", "top\nlimit = 2\nbottom\n");
    let repo = t.repo();
    let c = t.diff(&repo);
    let f = &c.files[0];
    let mut n = changed_note(&repo, &c, f);
    n["suggestion"] = json!("limit = 9");
    let mut store = t.store();
    store.save(&repo, &n, None).unwrap();
    let original = store.notes(&repo).unwrap().pop().unwrap();
    store.db.execute_batch("CREATE TRIGGER refuse_receipts BEFORE UPDATE OF data ON notes BEGIN SELECT RAISE(FAIL,'simulated I/O failure'); END;").unwrap();
    assert!(
        suggestions::apply(&mut store, &repo, &c, f, &original, &original)
            .unwrap_err()
            .contains("Export")
    );
    assert!(fs::read_to_string(t.root.join("settings"))
        .unwrap()
        .contains("limit = 9"));
    let restored = t.store().notes(&repo).unwrap();
    assert!(markdown(&repo, None, &restored, &Locations::new(), false)
        .contains("Suggestion status: applied to working file"));
    assert!(suggestions::apply(&mut store, &repo, &c, f, &original, &original).is_err());
}

#[cfg(unix)]
#[test]
fn python_non_utf8_paths_roundtrip_without_conflating_literal_escape_text() {
    use std::os::unix::ffi::OsStrExt;
    let t = Checkout::new();
    let repo = t.repo();
    let mut store = t.store();
    let raw = b"settings-\xff";
    let encoded = git::name(raw);
    fs::write(repo.root.join(std::ffi::OsStr::from_bytes(raw)), b"a\n").unwrap();
    let existing = r#"{"path":"settings-\udcff","old_path":"settings-\udcff","body":"literal \\udcff","new":[]}"#;
    store
        .db
        .execute(
            "INSERT INTO notes(repo,data) VALUES(?,?)",
            params![repo_key(&repo), existing],
        )
        .unwrap();
    let old = store.notes(&repo).unwrap().pop().unwrap();
    assert_eq!(old["path"], encoded);
    assert_eq!(old["body"], "literal \\udcff");
    let c = t.diff(&repo);
    let f = c.files.iter().find(|f| f.path == encoded).unwrap();
    store.set_viewed(&repo, &c, f, true).unwrap();
    let raw_key: String = store
        .db
        .query_row("SELECT path FROM viewed", [], |row| row.get(0))
        .unwrap();
    assert!(raw_key.contains(r#""settings-\udcff""#));
    let mut edited = old.clone();
    edited["body"] = json!("Edited");
    store.save(&repo, &edited, Some(&old)).unwrap();
    let data: String = store
        .db
        .query_row("SELECT data FROM notes", [], |row| row.get(0))
        .unwrap();
    assert!(data.contains(r#""path":"settings-\udcff""#));
    assert_eq!(store.notes(&repo).unwrap()[0]["path"], encoded);
}
