use crate::git::{self, Change, Comparison, Line, Repository, EMPTY, WORKTREE};
use crate::review::{comparisons, file_version, note_matches_file, num, s, span, Locations};
use serde_json::{json, Value};
use std::collections::{BTreeMap, HashMap, HashSet};
use std::rc::Rc;

fn follow_range(
    lines: &[Line],
    note: &Value,
    side: &str,
    same_blob: bool,
) -> Option<(usize, usize)> {
    let sign = if side == "new" { '+' } else { '-' };
    let expected = s(note, "excerpt")
        .split('\n')
        .filter_map(|l| {
            l.strip_prefix(sign)
                .map(|t| (true, t))
                .or_else(|| l.strip_prefix(' ').map(|t| (false, t)))
        })
        .collect::<Vec<_>>();
    let (original, _) = span(note, side)?;
    let first = expected.first()?.1;
    let visible: BTreeMap<_, _> = lines
        .iter()
        .filter_map(|l| num(l, side).map(|i| (i, l)))
        .collect();
    let neighbors = note["neighbors"][side].as_object();
    let mut best = None;
    let mut tied = false;
    for (&start, line) in &visible {
        if (same_blob && start != original) || line.text != first {
            continue;
        }
        let end = start.checked_add(expected.len() - 1)?;
        let mut changed = false;
        if !expected
            .iter()
            .enumerate()
            .all(|(offset, (was_changed, word))| {
                let Some(found) = visible.get(&(start + offset)) else {
                    return false;
                };
                changed |= *was_changed && found.kind.starts_with(sign);
                found.hunk == line.hunk && found.text == *word
            })
            || (expected.iter().any(|(change, _)| *change) && !changed)
        {
            continue;
        }
        if same_blob {
            return Some((start, end));
        }
        let mut score = 0usize;
        if let Some(context) = neighbors {
            for (k, v) in context {
                let Some(step) = k.parse::<isize>().ok() else {
                    continue;
                };
                let number = if step < 0 { start } else { end }.checked_add_signed(step);
                if let Some(candidate) = number.and_then(|i| visible.get(&i)) {
                    if candidate.hunk == line.hunk
                        && !candidate.text.trim().is_empty()
                        && v == &candidate.text
                    {
                        score += 1;
                    }
                }
            }
        }
        match best {
            Some((points, _, _)) if score == points => tied = true,
            Some((points, _, _)) if score < points => {}
            _ => {
                best = Some((score, start, end));
                tied = false;
            }
        }
    }
    let (score, start, end) = best?;
    let has_context = neighbors.is_some_and(|map| {
        map.values()
            .any(|v| v.as_str().is_some_and(|text| !text.trim().is_empty()))
    });
    if tied
        || (score == 0
            && (has_context || !expected.iter().any(|(_, text)| !text.trim().is_empty())))
    {
        None
    } else {
        Some((start, end))
    }
}
fn project(file: &Change, lines: &[Line], note: &Value) -> Option<Value> {
    let side = if span(note, "new").is_some() {
        "new"
    } else {
        "old"
    };
    let old = &note["file_version"][0];
    let new = &note["file_version"][1];
    if span(note, side).is_none() {
        let same =
            new == &file.oid && (!file.oid.trim_matches('0').is_empty() || old == &file.old_oid);
        return same.then(|| note.clone());
    }
    let primary = follow_range(
        lines,
        note,
        side,
        if side == "new" {
            new == &file.oid
        } else {
            old == &file.old_oid
        },
    )?;
    let mut projected = note.clone();
    projected["new"] = json!([]);
    projected["old"] = json!([]);
    projected[side] = json!(primary);
    if side == "new" && span(note, "old").is_some() {
        if let Some((first, last)) = follow_range(lines, note, "old", old == &file.old_oid) {
            let selected = lines
                .iter()
                .filter(|l| {
                    l.old.is_some_and(|i| (first..=last).contains(&i))
                        || l.new.is_some_and(|i| (primary.0..=primary.1).contains(&i))
                })
                .map(|l| format!("{}{}", l.kind, l.text))
                .collect::<Vec<_>>()
                .join("\n");
            if selected == s(note, "excerpt") {
                projected["old"] = json!([first, last]);
            }
        }
    }
    Some(projected)
}

