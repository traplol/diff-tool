use super::*;
use tempfile::{tempdir, TempDir};

fn history() -> TempDir {
    let repo = tempdir().unwrap();
    for args in [
        &["init", "-qb", "main"][..],
        &["config", "user.name", "Morgan"],
        &["config", "user.email", "review@example.test"],
        &["config", "commit.gpgsign", "false"],
        &["config", "core.autocrlf", "false"],
    ] {
        git(repo.path(), args).unwrap();
    }
    repo
}

fn write(repo: &TempDir, path: &str, content: &[u8]) {
    fs::write(repo.path().join(path), content).unwrap();
}
fn record(repo: &TempDir, message: &str) {
    git(repo.path(), &["add", "-A"]).unwrap();
    git(repo.path(), &["commit", "-qm", message]).unwrap();
}
fn work(repo: &Repository) -> Comparison {
    compare(repo, &repo.checkout, WORKTREE).unwrap()
}
fn file<'a>(c: &'a Comparison, group: &str, path: &str) -> &'a Change {
    c.files
        .iter()
        .find(|f| f.group == group && f.path == path)
        .unwrap()
}
fn content(repo: &Repository, c: &Comparison, group: &str, path: &str) -> Vec<String> {
    patch(repo, c, file(c, group, path))
        .unwrap()
        .into_iter()
        .filter(|l| matches!(l.kind.as_str(), "+" | "-"))
        .map(|l| l.text)
        .collect()
}

fn assert_streamed_rows(repo: &Repository, c: &Comparison) {
    let expected: Vec<_> = c
        .files
        .iter()
        .filter(|f| f.added.is_some() && f.removed.is_some())
        .flat_map(|file| {
            patch(repo, c, file)
                .unwrap()
                .into_iter()
                .enumerate()
                .map(|(row, line)| {
                    (
                        file.old.clone(),
                        file.path.clone(),
                        file.group.clone(),
                        row,
                        serde_json::to_value(line).unwrap(),
                    )
                })
        })
        .collect();
    let mut actual = Vec::new();
    visit_patches(repo, c, &|| false, |file, row, line| {
        actual.push((
            file.old.clone(),
            file.path.clone(),
            file.group.clone(),
            row,
            serde_json::to_value(line).unwrap(),
        ));
        Ok(true)
    })
    .unwrap();
    assert_eq!(actual, expected);
}

#[test]
fn raw_and_numstat_parsers_keep_counts_errors_and_stat_only_changes() {
    let old = "1".repeat(40);
    let new = "2".repeat(40);
    let mut raw = format!(":100644 100644 {old} {new} M\0").into_bytes();
    raw.extend_from_slice(b"literal\t\n\xff\0");
    let files = parse_raw_changes(&mut raw.split(|&b| b == 0).peekable()).unwrap();
    assert_eq!(files.len(), 1);
    assert_eq!(files[0].path, name(b"literal\t\n\xff"));
    assert_eq!((files[0].added, files[0].removed), (None, None));
    let mut summary = raw.clone();
    summary.extend_from_slice(b"2\t1\tliteral\t\n\xff\0");
    let files = parse_changes(&summary, false).unwrap();
    assert_eq!((files[0].added, files[0].removed), (Some(2), Some(1)));
    assert_eq!(
        (files[0].old_oid.as_str(), files[0].oid.as_str()),
        (old.as_str(), new.as_str())
    );
    assert!(parse_changes(&raw, false).is_err());
    for broken in [b":100644 M\0path\0".as_slice(), b":100644 100644 a b M"] {
        assert!(parse_raw_changes(&mut broken.split(|&b| b == 0).peekable()).is_err());
    }
    for count in [b"invalid\t1\tpath\0".as_slice(), b"2\0"] {
        let mut broken = raw.clone();
        broken.extend_from_slice(count);
        assert!(parse_changes(&broken, false).is_err());
    }
    let stale = format!(":100644 100644 {old} {} M\0path\0", "0".repeat(40));
    assert!(parse_changes(stale.as_bytes(), false).is_err());
    assert!(parse_changes(stale.as_bytes(), true).unwrap().is_empty());
}

