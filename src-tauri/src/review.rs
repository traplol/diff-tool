//! SQLite schema and JSON anchors shared with the original Branchline client.
use crate::git::{Change, Comparison, Line, Repository, WORKTREE};
use rusqlite::{params, Connection, OptionalExtension, TransactionBehavior};
use serde_json::{json, Value};
use std::{
    collections::{BTreeMap, HashSet},
    env, fs,
    path::{Path, PathBuf},
    sync::Mutex,
};

#[path = "stored_paths.rs"]
mod stored_paths;
use stored_paths::{stored_name, translate};

pub type Locations = BTreeMap<i64, Vec<Value>>;
pub(crate) fn s<'a>(note: &'a Value, field: &str) -> &'a str {
    note[field].as_str().unwrap_or("")
}
pub(crate) fn span(note: &Value, side: &str) -> Option<(usize, usize)> {
    let range = note[side].as_array()?;
    let first = usize::try_from(range.first()?.as_u64()?).ok()?;
    let last = usize::try_from(range.get(1)?.as_u64()?).ok()?;
    (first > 0 && last >= first).then_some((first, last))
}

fn err(e: impl std::fmt::Display) -> String {
    e.to_string()
}

fn directory() -> Result<PathBuf, String> {
    #[cfg(windows)]
    let dir = env::var_os("LOCALAPPDATA")
        .map(PathBuf::from)
        .or_else(|| env::var_os("USERPROFILE").map(|p| PathBuf::from(p).join("AppData/Local")))
        .map(|p| p.join("Branchline"));
    #[cfg(not(windows))]
    let dir = env::var_os("XDG_DATA_HOME")
        .map(PathBuf::from)
        .or_else(|| env::var_os("HOME").map(|p| PathBuf::from(p).join(".local/share")))
        .map(|p| p.join("branchline"));
    dir.ok_or_else(|| "Could not locate the review data directory.".into())
}
fn repo_key(repo: &Repository) -> Vec<u8> {
    #[cfg(unix)]
    {
        use std::os::unix::ffi::OsStrExt;
        repo.root.as_os_str().as_bytes().to_vec()
    }
    #[cfg(windows)]
    {
        let path = repo.root.to_string_lossy().replace('/', "\\");
        if let Some(unc) = path.strip_prefix(r"\\?\UNC\") {
            return format!(r"\\{unc}").into_bytes();
        }
        path.strip_prefix(r"\\?\")
            .unwrap_or(&path)
            .as_bytes()
            .to_vec()
    }
}

// A file replacement can succeed while SQLite fails to commit its receipt.
// Preserve that receipt for export and for the next successful edit in this process.
type Receipts = BTreeMap<(PathBuf, i64), Value>;
static PENDING: Mutex<Receipts> = Mutex::new(BTreeMap::new());

pub(crate) fn remember_receipt(repo: &Repository, id: i64, receipt: Value) {
    PENDING
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .insert((repo.root.clone(), id), receipt);
}
pub(crate) fn restore_receipt(repo: &Repository, id: i64, note: &mut Value) {
    let pending = PENDING.lock().unwrap_or_else(|e| e.into_inner());
    if let Some(receipt) = pending.get(&(repo.root.clone(), id)) {
        if receipt["suggestion"] == note["suggestion"] && note["applied_location"].is_null() {
            note["applied_location"] = receipt["applied_location"].clone();
            note["applied_anchor"] = receipt["applied_anchor"].clone();
        } else if receipt["applied_anchor"] != note["applied_anchor"] {
            note["earlier_application"] = receipt.clone();
        }
    }
}

pub struct Store {
    db: Connection,
}
impl Store {
    pub fn open() -> Result<Self, String> {
        Self::at(&directory()?)
    }
    pub fn at(dir: &Path) -> Result<Self, String> {
        fs::create_dir_all(dir).map_err(err)?;
        let mut db = Connection::open(dir.join("reviews.sqlite3")).map_err(err)?;
        // A read-only view of an initialized database must not acquire a writer lock.
        // Another Branchline instance can be applying a suggestion while this one reads.
        let ready: bool = db
            .query_row(
                "SELECT (SELECT count(*) FROM sqlite_master WHERE type='table'
                AND name IN ('stacks','preferences','viewed','notes')) = 4
                AND EXISTS(SELECT 1 FROM pragma_table_info('notes') WHERE name='resolved')",
                [],
                |row| row.get(0),
            )
            .map_err(err)?;
        if ready {
            return Ok(Self { db });
        }

        let tx = db
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(err)?;
        tx.execute_batch("CREATE TABLE IF NOT EXISTS stacks(repo BLOB PRIMARY KEY,refs TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS preferences(name TEXT PRIMARY KEY,value INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS viewed(repo BLOB,base TEXT,head TEXT,path TEXT,PRIMARY KEY(repo,base,head,path));").map_err(err)?;
        let cols: (i64,i64) = tx.query_row("SELECT count(*),count(CASE WHEN name='resolved' THEN 1 END) FROM pragma_table_info('notes')",[],|r|Ok((r.get(0)?,r.get(1)?))).map_err(err)?;
        let legacy = cols.0 != 0 && cols.1 == 0;
        if legacy {
            tx.execute_batch("ALTER TABLE notes RENAME TO notes_before_resolution;")
                .map_err(err)?;
        }
        tx.execute_batch("CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY AUTOINCREMENT,repo BLOB NOT NULL,data TEXT NOT NULL,resolved INTEGER NOT NULL DEFAULT 0);").map_err(err)?;
        if legacy {
            tx.execute_batch("INSERT INTO notes(id,repo,data) SELECT id,repo,data FROM notes_before_resolution; DROP TABLE notes_before_resolution;").map_err(err)?;
        }
        tx.commit().map_err(err)?;
        Ok(Self { db })
    }
    pub fn sidebar_width(&self) -> Result<i64, String> {
        Ok(self
            .db
            .query_row(
                "SELECT value FROM preferences WHERE name='sidebar_width'",
                [],
                |r| r.get(0),
            )
            .optional()
            .map_err(err)?
            .unwrap_or(320))
    }
    pub fn saved_stack(&self, repo: &Repository) -> Result<Option<Vec<String>>, String> {
        let saved: Option<String> = self
            .db
            .query_row(
                "SELECT refs FROM stacks WHERE repo=?",
                [repo_key(repo)],
                |r| r.get(0),
            )
            .optional()
            .map_err(err)?;
        if let Some(raw) = saved {
            let refs: Vec<String> =
                serde_json::from_str(&translate(&raw, true, true)?).map_err(err)?;
            if refs.len() >= 2 {
                return Ok(Some(refs));
            }
        }
        Ok(None)
    }
    pub fn notes(&self, repo: &Repository) -> Result<Vec<Value>, String> {
        self.notes_after(repo, 0, None, -1)
    }
    pub fn note(&self, repo: &Repository, id: i64) -> Result<Option<Value>, String> {
        if id <= 0 {
            return Ok(None);
        }
        Ok(self
            .notes_after(repo, id - 1, None, 1)?
            .pop()
            .filter(|note| note["id"] == id))
    }
    pub fn notes_after(
        &self,
        repo: &Repository,
        after: i64,
        resolved: Option<bool>,
        limit: i64,
    ) -> Result<Vec<Value>, String> {
        let mut stmt = self
            .db
            .prepare(
                "SELECT id,data,resolved FROM notes
                WHERE repo=?1 AND id>?2 AND (?3 IS NULL OR resolved=?3)
                ORDER BY id LIMIT ?4",
            )
            .map_err(err)?;
        let mut rows = stmt
            .query(params![repo_key(repo), after, resolved, limit])
            .map_err(err)?;
        let mut notes = Vec::new();
        while let Some(r) = rows.next().map_err(err)? {
            let mut n: Value = serde_json::from_str(&translate(
                &r.get::<_, String>(1).map_err(err)?,
                false,
                true,
            )?)
            .map_err(err)?;
            let obj = n.as_object_mut().ok_or("Invalid saved review record.")?;
            let id = r.get::<_, i64>(0).map_err(err)?;
            obj.insert("id".into(), json!(id));
            obj.insert("resolved".into(), json!(r.get::<_, bool>(2).map_err(err)?));
            restore_receipt(repo, id, &mut n);
            notes.push(n);
        }
        Ok(notes)
    }
    /// Keep the latest body, replacement, resolution and application receipt independent across windows.
    pub(crate) fn edit<F>(&mut self, repo: &Repository, id: i64, change: F) -> Result<(), String>
    where
        F: FnOnce(&mut Value, bool) -> Result<(), String>,
    {
        self.edit_note(repo, id, None, change)
    }
    fn edit_note<F>(
        &mut self,
        repo: &Repository,
        id: i64,
        resolution: Option<bool>,
        change: F,
    ) -> Result<(), String>
    where
        F: FnOnce(&mut Value, bool) -> Result<(), String>,
    {
        let tx = self
            .db
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(err)?;
        let key = repo_key(repo);
        let (data, resolved): (String, bool) = tx
            .query_row(
                "SELECT data,resolved FROM notes WHERE repo=? AND id=?",
                params![key, id],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()
            .map_err(err)?
            .ok_or("Another window deleted this comment.")?;
        let mut note: Value = serde_json::from_str(&translate(&data, false, true)?).map_err(err)?;
        if !note.is_object() {
            return Err("Invalid saved review record.".into());
        }
        restore_receipt(repo, id, &mut note);
        change(&mut note, resolved)?;
        tx.execute(
            "UPDATE notes SET data=?,resolved=? WHERE repo=? AND id=?",
            params![
                translate(&note.to_string(), false, false)?,
                resolution.unwrap_or(resolved),
                key,
                id
            ],
        )
        .map_err(err)?;
        tx.commit().map_err(err)?;
        PENDING
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .remove(&(repo.root.clone(), id));
        Ok(())
    }
    pub fn reply(
        &mut self,
        repo: &Repository,
        id: i64,
        author: &str,
        body: &str,
        resolution: Option<bool>,
    ) -> Result<(), String> {
        let author = author.trim();
        let body = body.trim();
        if author.is_empty() || author.len() > 120 || body.is_empty() || body.len() > 32_768 {
            return Err(
                "Supply a reply of up to 32768 bytes and an author of up to 120 bytes.".into(),
            );
        }
        self.edit_note(repo, id, resolution, |note, _| {
            let replies = note
                .as_object_mut()
                .ok_or("Invalid saved review record.")?
                .entry("replies")
                .or_insert_with(|| json!([]));
            replies
                .as_array_mut()
                .ok_or("Invalid saved comment replies.")?
                .push(json!({"author": author, "body": body}));
            Ok(())
        })
    }
    pub fn save(
        &mut self,
        repo: &Repository,
        note: &Value,
        original: Option<&Value>,
    ) -> Result<i64, String> {
        if let Some(id) = note["id"].as_i64() {
            let original = original
                .filter(|n| n["id"] == id)
                .ok_or("Saving an edit requires the original comment.")?;
            self.edit(repo, id, |current, _| {
                for key in ["body", "suggestion"] {
                    if note[key] == original[key] || note[key] == current[key] {
                        continue;
                    }
                    if key == "suggestion" && !current["applied_location"].is_null() {
                        return Err("Another window applied this suggestion. The replacement is read-only.".into());
                    }
                    if current[key] != original[key] {
                        return Err("Another window edited the same text. Reopen the comment to see its changes.".into());
                    }
                    current[key] = note[key].clone();
                }
                Ok(())
            })?;
            return Ok(id);
        }
        let mut data = note.as_object().ok_or("Invalid review record.")?.clone();
        data.remove("resolved");
        self.db
            .execute(
                "INSERT INTO notes(repo,data) VALUES(?,?)",
                params![
                    repo_key(repo),
                    translate(&Value::Object(data).to_string(), false, false)?
                ],
            )
            .map_err(err)?;
        Ok(self.db.last_insert_rowid())
    }
    pub fn set_resolved(&self, repo: &Repository, id: i64, resolved: bool) -> Result<bool, String> {
        Ok(self
            .db
            .execute(
                "UPDATE notes SET resolved=? WHERE id=? AND repo=?",
                params![resolved, id, repo_key(repo)],
            )
            .map_err(err)?
            == 1)
    }
    pub fn delete(&self, repo: &Repository, id: i64) -> Result<(), String> {
        self.db
            .execute(
                "DELETE FROM notes WHERE repo=? AND id=?",
                params![repo_key(repo), id],
            )
            .map_err(err)?;
        Ok(())
    }
    pub fn viewed(&self, repo: &Repository, c: &Comparison) -> Result<Vec<usize>, String> {
        let (base, head) = viewed_scope(c);
        let mut stmt = self
            .db
            .prepare("SELECT path FROM viewed WHERE repo=? AND base=? AND head=?")
            .map_err(err)?;
        let rows = stmt
            .query_map(params![repo_key(repo), base, head], |r| {
                r.get::<_, String>(0)
            })
            .map_err(err)?;
        let saved = rows
            .collect::<rusqlite::Result<HashSet<String>>>()
            .map_err(err)?;
        let mut viewed = Vec::new();
        for (index, file) in c.files.iter().enumerate() {
            if saved.contains(&viewed_path(file)?) {
                viewed.push(index);
            }
        }
        Ok(viewed)
    }
    pub fn set_viewed(
        &self,
        repo: &Repository,
        c: &Comparison,
        f: &Change,
        value: bool,
    ) -> Result<(), String> {
        let (base, head) = viewed_scope(c);
        let sql = if value {
            "INSERT OR IGNORE INTO viewed VALUES(?,?,?,?)"
        } else {
            "DELETE FROM viewed WHERE repo=? AND base=? AND head=? AND path=?"
        };
        self.db
            .execute(sql, params![repo_key(repo), base, head, viewed_path(f)?])
            .map_err(err)?;
        Ok(())
    }
}

fn viewed_scope(c: &Comparison) -> (&str, &str) {
    if c.right == WORKTREE {
        (&c.left, WORKTREE)
    } else {
        (&c.base, &c.head)
    }
}
pub(crate) fn file_version(f: &Change) -> Value {
    json!([f.old_oid, f.oid, f.old_mode, f.mode])
}
// Python's json.dumps spelling is part of the existing database primary key.
fn viewed_path(f: &Change) -> Result<String, String> {
    let path = stored_name(&f.path)?;
    if f.group.is_empty() {
        return Ok(path);
    }
    let quote = stored_paths::python_string;
    Ok(format!(
        "[[{}, {}], {}, [{}, {}, {}, {}]]",
        quote(&f.group),
        path,
        stored_name(&f.old)?,
        quote(&f.old_oid),
        quote(&f.oid),
        quote(&f.old_mode),
        quote(&f.mode)
    ))
}

pub fn comparisons(stack: &[String]) -> Vec<(&str, &str)> {
    if stack.len() < 2 {
        return vec![];
    }
    let mut pairs = vec![(stack[0].as_str(), stack[stack.len() - 1].as_str())];
    if stack.len() > 2 {
        pairs.extend(stack.windows(2).map(|p| (p[0].as_str(), p[1].as_str())));
    }
    pairs
}
pub(crate) fn num(line: &Line, side: &str) -> Option<usize> {
    if side == "old" {
        line.old
    } else {
        line.new
    }
}
pub fn make_note(
    c: &Comparison,
    f: &Change,
    lines: &[Line],
    side: &str,
    body: &str,
    diff: &[Line],
) -> Value {
    let mut n = json!({"left":c.left,"right":c.right,"left_tip":c.left_tip,"base":c.base,"head":c.head,
        "path":f.path,"old_path":f.old,"old":[],"new":[],"excerpt":lines.iter().map(|l|format!("{}{}",l.kind,l.text)).collect::<Vec<_>>().join("\n"),"body":body});
    if c.right == WORKTREE {
        n["group"] = json!(f.group);
        n["file_version"] = file_version(f);
    }
    for name in ["old", "new"] {
        if (side == "old" && name == "new") || (side == "new" && name == "old") {
            continue;
        }
        let mut numbers = lines.iter().filter_map(|l| num(l, name));
        let Some(first) = numbers.next() else {
            continue;
        };
        let last = numbers.next_back().unwrap_or(first);
        n[name] = json!([first, last]);
        if c.right == WORKTREE && !diff.is_empty() {
            let mut neighbors = serde_json::Map::new();
            for l in diff.iter().filter(|l| l.hunk == lines[0].hunk) {
                let Some(i) = num(l, name) else {
                    continue;
                };
                let offset = if i < first && first - i <= 3 {
                    -(first.abs_diff(i) as i64)
                } else if i > last && i - last <= 3 {
                    last.abs_diff(i) as i64
                } else {
                    continue;
                };
                neighbors.insert(offset.to_string(), json!(l.text));
            }
            n["neighbors"][name] = Value::Object(neighbors);
        }
    }
    n
}
pub fn note_matches_file(c: &Comparison, f: &Change, n: &Value) -> bool {
    n["left"] == c.left
        && n["right"] == c.right
        && n["path"] == f.path
        && if c.right == WORKTREE {
            n["group"] == f.group && n["old_path"] == f.old && n["file_version"] == file_version(f)
        } else {
            n["base"] == c.base && n["head"] == c.head
        }
}
pub fn suggestion_source(n: &Value) -> String {
    s(n, "excerpt")
        .split('\n')
        .filter_map(|line| line.strip_prefix('+').or_else(|| line.strip_prefix(' ')))
        .collect::<Vec<_>>()
        .join("\n")
}

#[path = "report.rs"]
mod report;
pub use report::markdown;

#[cfg(test)]
#[path = "review_tests.rs"]
mod tests;