pub fn location_for(c: &Comparison, f: &Change, n: &Value) -> Value {
    let mut l = json!({"left":c.left,"right":c.right,"base":c.base,"head":c.head,"path":f.path,"group":f.group,"old":n["old"],"new":n["new"]});
    if c.right == WORKTREE {
        l["blob"] = json!(if (span(n, "old").is_some() && span(n, "new").is_none())
            || f.status == "D"
        {
            &f.old_oid
        } else {
            &f.oid
        });
    }
    l
}
struct Lookup<'a> {
    repo: &'a Repository,
    untracked: HashSet<String>,
    comparisons: HashMap<(String, String), Rc<Comparison>>,
    patches: HashMap<(String, String, String, String), Vec<Line>>,
    common: HashMap<(String, String), String>,
    ancestry: HashMap<(String, String), bool>,
}
impl Lookup<'_> {
    fn comparison(&mut self, left: &str, right: &str) -> Result<Rc<Comparison>, String> {
        let key = (left.into(), right.into());
        if let Some(hit) = self.comparisons.get(&key) {
            return Ok(hit.clone());
        }
        let c = Rc::new(if right == WORKTREE {
            git::working_tree(self.repo, left, Some(&self.untracked))?
        } else {
            git::compare(self.repo, left, right)?
        });
        self.comparisons.insert(key, c.clone());
        Ok(c)
    }
    fn introduced(&mut self, origin: &str, head: &str) -> Result<Rc<Comparison>, String> {
        let key = (origin.into(), head.into());
        if let Some(c) = self.comparisons.get(&key) {
            return Ok(c.clone());
        }
        let c = Rc::new(git::compare_trees(
            self.repo, origin, head, origin, origin, head,
        )?);
        self.comparisons.insert(key, c.clone());
        Ok(c)
    }
    fn common(&mut self, a: &str, b: &str) -> Result<String, String> {
        if a == b {
            return Ok(a.into());
        }
        let key = (a.into(), b.into());
        if let Some(hit) = self.common.get(&key) {
            return Ok(hit.clone());
        }
        let hash = git::merge_base(self.repo, a, b)?;
        self.common.insert(key, hash.clone());
        Ok(hash)
    }
    fn descends(&mut self, origin: &str, head: &str) -> Result<bool, String> {
        if origin == self.repo.refs[EMPTY] || origin == head {
            return Ok(true);
        }
        if head == self.repo.refs[EMPTY] {
            return Ok(false);
        }
        if !oid(origin) || !oid(head) {
            return Err("Invalid saved revision.".into());
        }
        let key = (origin.into(), head.into());
        if let Some(hit) = self.ancestry.get(&key) {
            return Ok(*hit);
        }
        let descends = git::descends(self.repo, origin, head)?;
        self.ancestry.insert(key, descends);
        Ok(descends)
    }
    fn patch(&mut self, c: &Comparison, f: &Change) -> Result<&[Line], String> {
        let key = (
            c.base.clone(),
            c.head.clone(),
            f.group.clone(),
            f.path.clone(),
        );
        let lines = match self.patches.entry(key) {
            std::collections::hash_map::Entry::Occupied(entry) => entry.into_mut(),
            std::collections::hash_map::Entry::Vacant(entry) => {
                entry.insert(git::patch(self.repo, c, f)?)
            }
        };
        Ok(lines)
    }
    fn unchanged_branch_location(
        &mut self,
        c: &Comparison,
        n: &Value,
    ) -> Result<Option<Value>, String> {
        let previous_head = s(n, "head");
        if n["base"] != c.base || !self.descends(previous_head, &c.head)? {
            return Ok(None);
        }

        // Older branch comments did not store blob IDs. Read the original
        // comparison and require exact identities on both sides of the diff.
        let previous = self.introduced(&c.base, previous_head)?;
        let matches_path = |f: &&Change| n["path"] == f.path && n["old_path"] == f.old;
        let mut original_files = previous.files.iter().filter(matches_path);
        let mut current_files = c.files.iter().filter(matches_path);
        let (Some(original), None, Some(current), None) = (
            original_files.next(),
            original_files.next(),
            current_files.next(),
            current_files.next(),
        ) else {
            return Ok(None);
        };
        let version = file_version(current);
        if original.status != current.status || file_version(original) != version {
            return Ok(None);
        }

        if span(n, "old").is_some() || span(n, "new").is_some() {
            let mut anchored = n.clone();
            anchored["file_version"] = version;
            let lines = self.patch(c, current)?;
            if !project(current, lines, &anchored)
                .is_some_and(|n2| n2["old"] == n["old"] && n2["new"] == n["new"])
            {
                return Ok(None);
            }
        }
        Ok(Some(location_for(c, current, n)))
    }
    fn matching<'b>(
        &mut self,
        c: &'b Comparison,
        n: &Value,
    ) -> Result<Option<(&'b Change, Value)>, String> {
        if let Some(f) = c.files.iter().find(|f| note_matches_file(c, f, n)) {
            return Ok(Some((f, n.clone())));
        }
        let mut candidates = Vec::new();
        for f in c
            .files
            .iter()
            .filter(|f| n["path"] == f.path || (f.status == "R" && n["path"] == f.old))
        {
            if let Some(anchor) = project(f, self.patch(c, f)?, n) {
                let idx = usize::from(span(n, "new").is_some());
                let rank = (
                    n["file_version"][idx] == file_version(f)[idx],
                    n["group"] == f.group,
                );
                candidates.push((rank, f, anchor));
            }
        }
        candidates.sort_by_key(|(rank, _, _)| *rank);
        let Some((rank, f, anchor)) = candidates.pop() else {
            return Ok(None);
        };
        Ok(candidates
            .last()
            .is_none_or(|x| x.0 != rank)
            .then_some((f, anchor)))
    }
    fn in_stack(
        &mut self,
        n: &Value,
        source: &str,
        left: &str,
        right: &str,
    ) -> Result<Option<Value>, String> {
        let origin = s(n, "left_tip");
        if !self.descends(origin, source)? {
            return Ok(None);
        }
        let tip = self
            .repo
            .refs
            .get(right)
            .ok_or("Missing branch tip.")?
            .clone();
        let shared = self.common(source, &tip)?;
        if shared == origin || !self.descends(origin, &shared)? {
            return Ok(None);
        }
        let c = self.comparison(left, right)?;
        if c.base != self.repo.refs[EMPTY] && self.common(&c.base, &shared)? == shared {
            return Ok(None);
        }
        let introduced = self.introduced(origin, &shared)?;
        let Some((f, mut anchor)) = self.matching(&introduced, n)? else {
            return Ok(None);
        };
        if c.base == origin && c.head == shared {
            return Ok(Some(location_for(&c, f, &anchor)));
        }
        anchor["path"] = json!(f.path);
        anchor["file_version"] = file_version(f);
        Ok(self
            .matching(&c, &anchor)?
            .map(|(f, a)| location_for(&c, f, &a)))
    }
}
pub(crate) fn oid(hash: &str) -> bool {
    matches!(hash.len(), 40 | 64)
        && hash
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

pub fn locate_notes(
    repo: &Repository,
    stack: &[String],
    primary: Option<&Comparison>,
    notes: &[Value],
) -> Locations {
    let branches: HashSet<&str> = stack
        .iter()
        .map(|r| {
            if r == "HEAD" {
                repo.checkout.as_str()
            } else {
                r.as_str()
            }
        })
        .collect();
    let mut anchors = Vec::new();
    for n in notes {
        let Some(id) = n["id"].as_i64() else {
            continue;
        };
        for (applied, anchor) in [(false, n), (true, &n["applied_anchor"])] {
            if anchor["right"] == WORKTREE
                && (anchor["left"] == repo.checkout || branches.contains(s(anchor, "left")))
            {
                anchors.push((id, applied, anchor));
            }
        }
    }
    let pairs = comparisons(stack);
    let untracked = anchors
        .iter()
        .filter(|(_, _, a)| a["left"] == repo.checkout)
        .map(|(_, _, a)| s(a, "path").to_string())
        .collect();
    let mut look = Lookup {
        repo,
        untracked,
        comparisons: HashMap::new(),
        patches: HashMap::new(),
        common: HashMap::new(),
        ancestry: HashMap::new(),
    };
    if let Some(c) = primary {
        look.comparisons
            .insert((c.left.clone(), c.right.clone()), Rc::new(c.clone()));
    }
    let mut found: Locations = BTreeMap::new();
    let mut unavailable = HashSet::new();
    for n in notes {
        let (left, right) = (s(n, "left"), s(n, "right"));
        let Some(id) = n["id"].as_i64() else {
            continue;
        };
        if !pairs.contains(&(left, right)) {
            continue;
        }
        let Some(head) = repo.refs.get(right) else {
            continue;
        };
        let head_unchanged = n["head"] == *head;
        if head_unchanged && repo.refs.get(left).is_none_or(|h| n["left_tip"] == *h) {
            continue;
        }
        let location = (|| {
            let c = look.comparison(left, right)?;
            if head_unchanged {
                Ok(c.files
                    .iter()
                    .find(|f| note_matches_file(&c, f, n))
                    .map(|f| location_for(&c, f, n)))
            } else {
                look.unchanged_branch_location(&c, n)
            }
        })();
        match location {
            Ok(Some(location)) => found.entry(id).or_default().push(location),
            Ok(None) => {}
            Err(_) => {
                unavailable.insert(id);
            }
        }
    }
    for (id, applied, n) in anchors {
        let dests = found.entry(id).or_default();
        let mut record = |result: Result<Option<Value>, String>| match result {
            Ok(Some(mut l)) => {
                if applied {
                    l["applied_text"] = json!(true);
                }
                if let Some(pos) = dests
                    .iter()
                    .position(|d| d["left"] == l["left"] && d["right"] == l["right"])
                {
                    dests[pos] = l;
                } else {
                    dests.push(l);
                }
            }
            Err(_) => {
                unavailable.insert(id);
            }
            _ => {}
        };
        let branch = s(n, "left");
        if branch == repo.checkout {
            record((|| {
                let c = look.comparison(branch, WORKTREE)?;
                let Some((f, anchor)) = look.matching(&c, n)? else {
                    return Ok(None);
                };
                if note_matches_file(&c, f, n) || look.descends(s(n, "left_tip"), &c.base)? {
                    Ok(Some(location_for(&c, f, &anchor)))
                } else {
                    Ok(None)
                }
            })());
        }
        if branches.contains(branch) {
            if let Some(source) = repo
                .refs
                .get(if branch.starts_with("HEAD@") {
                    "HEAD"
                } else {
                    branch
                })
                .filter(|h| n["left_tip"] != **h)
            {
                for (left, right) in &pairs {
                    record(look.in_stack(n, source, left, right));
                }
            }
        }
    }
    found.retain(|id, dests| !dests.is_empty() || !unavailable.contains(id));
    found
}