#[test]
fn streamed_patches_keep_snapshot_order_rows_and_frozen_local_bytes() {
    let dir = history();
    write(&dir, "a-normal", b"one\r\ntwo\r\nlast");
    write(
        &dir,
        "b-before",
        b"one\ntwo\nthree\nfour\nfive\nsix\nseven\neight\nnine\nten\n",
    );
    write(&dir, "binary", b"before\0binary");
    write(&dir, "removed", b"removed without newline");
    record(&dir, "Base");
    write(&dir, "a-normal", b"one\r\nchanged \xff\r\nlast");
    git(dir.path(), &["mv", "b-before", "b-after"]).unwrap();
    write(
        &dir,
        "b-after",
        b"one\ntwo\nchanged\nfour\nfive\nsix\nseven\neight\nnine\nten\n",
    );
    write(&dir, "binary", b"after\0binary");
    fs::remove_file(dir.path().join("removed")).unwrap();
    write(&dir, "literal[1]\tline\nname", b"new\r\nlast");
    record(&dir, "Change");
    let repo = open_repo(dir.path()).unwrap();
    let branch = compare(&repo, "HEAD^", &repo.checkout).unwrap();
    assert!(branch.files.iter().any(|file| file.status == "R"));
    assert_streamed_rows(&repo, &branch);

    write(&dir, "a-normal", b"staged\n");
    git(dir.path(), &["add", "a-normal"]).unwrap();
    write(&dir, "a-normal", b"unstaged\n");
    write(&dir, "draft", b"untracked\r\nno newline");
    let frozen = work(&repo);
    write(&dir, "a-normal", b"later bytes\n");
    fs::remove_file(dir.path().join("draft")).unwrap();
    record(&dir, "Move refs and index");
    assert_streamed_rows(&repo, &branch);
    assert_streamed_rows(&repo, &frozen);
}

#[cfg(unix)]
#[test]
fn streamed_patches_keep_type_change_sections_and_byte_paths() {
    use std::os::unix::{ffi::OsStrExt, fs::symlink};
    let dir = history();
    let bad = OsStr::from_bytes(b"invalid\xff\t\n");
    fs::write(dir.path().join(bad), b"before\n").unwrap();
    write(&dir, "type", b"regular\n");
    record(&dir, "Base");
    fs::write(dir.path().join(bad), b"after\r\nlast").unwrap();
    fs::remove_file(dir.path().join("type")).unwrap();
    symlink("target", dir.path().join("type")).unwrap();
    record(&dir, "Change");
    let repo = open_repo(dir.path()).unwrap();
    let c = compare(&repo, "HEAD^", &repo.checkout).unwrap();
    assert!(c.files.iter().any(|file| file.status == "T"));
    assert_streamed_rows(&repo, &c);
}

