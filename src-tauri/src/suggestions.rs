//! Apply only a saved, verified replacement to a regular working file.
use crate::git::{self, Change, Comparison, Repository, EMPTY, WORKTREE};
use crate::review::{remember_receipt, span, suggestion_source, Store};
use crate::tracking::oid;
use serde_json::{json, Value};
use sha2::Digest;
use std::{
    fs::{File, OpenOptions},
    io::{self, Read, Write},
    path::{Component, Path, PathBuf},
};

const CHANGED: &str = "The file changed during Apply. Refresh and review the suggestion again.";
const STALE:&str="The original selection cannot be verified in the working file. Review the current working-tree diff and create a suggestion there.";
fn error(e: impl std::fmt::Display) -> String {
    e.to_string()
}

#[cfg(windows)]
fn invalid_component(s: &str) -> bool {
    let stem = s.split('.').next().unwrap_or(s).trim_end().to_uppercase();
    s.ends_with([' ', '.'])
        || s.chars().any(|c| c < ' ' || "<>:\"\\|?*".contains(c))
        || matches!(
            stem.as_str(),
            "NUL" | "CON" | "AUX" | "PRN" | "CONIN$" | "CONOUT$"
        )
        || (stem.starts_with("COM") || stem.starts_with("LPT"))
            && matches!(
                stem.get(3..),
                Some("1" | "2" | "3" | "4" | "5" | "6" | "7" | "8" | "9" | "¹" | "²" | "³")
            )
}
fn reject_link(path: &Path) -> Result<(), String> {
    let metadata = path.symlink_metadata().map_err(error)?;
    let linked = metadata.is_symlink();
    #[cfg(windows)]
    let linked = {
        use std::os::windows::fs::MetadataExt;
        linked || metadata.file_attributes() & 0x400 != 0
    };
    if linked {
        return Err("Suggestions can only be applied to files outside symbolic links.".into());
    }
    Ok(())
}
fn working_path(root: &Path, name: &str) -> Result<PathBuf, String> {
    let relative = git::working_path(Path::new(""), name)?;
    let path_bytes = relative.as_os_str().as_encoded_bytes();
    if path_bytes.is_empty()
        || path_bytes.starts_with(b"\\")
        || path_bytes.get(1) == Some(&b':') && path_bytes[0].is_ascii_alphabetic()
        || path_bytes
            .split(|b| *b == b'/')
            .any(|p| p.is_empty() || p == b"." || p == b".." || p.eq_ignore_ascii_case(b".git"))
    {
        return Err("Choose a file inside the working tree.".into());
    }
    #[cfg(windows)]
    if path_bytes.contains(&b'\\') {
        return Err("Choose a regular working-tree path.".into());
    }
    reject_link(root)?;
    let mut path = root.to_owned();
    for part in relative.components() {
        let Component::Normal(part) = part else {
            return Err("Choose a file inside the working tree.".into());
        };
        #[cfg(windows)]
        if invalid_component(&part.to_string_lossy()) {
            return Err("Choose a regular working-tree path.".into());
        }
        path.push(part);
        reject_link(&path)?;
    }
    if !path.is_file() {
        return Err("Choose a regular UTF-8 text file.".into());
    }
    Ok(path)
}
fn blob(data: &[u8], reference: &str) -> String {
    let header = format!("blob {}\0", data.len());
    if reference.len() == 64 {
        let mut h = sha2::Sha256::new();
        h.update(header.as_bytes());
        h.update(data);
        format!("{:x}", h.finalize())
    } else {
        let mut h = sha1::Sha1::new();
        h.update(header.as_bytes());
        h.update(data);
        format!("{:x}", h.finalize())
    }
}
fn ending(row: &str) -> &str {
    if row.ends_with("\r\n") {
        "\r\n"
    } else if row.ends_with('\n') {
        "\n"
    } else {
        ""
    }
}
fn verify(
    root: &Path,
    data: &str,
    content: &[&str],
    start: usize,
    wanted: &[&str],
    reference: &str,
    original_start: usize,
) -> Result<(), String> {
    if !oid(reference) {
        return Err(STALE.into());
    }
    if blob(data.as_bytes(), reference) == reference
        || (data.contains("\r\n")
            && blob(data.replace("\r\n", "\n").as_bytes(), reference) == reference)
    {
        return if start == original_start {
            Ok(())
        } else {
            Err(STALE.into())
        };
    }
    let original =
        git::blob_bytes(root, reference).map_err(|_| STALE.to_string())?;
    if blob(&original, reference) != reference {
        return Err(STALE.into());
    }
    let original = std::str::from_utf8(&original)
        .map_err(|_| STALE)?
        .replace("\r\n", "\n");
    let original: Vec<_> = original.split_terminator('\n').collect();
    let Some(offset) = start.checked_sub(original_start) else {
        return Err(STALE.into());
    };
    let Some(end) = original_start.checked_add(wanted.len()) else {
        return Err(STALE.into());
    };
    if original.get(..end) != content.get(offset..start + wanted.len())
        || [(&original[..], original_start), (content, start)]
            .iter()
            .any(|(rows, selected)| {
                rows.windows(wanted.len())
                    .enumerate()
                    .any(|(i, window)| i != *selected && window == wanted)
            })
    {
        return Err(STALE.into());
    }
    Ok(())
}
struct Replacement<'a> {
    first: usize,
    last: usize,
    reviewed_first: usize,
    expected: &'a str,
    replacement: &'a str,
    reference: &'a str,
}
impl Replacement<'_> {
    fn apply_to(&self, root: &Path, bytes: &[u8]) -> Result<Vec<u8>, String> {
        if bytes.contains(&0) || self.replacement.contains('\0') {
            return Err("Suggestions can only be applied to UTF-8 text.".into());
        }
        let original = std::str::from_utf8(bytes)
            .map_err(|_| "Suggestions can only be applied to UTF-8 text.")?;
        let rows: Vec<_> = original.split_inclusive('\n').collect();
        let content: Vec<_> = rows
            .iter()
            .map(|row| row.strip_suffix(ending(row)).unwrap())
            .collect();
        let wanted: Vec<_> = self.expected.split('\n').collect();
        let start = self.first.checked_sub(1).ok_or(STALE)?;
        let last = self.last;
        if content.get(start..last) != Some(wanted.as_slice()) {
            return Err(
                "The selected lines have changed. Refresh and review the suggestion again.".into(),
            );
        }
        verify(
            root,
            original,
            &content,
            start,
            &wanted,
            self.reference,
            self.reviewed_first.checked_sub(1).ok_or(STALE)?,
        )?;
        let mut result = rows[..start].concat();
        let last_end = ending(rows[last - 1]);
        if self.replacement.is_empty() {
            if last == rows.len() && last_end.is_empty() {
                result.truncate(result.len() - ending(&result).len());
            }
        } else {
            let mut preferred = ending(rows[start]);
            if preferred.is_empty() {
                preferred = ending(&result);
            }
            if preferred.is_empty() {
                preferred = "\n";
            }
            let preferred = preferred.to_owned();
            let replacement = self.replacement.replace("\r\n", "\n");
            let mut new = replacement.split('\n').enumerate().peekable();
            while let Some((i, word)) = new.next() {
                result.push_str(word);
                let delimiter = if new.peek().is_none() {
                    last_end
                } else {
                    rows[start..last]
                        .get(i)
                        .map(|row| ending(row))
                        .filter(|s| !s.is_empty())
                        .unwrap_or(&preferred)
                };
                result.push_str(delimiter);
            }
        }
        for line in &rows[last..] {
            result.push_str(line);
        }
        Ok(result.into_bytes())
    }
}
#[cfg(unix)]
#[derive(PartialEq)]
struct Identity(u64, u64, u64, u32, u64, i64, i64, i64, i64);
#[cfg(unix)]
fn identity(file: &File) -> io::Result<Identity> {
    use std::os::unix::fs::MetadataExt;
    let m = file.metadata()?;
    Ok(Identity(
        m.dev(),
        m.ino(),
        m.nlink(),
        m.mode(),
        m.size(),
        m.mtime(),
        m.mtime_nsec(),
        m.ctime(),
        m.ctime_nsec(),
    ))
}
#[cfg(windows)]
#[derive(PartialEq)]
struct Identity(u32, u64, u64, u32, u64, u64);
#[cfg(windows)]
fn identity(file: &File) -> io::Result<Identity> {
    use std::os::windows::io::AsRawHandle;
    use windows_sys::Win32::Storage::FileSystem::{
        GetFileInformationByHandle, BY_HANDLE_FILE_INFORMATION,
    };
    let mut info = std::mem::MaybeUninit::<BY_HANDLE_FILE_INFORMATION>::uninit();
    // The handle stays open while Windows initializes the structure.
    if unsafe { GetFileInformationByHandle(file.as_raw_handle(), info.as_mut_ptr()) } == 0 {
        return Err(io::Error::last_os_error());
    }
    let m = unsafe { info.assume_init() };
    let pair = |a: u32, b: u32| (u64::from(a) << 32) | u64::from(b);
    Ok(Identity(
        m.dwVolumeSerialNumber,
        pair(m.nFileIndexHigh, m.nFileIndexLow),
        m.nNumberOfLinks.into(),
        m.dwFileAttributes,
        pair(m.nFileSizeHigh, m.nFileSizeLow),
        pair(
            m.ftLastWriteTime.dwHighDateTime,
            m.ftLastWriteTime.dwLowDateTime,
        ),
    ))
}
fn read_file(path: &Path) -> Result<(File, Identity, Vec<u8>), String> {
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK);
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        options.custom_flags(0x00200000);
    }
    let mut file = options.open(path).map_err(error)?;
    let m = file.metadata().map_err(error)?;
    if !m.is_file() || m.is_symlink() {
        return Err("Choose a regular UTF-8 text file.".into());
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        if m.file_attributes() & 0x400 != 0 {
            return Err("Choose a regular UTF-8 text file.".into());
        }
    }
    let stamp = identity(&file).map_err(error)?;
    if stamp.2 > 1 {
        return Err(
            "This file has hard links. Edit it directly to preserve the linked files.".into(),
        );
    }
    if m.permissions().readonly() {
        return Err("The working file is read-only.".into());
    }
    let mut bytes = Vec::new();
    file.read_to_end(&mut bytes).map_err(error)?;
    if identity(&file).map_err(error)? != stamp {
        return Err(CHANGED.into());
    }
    Ok((file, stamp, bytes))
}
#[cfg(unix)]
fn copy_metadata(file: &File, temp: &File) -> io::Result<()> {
    use std::collections::HashSet;
    use std::os::unix::{fs::MetadataExt, io::AsRawFd};
    use xattr::FileExt;
    let from = file.metadata()?;
    let to = temp.metadata()?;
    if (from.uid(), from.gid()) != (to.uid(), to.gid()) {
        // The destination is our open temporary file.
        if unsafe { libc::fchown(temp.as_raw_fd(), from.uid(), from.gid()) } != 0 {
            return Err(io::Error::last_os_error());
        }
    }
    temp.set_permissions(from.permissions())?;
    let original: HashSet<_> = file.list_xattr()?.collect();
    for name in temp.list_xattr()? {
        if !original.contains(&name) {
            temp.remove_xattr(name)?;
        }
    }
    for name in original {
        let value = file
            .get_xattr(&name)?
            .ok_or_else(|| io::Error::other(CHANGED))?;
        if temp.get_xattr(&name)?.as_ref() != Some(&value) {
            temp.set_xattr(&name, &value)?;
        }
    }
    Ok(())
}
#[cfg(windows)]
fn replace(temp: tempfile::NamedTempFile, target: &Path) -> Result<(), String> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Storage::FileSystem::ReplaceFileW;
    let temporary = temp.into_temp_path();
    let mut backup_name = temporary.as_os_str().to_owned();
    backup_name.push(".original");
    let backup = PathBuf::from(backup_name);
    fn wide(p: &Path) -> Vec<u16> {
        p.as_os_str().encode_wide().chain([0]).collect()
    }
    let (target_w, temp_w, backup_w) = (wide(target), wide(&temporary), wide(&backup));
    // ReplaceFile preserves the destination ACL and alternate data streams.
    let ok = unsafe {
        ReplaceFileW(
            target_w.as_ptr(),
            temp_w.as_ptr(),
            backup_w.as_ptr(),
            0,
            std::ptr::null(),
            std::ptr::null(),
        )
    };
    if ok == 0 {
        let e = io::Error::last_os_error();
        if backup.exists() && !target.exists() && std::fs::rename(&backup, target).is_err() {
            return Err(format!(
                "Could not restore the original file. Its backup is at {}.",
                backup.display()
            ));
        }
        return Err(error(e));
    }
    if let Err(e) = std::fs::remove_file(&backup) {
        eprintln!(
            "Could not remove the suggestion backup {}: {e}",
            backup.display()
        );
    }
    Ok(())
}
fn replace_file(repo: &Repository, path: &str, request: &Replacement) -> Result<String, String> {
    let target = working_path(&repo.root, path)?;
    let (source, stamp, original) = read_file(&target)?;
    let result = request.apply_to(&repo.root, &original)?;
    if original == result {
        return Err("The file already contains this replacement.".into());
    }
    let mut temp = tempfile::Builder::new()
        .prefix(".branchline-")
        .tempfile_in(target.parent().ok_or(STALE)?)
        .map_err(error)?;
    temp.write_all(&result).map_err(error)?;
    #[cfg(unix)]
    copy_metadata(&source, temp.as_file()).map_err(error)?;
    drop(source);
    temp.as_file().sync_all().map_err(error)?;
    let (_, current_stamp, current) = read_file(&working_path(&repo.root, path)?)?;
    if stamp != current_stamp || original != current {
        return Err(CHANGED.into());
    }
    #[cfg(unix)]
    temp.persist(&target).map_err(error)?;
    #[cfg(windows)]
    replace(temp, &target)?;
    Ok(blob(&result, request.reference))
}
pub fn apply(
    store: &mut Store,
    repo: &Repository,
    c: &Comparison,
    f: &Change,
    note: &Value,
    anchor: &Value,
) -> Result<(), String> {
    let id = note["id"]
        .as_i64()
        .ok_or("Save this suggestion before applying it.")?;
    let checkout = if repo.checkout.starts_with("HEAD@") {
        "HEAD"
    } else {
        &repo.checkout
    };
    if !matches!(f.mode.as_str(), "100644" | "100755")
        || !(c.right == checkout || (c.right == WORKTREE && c.left == repo.checkout))
    {
        return Err("Choose a suggestion on a regular file in the checked-out revision.".into());
    }
    let (first, last) = span(anchor, "new").ok_or(STALE)?;
    let head = if c.right == WORKTREE {
        &c.left_tip
    } else {
        &c.head
    };
    let mut receipt = None;
    let result = store.edit(repo, id, |current, resolved| {
        let code = current["suggestion"]
            .as_str()
            .ok_or("The comment has no suggestion.")?;
        if resolved
            || current["applied_location"].is_object()
            || current["suggestion"] != note["suggestion"]
        {
            return Err("Refresh to review the latest version before applying.".into());
        }
        let expected_checkout = (
            repo.checkout.clone(),
            (head != &repo.refs[EMPTY]).then(|| head.clone()),
        );
        if git::checkout_state(&repo.root) != expected_checkout {
            return Err("The checked-out revision changed. Refresh before applying.".into());
        }
        let expected = suggestion_source(current);
        let reference = if current["right"] == WORKTREE {
            current["file_version"][1].as_str().ok_or(STALE)?
        } else {
            &f.oid
        };
        let reviewed_first = span(current, "new").ok_or(STALE)?.0;
        let request = Replacement {
            first,
            last,
            reviewed_first,
            expected: &expected,
            replacement: code,
            reference,
        };
        let changed = replace_file(repo, &f.path, &request)?;
        let deletion = code.is_empty();
        let sign = if deletion { '-' } else { '+' };
        let text = if deletion { expected.as_str() } else { code };
        let excerpt: Vec<_> = text
            .split('\n')
            .map(|line| format!("{sign}{line}"))
            .collect();
        let applied = json!({
            "left": repo.checkout, "right": WORKTREE, "left_tip": head,
            "path": f.path, "old_path": f.path,
            "old": if deletion { json!([first, last]) } else { json!([]) },
            "new": if deletion { json!([]) } else { json!([first, first + excerpt.len() - 1]) },
            "group": if f.group == "Untracked" { "Untracked" } else { "Unstaged" },
            "file_version": [f.oid, changed, f.mode, f.mode], "excerpt": excerpt.join("\n")
        });
        current["applied_location"] =
            json!({ "path": f.path, "new": [first,last], "branch": repo.checkout });
        current["applied_anchor"] = applied;
        receipt = Some(current.clone());
        Ok(())
    });
    if let Err(e) = result {
        if let Some(receipt) = receipt {
            remember_receipt(repo, id, receipt);
            return Err(format!("The file was updated. SQLite could not save its receipt. Export the review before closing Branchline to keep the application record.\n{e}"));
        }
        return Err(e);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn edit<'a>(oid: &'a str, expected: &'a str, replacement: &'a str) -> Replacement<'a> {
        Replacement {
            first: 2,
            last: 2,
            reviewed_first: 2,
            expected,
            replacement,
            reference: oid,
        }
    }
    #[test]
    fn preserves_mixed_line_endings_and_deletes_at_eof() {
        let data = b"a\r\nb\r\nc";
        let hash = blob(data, "");
        assert_eq!(
            edit(&hash, "b", "x\ny")
                .apply_to(Path::new("."), data)
                .unwrap(),
            b"a\r\nx\r\ny\r\nc"
        );
        let mut request = edit(&hash, "c", "");
        request.first = 3;
        request.last = 3;
        request.reviewed_first = 3;
        assert_eq!(request.apply_to(Path::new("."), data).unwrap(), b"a\r\nb");
        assert!(edit(&hash, "b", "evil\0bytes")
            .apply_to(Path::new("."), data)
            .is_err());
    }
    #[test]
    fn stale_duplicate_selection_cannot_edit_an_unrelated_block() {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path();
        git::git(root, &["init", "-q"]).unwrap();
        let reviewed = "fn read():\n    return 30\n\nfn write():\n    return 30\n";
        let file = root.join("settings");
        std::fs::write(&file, reviewed).unwrap();
        let hash = String::from_utf8(
            git::git(root, &["hash-object", "-w", "--no-filters", "settings"]).unwrap(),
        )
        .unwrap();
        let request = edit(hash.trim(), "    return 30", "    return 15");
        let current = b"fn write():\n    return 30\n";
        assert!(request
            .apply_to(root, current)
            .unwrap_err()
            .contains("working-tree"));
        let shifted = format!("// header\n{reviewed}");
        let mut shifted_request = request;
        shifted_request.first = 3;
        shifted_request.last = 3;
        assert!(shifted_request.apply_to(root, shifted.as_bytes()).is_err());
    }
    #[test]
    fn refuses_hard_links_and_paths_outside_the_checkout() {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path();
        let original = root.join("settings");
        std::fs::write(&original, "test").unwrap();
        std::fs::hard_link(&original, root.join("linked")).unwrap();
        assert!(read_file(&original).err().unwrap().contains("hard links"));
        for path in [
            "../source",
            ".git/HEAD",
            "/outside",
            "C:\\outside",
            "./settings",
            "settings/../settings",
        ] {
            assert!(working_path(root, path).is_err(), "{path}");
        }
        #[cfg(unix)]
        {
            let link = root.join("symlink");
            std::os::unix::fs::symlink(dir.path(), &link).unwrap();
            assert!(working_path(root, "symlink/settings").is_err());
            assert!(working_path(&link, "settings").is_err());
        }
    }
    #[cfg(windows)]
    #[test]
    fn reserved_windows_paths_are_rejected() {
        for name in [
            "COM1",
            "NUL.txt",
            "name.",
            "name ",
            "test:stream",
            "dir\\file",
            "CONIN$",
        ] {
            assert!(invalid_component(name), "{name}");
        }
    }
}
