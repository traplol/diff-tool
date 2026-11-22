"""Apply a reviewed replacement to a specific range in a working file."""

import hashlib
import logging
import ntpath
import os
import re
import stat
import tempfile
from pathlib import Path, PureWindowsPath

from .git import GitError, git


class SuggestionError(Exception):
    """The working file cannot safely accept this replacement."""


def _invalid_windows_component(part):
    if "\\" in part or ":" in part or part.rstrip(" .") != part:
        return True
    if hasattr(ntpath, "isreserved"):
        return ntpath.isreserved(part)
    return PureWindowsPath(part).is_reserved()  # Python 3.10–3.12


def _working_path(root, name):
    if not isinstance(name, str) or not name or "\0" in name or PureWindowsPath(name).anchor:
        raise SuggestionError("Choose a file inside the repository.")
    parts = name.split("/")
    if any(part in ("", ".", "..") or part.casefold() == ".git" for part in parts):
        raise SuggestionError("Choose a file inside the working tree.")
    if os.name == "nt" and any(_invalid_windows_component(part) for part in parts):
        raise SuggestionError("Choose a regular working-tree path.")
    target = root
    for part in ("", *parts):
        target = target / part
        info = target.lstat()
        if (
            stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise SuggestionError("Suggestions can only be applied to files outside symbolic links.")
    if not stat.S_ISREG(info.st_mode):
        raise SuggestionError("Choose a regular UTF-8 text file.")
    return target


def _version(info):
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _read(target):
    flags = (
        os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    )
    with os.fdopen(os.open(target, flags), "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise SuggestionError("Choose a regular UTF-8 text file.")
        data = source.read()
        if _version(info) != _version(os.fstat(source.fileno())):
            raise SuggestionError("The file changed during Apply. Refresh and review the suggestion again.")
        return data, info


def _blob_oid(data, reference):
    algorithm = "sha256" if len(reference or "") == 64 else "sha1"
    header = b"blob " + str(len(data)).encode("ascii") + b"\0"
    return hashlib.new(algorithm, header + data).hexdigest()


def _same_blob(data, oid):
    return bool(oid) and (
        _blob_oid(data, oid) == oid or (b"\r\n" in data and _blob_oid(data.replace(b"\r\n", b"\n"), oid) == oid)
    )


def _line_end(line):
    if line.endswith(b"\r\n"):
        return b"\r\n"
    return b"\n" if line.endswith(b"\n") else b""


def _verify_range(root, data, content, start, wanted, oid, reviewed_start):
    stale = (
        "The original selection cannot be verified in the working file. "
        "Review the current working-tree diff and create a suggestion there."
    )
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", oid or ""):
        raise SuggestionError(stale)
    if _same_blob(data, oid):
        if start != reviewed_start:
            raise SuggestionError(stale)
        return
    try:
        reviewed = git(root, "cat-file", "blob", oid)
    except GitError as error:
        # Git does not store every unstaged or untracked blob.
        raise SuggestionError(stale) from error
    original = reviewed.replace(b"\r\n", b"\n").split(b"\n")
    if original[-1] == b"":
        original.pop()
    offset = start - reviewed_start
    # Keep edits before or after an intact prefix. A second occurrence in either
    # version can stand in for a removed block, even at its former line number.
    if (
        _blob_oid(reviewed, oid) != oid
        or reviewed_start < 0
        or offset < 0
        or original[: reviewed_start + len(wanted)] != content[offset : start + len(wanted)]
        or any(
            i != selected and line == wanted[0] and rows[i : i + len(wanted)] == wanted
            for rows, selected in ((original, reviewed_start), (content, start))
            for i, line in enumerate(rows)
        )
    ):
        raise SuggestionError(stale)


def _replace_lines(root, data, first, last, expected, replacement, snapshot_oid, reviewed_first):
    if b"\0" in data or "\0" in replacement:
        raise SuggestionError("Suggestions can only be applied to UTF-8 text.")
    try:
        data.decode("utf-8")
        wanted = expected.encode("utf-8").split(b"\n")
        replacement = replacement.replace("\r\n", "\n").encode("utf-8")
    except UnicodeError as error:
        raise SuggestionError("Suggestions can only be applied to UTF-8 text.") from error

    # Git numbers lines at LF bytes. Keep the original delimiters for the write.
    rows = re.findall(rb"[^\n]*\n|[^\n]+", data)
    content = [row.removesuffix(_line_end(row)) for row in rows]
    start = first - 1
    if first < 1 or last < first or last > len(rows) or content[start:last] != wanted:
        raise SuggestionError("The selected lines have changed. Refresh and review the suggestion again.")
    _verify_range(root, data, content, start, wanted, snapshot_oid, reviewed_first - 1)

    prefix = b"".join(rows[:start])
    suffix = b"".join(rows[last:])
    endings = [_line_end(row) for row in rows[start:last]]
    if not replacement:
        if not suffix and not endings[-1]:
            prefix = prefix.removesuffix(_line_end(prefix))
        return prefix + suffix

    preferred = endings[0] or _line_end(prefix) or b"\n"
    new_rows = replacement.split(b"\n")
    for i in range(len(new_rows) - 1):
        new_rows[i] += (endings[i] if i < len(endings) else preferred) or preferred
    new_rows[-1] += endings[-1]
    return prefix + b"".join(new_rows) + suffix


def _copy_posix_metadata(source, dest, info):
    dest_info = dest.stat()
    if (info.st_uid, info.st_gid) != (dest_info.st_uid, dest_info.st_gid):
        os.chown(dest, info.st_uid, info.st_gid)
    os.chmod(dest, stat.S_IMODE(info.st_mode))
    if hasattr(os, "listxattr"):
        original = set(os.listxattr(source, follow_symlinks=False))
        inherited = set(os.listxattr(dest))
        for name in inherited - original:
            os.removexattr(dest, name)
        for name in original:
            value = os.getxattr(source, name, follow_symlinks=False)
            if name not in inherited or value != os.getxattr(dest, name):
                os.setxattr(dest, name, value)


def _replace_windows(temp, target):
    # ReplaceFile merges the target's ACL and named streams. Retain the
    # original on the same volume in case Windows fails partway through.
    import ctypes
    from ctypes import wintypes

    replace = ctypes.WinDLL("kernel32", use_last_error=True).ReplaceFileW
    replace.argtypes = [wintypes.LPCWSTR] * 3 + [wintypes.DWORD, wintypes.LPVOID, wintypes.LPVOID]
    replace.restype = wintypes.BOOL
    backup = temp.with_name(temp.name + ".original")
    if not replace(str(target), str(temp), str(backup), 0, None, None):
        error = ctypes.WinError(ctypes.get_last_error())
        if backup.exists() and not target.exists():
            try:
                backup.rename(target)
            except OSError as restore_error:
                raise SuggestionError(
                    f"Could not restore the original file. Its backup is at {backup}."
                ) from restore_error
        raise error
    try:
        backup.unlink()
    except OSError as error:
        # The replacement succeeded. Its receipt must still be saved.
        logging.getLogger(__name__).warning("Could not remove the suggestion backup %s: %s", backup, error)


def apply_suggestion(repo, path, first, last, expected, replacement, *, snapshot_oid=None, reviewed_first=None):
    """Replace a verified range and return the raw working-file blob OID.

    first and last are inclusive working-file line numbers. snapshot_oid and
    reviewed_first identify the original selection, even after a comment moves.
    """
    temp = None
    try:
        target = _working_path(repo.root, path)
        path_info = target.lstat()
        original, info = _read(target)
        if not info.st_mode & 0o222:
            raise SuggestionError("The working file is read-only.")
        if info.st_nlink > 1:
            raise SuggestionError("This file has hard links. Edit it directly to preserve the linked files.")
        result = _replace_lines(
            repo.root,
            original,
            first,
            last,
            expected,
            replacement,
            snapshot_oid,
            first if reviewed_first is None else reviewed_first,
        )
        if original == result:
            raise SuggestionError("The file already contains this replacement.")
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".branchline-", delete=False) as output:
            temp = Path(output.name)
            output.write(result)
        if os.name != "nt":
            _copy_posix_metadata(target, temp, info)
        _working_path(repo.root, path)
        current, current_info = _read(target)
        if (
            original != current
            or _version(info) != _version(current_info)
            # Windows derives execute bits for .cmd/.bat from the path only.
            or not os.path.samestat(info, path_info)
            or _version(path_info) != _version(target.lstat())
        ):
            raise SuggestionError("The file changed during Apply. Refresh and review the suggestion again.")
        result_oid = _blob_oid(result, snapshot_oid)
        if os.name == "nt":
            _replace_windows(temp, target)
        else:
            os.replace(temp, target)
        temp = None
        return result_oid
    except OSError as error:
        raise SuggestionError(f"Could not update {path}: {error.strerror or error}.") from error
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