#[test]
fn patch_stream_stops_at_201_matches_inside_the_first_file() {
    let dir = history();
    write(&dir, "first", b"before\n");
    record(&dir, "Base");
    write(
        &dir,
        "first",
        format!("{}tail that must not be read\n", "needle\n".repeat(300)).as_bytes(),
    );
    record(&dir, "Change");
    let repo = open_repo(dir.path()).unwrap();
    let c = compare(&repo, "HEAD^", &repo.checkout).unwrap();
    let mut args = PATCH_ARGS.to_vec();
    args.extend(["--raw", "--no-abbrev", "-z", &c.base, &c.head, "--"]);
    let data = git(&repo.root, &args).unwrap();
    let mut end = 0;
    let mut hits = 0;
    for line in data.split_inclusive(|&b| b == b'\n') {
        end += line.len();
        if line == b"+needle\n" {
            hits += 1;
        }
        if hits == 201 {
            break;
        }
    }
    struct StopAfterPrefix<'a>(io::Cursor<&'a [u8]>);
    impl Read for StopAfterPrefix<'_> {
        fn read(&mut self, out: &mut [u8]) -> io::Result<usize> {
            self.0.read(out)
        }
    }
    impl BufRead for StopAfterPrefix<'_> {
        fn fill_buf(&mut self) -> io::Result<&[u8]> {
            let bytes = self.0.fill_buf()?;
            assert!(!bytes.is_empty(), "search read beyond the 201st hit");
            Ok(bytes)
        }
        fn consume(&mut self, amount: usize) {
            self.0.consume(amount);
        }
    }
    let mut output = StopAfterPrefix(io::Cursor::new(&data[..end]));
    let mut found = 0;
    let complete = read_branch_patches(&mut output, &c, &mut |file, row, line| {
        assert_eq!(file.path, "first");
        if line.text == "needle" {
            found += 1;
        }
        if found == 201 {
            assert_eq!(row, 202);
        }
        Ok(found < 201)
    })
    .unwrap();
    assert!(!complete);
    assert_eq!(found, 201);
    #[cfg(unix)]
    {
        let prefix = dir.path().join(".git/patch-prefix");
        fs::write(&prefix, &data[..end]).unwrap();
        let child = Command::new("sh")
            .args(["-c", "cat \"$1\"; exec sleep 5", "sh"])
            .arg(prefix)
            .stdout(Stdio::piped())
            .spawn()
            .unwrap();
        let pid = child.id();
        let start = std::time::Instant::now();
        found = 0;
        read_patch_process(child, &c, &|| false, &mut |_, _, line| {
            found += usize::from(line.text == "needle");
            Ok(found < 201)
        })
        .unwrap();
        assert_eq!(found, 201);
        assert!(start.elapsed() < Duration::from_secs(1));
        assert_eq!(unsafe { libc::kill(pid as i32, 0) }, -1);
    }
}

#[test]
fn patch_reader_checks_cancellation_while_git_is_silent() {
    use std::sync::atomic::{AtomicBool, Ordering};
    let cancelled = AtomicBool::new(false);
    std::thread::scope(|scope| {
        let (_sender, receiver) = mpsc::sync_channel(2);
        let check = || cancelled.load(Ordering::Relaxed);
        let mut reader = PatchReader {
            receiver,
            bytes: Vec::new(),
            offset: 0,
            cancelled: &check,
        };
        scope.spawn(|| {
            std::thread::sleep(Duration::from_millis(5));
            cancelled.store(true, Ordering::Relaxed);
        });
        assert_eq!(
            reader.fill_buf().unwrap_err().to_string(),
            "Search superseded."
        );
    });
}

#[cfg(unix)]
#[test]
fn patch_process_is_reaped_when_a_silent_search_is_superseded() {
    use std::sync::atomic::{AtomicBool, Ordering};
    let dir = history();
    write(&dir, "code", b"before\n");
    record(&dir, "Base");
    write(&dir, "code", b"after\n");
    record(&dir, "Change");
    let repo = open_repo(dir.path()).unwrap();
    let c = compare(&repo, "HEAD^", &repo.checkout).unwrap();
    let child = Command::new("sh")
        .args(["-c", "exec sleep 5"])
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    let pid = child.id();
    let cancelled = AtomicBool::new(false);
    let start = std::time::Instant::now();
    std::thread::scope(|scope| {
        scope.spawn(|| {
            std::thread::sleep(Duration::from_millis(5));
            cancelled.store(true, Ordering::Relaxed);
        });
        let result = read_patch_process(
            child,
            &c,
            &|| cancelled.load(Ordering::Relaxed),
            &mut |_, _, _| panic!("a silent child emitted a patch row"),
        );
        assert_eq!(result.unwrap_err(), "Search superseded.");
    });
    assert!(
        start.elapsed() < Duration::from_secs(1),
        "reader did not stop with the canceled child"
    );
    assert_eq!(
        unsafe { libc::kill(pid as i32, 0) },
        -1,
        "child was not reaped"
    );
}

