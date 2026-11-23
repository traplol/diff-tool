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