#[test]
fn whole_file_keeps_branch_blob_ids_after_a_rename_and_tip_move() {
    let dir = history();
    let root = dir.path();
    write(&dir, "before", b"first\r\nlast\n");
    write(&dir, "image", b"binary\0data");
    write(&dir, "removed", b"old text");
    record(&dir, "Base");
    git(root, &["mv", "before", "after"]).unwrap();
    git(root, &["rm", "removed"]).unwrap();
    write(&dir, "created", b"new text\n\n");
    record(&dir, "Rename");
    let repo = open_repo(root).unwrap();
    let c = compare(&repo, "HEAD^", &repo.checkout).unwrap();
    write(&dir, "after", b"later content\n");
    record(&dir, "Move tip");

    let renamed = file_contents(&repo, file(&c, "", "after")).unwrap();
    assert_eq!(renamed, ["first", "last"]);
    let created = file_contents(&repo, file(&c, "", "created")).unwrap();
    assert_eq!(created, ["new text", ""]);
    let removed = file_contents(&repo, file(&c, "", "removed")).unwrap();
    assert!(removed.is_empty());
    assert!(matches!(revision_file(&repo, &c.head, "after").unwrap(),
        RevisionFile::Text { lines } if lines == renamed));
    assert!(revision_file(&repo, &c.head, "before").is_err());
    assert!(matches!(revision_file(&repo, &c.head, "image").unwrap(),
        RevisionFile::Binary { bytes: 11 }));
}

#[test]
fn whole_file_reconstructs_unstaged_gaps_after_the_index_and_disk_change() {
    let dir = history();
    let base: Vec<_> = (1..=60).map(|n| format!("line {n}")).collect();
    write(&dir, "code", base.join("\r\n").as_bytes());
    record(&dir, "Base");
    let mut staged = base.clone();
    staged[20] = "staged".into();
    write(&dir, "code", staged.join("\r\n").as_bytes());
    git(dir.path(), &["add", "code"]).unwrap();
    let mut live = staged.clone();
    live.insert(6, "inserted".into());
    live.remove(32);
    live[46] = "replaced".into();
    write(&dir, "code", live.join("\r\n").as_bytes());
    write(&dir, "draft", b"new\r\n\xff");
    let repo = open_repo(dir.path()).unwrap();
    let c = work(&repo);
    write(&dir, "code", b"completely different");
    write(&dir, "draft", b"later draft");
    record(&dir, "Commit other edits");

    let index = file_contents(&repo, file(&c, "Staged", "code")).unwrap();
    assert_eq!(index, staged);
    let working = file_contents(&repo, file(&c, "Unstaged", "code")).unwrap();
    assert_eq!(working, live);
    let draft = file_contents(&repo, file(&c, "Untracked", "draft")).unwrap();
    assert_eq!(draft, ["new", "�"]);
}

#[test]
fn first_commit_diverged_base_stack_and_forks() {
    let dir = history();
    let root = dir.path();
    let repo = open_repo(root).unwrap();
    assert!(repo.initial.is_empty());
    write(&dir, "code", b"base\n");
    record(&dir, "Base");
    let repo = open_repo(root).unwrap();
    assert_eq!(repo.initial, [EMPTY, "refs/heads/main"]);
    assert_eq!(
        commits(&repo, &compare(&repo, EMPTY, &repo.checkout).unwrap()).unwrap()[0].subject,
        "Base"
    );
    git(root, &["switch", "-qc", "policy"]).unwrap();
    write(&dir, "code", b"policy\n");
    record(&dir, "Policy");
    git(root, &["switch", "-qc", "metrics"]).unwrap();
    write(&dir, "code", b"metrics\n");
    record(&dir, "Metrics");
    git(root, &["switch", "main"]).unwrap();
    write(&dir, "extra", b"main only\n");
    record(&dir, "Unrelated");
    git(root, &["switch", "metrics"]).unwrap();
    let repo = open_repo(root).unwrap();
    let [base, middle, tip] = ["refs/heads/main", "refs/heads/policy", "refs/heads/metrics"];
    let (chain, forks) = discover_stack(&repo, base, middle).unwrap();
    assert_eq!(chain, [base, middle, tip]);
    assert!(forks.is_empty());
    let c = compare(&repo, base, tip).unwrap();
    assert_ne!(c.left_tip, c.base);
    assert_eq!(c.files.len(), 1);
    assert_eq!(content(&repo, &c, "", "code"), ["base", "metrics"]);
    let log = commits(&repo, &c).unwrap();
    assert_eq!(
        log.iter().map(|v| v.subject.as_str()).collect::<Vec<_>>(),
        ["Metrics", "Policy"]
    );
    let details = commit_details(&repo, &log[0].sha).unwrap();
    assert!(details.contains("Author:") && details.contains("Metrics") && details.contains("code"));
    assert!(commit_details(&repo, "--all").is_err());
    git(root, &["switch", "-qc", "expiry", middle]).unwrap();
    write(&dir, "expiry", b"time\n");
    record(&dir, "Expiry");
    let (chain, forks) = discover_stack(&open_repo(root).unwrap(), base, middle).unwrap();
    assert_eq!(chain, [base, middle]);
    assert_eq!(forks, ["refs/heads/expiry", tip]);
}

#[test]
fn advertised_remote_default_and_orphan_and_detached_checkout() {
    let dir = history();
    let root = dir.path();
    write(&dir, "start", b"start\n");
    record(&dir, "Start");
    git(
        root,
        &["update-ref", "refs/remotes/origin/release/stable", "HEAD"],
    )
    .unwrap();
    git(
        root,
        &[
            "symbolic-ref",
            "refs/remotes/origin/HEAD",
            "refs/remotes/origin/release/stable",
        ],
    )
    .unwrap();
    let repo = open_repo(root).unwrap();
    assert_eq!(
        repo.initial,
        ["refs/remotes/origin/release/stable", "refs/heads/main"]
    );
    git(root, &["switch", "--detach"]).unwrap();
    let repo = open_repo(root).unwrap();
    assert_eq!(repo.checkout, format!("HEAD@{}", work(&repo).base));
    git(root, &["switch", "--orphan", "orphan"]).unwrap();
    let orphan = open_repo(root).unwrap();
    assert_eq!(orphan.checkout, "refs/heads/orphan");
    assert_eq!(work(&orphan).base, orphan.refs[EMPTY]);
}

#[test]
fn partially_staged_snapshot_survives_file_and_index_changes() {
    let dir = history();
    let root = dir.path();
    write(&dir, "code", b"base\n");
    write(&dir, ".gitignore", b"ignored\n");
    record(&dir, "Base");
    write(&dir, "code", b"staged\n");
    git(root, &["add", "code"]).unwrap();
    write(&dir, "code", b"working\n");
    write(&dir, "-", b"new file\n");
    write(&dir, "ignored", b"skip\n");
    let index = fs::read(root.join(".git/index")).unwrap();
    let repo = open_repo(root).unwrap();
    let c = work(&repo);
    assert_eq!(c.files.len(), 3);
    assert_eq!(c.files[0].oid, c.files[1].old_oid);
    assert_eq!(index, fs::read(root.join(".git/index")).unwrap());
    write(&dir, "code", b"later\n");
    fs::remove_file(root.join("-")).unwrap();
    git(root, &["add", "code"]).unwrap();
    assert_eq!(content(&repo, &c, "Staged", "code"), ["base", "staged"]);
    assert_eq!(
        content(&repo, &c, "Unstaged", "code"),
        ["staged", "working"]
    );
    assert_eq!(content(&repo, &c, "Untracked", "-"), ["new file"]);
    assert_ne!(work(&repo).head, c.head);
    record(&dir, "Moved branch");
    assert!(compare(&repo, &repo.checkout, WORKTREE).is_err());
}

#[test]
fn working_tree_snapshot_does_not_rewrite_stat_stale_index() {
    let dir = history();
    let root = dir.path();
    write(&dir, "unchanged", b"same content\n");
    write(&dir, "staged", b"base\n");
    write(&dir, "unstaged", b"base\n");
    record(&dir, "Base");

    write(&dir, "staged", b"staged\n");
    git(root, &["add", "staged"]).unwrap();
    write(&dir, "unstaged", b"unstaged\n");
    write(&dir, "untracked", b"untracked\n");
    // A copied checkout can have stale file metadata without a content change.
    fs::OpenOptions::new()
        .write(true)
        .open(root.join("unchanged"))
        .unwrap()
        .set_modified(std::time::UNIX_EPOCH + std::time::Duration::from_secs(1_000_000_000))
        .unwrap();

    let index = fs::read(root.join(".git/index")).unwrap();
    let repo = open_repo(root).unwrap();
    let c = work(&repo);
    assert_eq!(c.files.len(), 3);
    assert_eq!(content(&repo, &c, "Staged", "staged"), ["base", "staged"]);
    assert_eq!(content(&repo, &c, "Unstaged", "unstaged"), ["base", "unstaged"]);
    assert_eq!(content(&repo, &c, "Untracked", "untracked"), ["untracked"]);
    assert_eq!(index, fs::read(root.join(".git/index")).unwrap());
}

#[test]
fn literal_names_binary_rename_line_numbers_and_scoped_untracked() {
    let dir = history();
    let root = dir.path();
    let text = (1..24)
        .map(|i| {
            if i == 2 {
                "\n".into()
            } else {
                format!("line {i}\n")
            }
        })
        .collect::<String>();
    write(&dir, "name[1]", text.as_bytes());
    write(&dir, "before", b"rename only\n");
    record(&dir, "Base");
    git(root, &["mv", "before", "after"]).unwrap();
    git(root, &["config", "diff.suppressBlankEmpty", "true"]).unwrap();
    write(
        &dir,
        "name[1]",
        text.replace("line 3\n", "+++ hello\n")
            .replace("line 22\n", "zzz\n")
            .as_bytes(),
    );
    write(&dir, "image", b"binary\0image");
    record(&dir, "Changes");
    let repo = open_repo(root).unwrap();
    let c = compare(&repo, "HEAD^", &repo.checkout).unwrap();
    let renamed = file(&c, "", "after");
    assert_eq!(renamed.old, "before");
    assert_eq!(renamed.status, "R");
    assert!(patch(&repo, &c, renamed).unwrap().is_empty());
    assert_eq!(file(&c, "", "image").added, None);
    let lines = patch(&repo, &c, file(&c, "", "name[1]")).unwrap();
    assert_eq!(
        lines
            .iter()
            .filter(|l| l.kind == "-")
            .map(|l| (l.old.unwrap(), l.hunk))
            .collect::<Vec<_>>(),
        [(3, 1), (22, 2)]
    );
    write(&dir, "a", b"new\n");
    write(&dir, "b", b"skip\n");
    let paths = HashSet::from(["a".to_owned()]);
    let scoped = working_tree(&repo, &repo.checkout, Some(&paths)).unwrap();
    assert_eq!(scoped.files.len(), 1);
    assert_eq!(scoped.files[0].path, "a");
}

#[test]
fn merge_conflict_shows_existing_stage_two_and_other_staged_changes() {
    let dir = history();
    let root = dir.path();
    write(&dir, "shared", b"base\n");
    record(&dir, "Base");
    git(root, &["switch", "-qc", "other"]).unwrap();
    write(&dir, "shared", b"theirs\n");
    record(&dir, "Theirs");
    git(root, &["switch", "main"]).unwrap();
    write(&dir, "shared", b"ours\n");
    record(&dir, "Ours");
    assert!(git(root, &["merge", "other"]).is_err());
    write(&dir, "new", b"staged\n");
    git(root, &["add", "new"]).unwrap();
    let repo = open_repo(root).unwrap();
    let c = work(&repo);
    assert_eq!(c.files.len(), 2);
    assert_eq!(file(&c, "Unstaged", "shared").status, "U");
    assert!(content(&repo, &c, "Unstaged", "shared").contains(&"<<<<<<< HEAD".to_owned()));
    let conflict = file_contents(&repo, file(&c, "Unstaged", "shared")).unwrap();
    assert_eq!(
        conflict.join("\n") + "\n",
        fs::read_to_string(root.join("shared")).unwrap()
    );
    assert_eq!(content(&repo, &c, "Staged", "new"), ["staged"]);
}

#[cfg(unix)]
#[test]
fn symlinks_type_changes_nested_repo_and_non_utf8_names() {
    use std::os::unix::{ffi::OsStrExt, fs::symlink};
    let dir = history();
    let root = dir.path();
    write(&dir, "type", b"regular\n");
    record(&dir, "Base");
    fs::remove_file(root.join("type")).unwrap();
    symlink("target", root.join("type")).unwrap();
    symlink(".", root.join("dirlink")).unwrap();
    let bad = OsStr::from_bytes(b"invalid\xff");
    fs::write(root.join(bad), b"unusual name\n").unwrap();
    fs::create_dir(root.join("nested")).unwrap();
    git(&root.join("nested"), &["init", "-q"]).unwrap();
    let repo = open_repo(root).unwrap();
    let c = work(&repo);
    assert_eq!(file(&c, "Untracked", "dirlink").mode, "120000");
    assert_eq!(content(&repo, &c, "Untracked", "dirlink"), ["."]);
    assert_eq!(
        content(&repo, &c, "Unstaged", "type"),
        ["regular", "target"]
    );
    assert_eq!(
        content(&repo, &c, "Untracked", &name(bad.as_bytes())),
        ["unusual name"]
    );
    assert_eq!(file(&c, "Untracked", "nested").mode, "160000");
    assert!(file_contents(&repo, file(&c, "Untracked", "nested")).is_err());
    let changed = file_contents(&repo, file(&c, "Unstaged", "type")).unwrap();
    assert_eq!(changed, ["target"]);
    fs::remove_dir_all(root.join("nested")).unwrap();
    record(&dir, "Links and names");
    let repo = open_repo(root).unwrap();
    let c = compare(&repo, "HEAD^", &repo.checkout).unwrap();
    assert!(matches!(
        revision_file(&repo, &c.head, &name(bad.as_bytes())).unwrap(),
        RevisionFile::Text { lines } if lines == ["unusual name"]
    ));
    assert_eq!(
        content(&repo, &c, "", &name(bad.as_bytes())),
        ["unusual name"]
    );
}

#[test]
fn revision_file_distinguishes_text_binary_and_missing_submodule_objects() {
    let dir = history();
    write(&dir, "text", b"first\r\nlast\n");
    write(&dir, "empty", b"");
    write(&dir, "asset.png", b"binary\0data");
    record(&dir, "Source files");
    // Gitlinks need not have their target commit in the superproject database.
    let target = "1234567890123456789012345678901234567890";
    git(dir.path(), &["update-index", "--add", "--cacheinfo",
        &format!("160000,{target},vendor/module")]).unwrap();
    git(dir.path(), &["commit", "-qm", "Submodule pointer"]).unwrap();
    let repo = open_repo(dir.path()).unwrap();
    let revision = &repo.refs["refs/heads/main"];
    assert!(matches!(revision_file(&repo, revision, "text").unwrap(),
        RevisionFile::Text { lines } if lines == ["first", "last"]));
    assert!(matches!(revision_file(&repo, revision, "empty").unwrap(),
        RevisionFile::Text { lines } if lines.is_empty()));
    assert!(matches!(revision_file(&repo, revision, "asset.png").unwrap(),
        RevisionFile::Binary { bytes: 11 }));
    assert!(matches!(revision_file(&repo, revision, "vendor/module").unwrap(),
        RevisionFile::Submodule { oid } if oid == target));
    assert!(revision_file(&repo, revision, "absent").is_err());
}
