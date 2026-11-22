//! Decode resident Git patch sections for line selection and display.

fn hunk_start(line: &str) -> Option<(usize, usize)> {
    let range = line.strip_prefix("@@ -")?.split_once(" @@")?.0;
    let (old, new) = range.split_once(" +")?;
    Some((
        old.split(',').next()?.parse().ok()?,
        new.split(',').next()?.parse().ok()?,
    ))
}

pub(super) fn visit(chunks: &[&[u8]], mut emit: impl FnMut(&str, &str, usize, usize, usize)) {
    let mut hunk = 0;
    for chunk in chunks {
        let mut at = None;
        for line in String::from_utf8_lossy(chunk).split('\n') {
            if let Some((old, new)) = hunk_start(line) {
                hunk += 1;
                at = Some((old, new));
                emit("@", line, old, new, hunk);
            } else if let Some((old, new)) = at.as_mut() {
                let Some(&kind) = line.as_bytes().first() else {
                    continue;
                };
                if matches!(kind, b'+' | b'-' | b' ') {
                    let text = line[1..].strip_suffix('\r').unwrap_or(&line[1..]);
                    emit(&line[..1], text, *old, *new, hunk);
                    *old += usize::from(kind != b'+');
                    *new += usize::from(kind != b'-');
                } else if kind == b'\\' {
                    emit("\\", line, *old, *new, hunk);
                }
            }
        }
    }
}

// Send each code line once. Hunk starts supply both line counters to the editor.
pub(super) fn encode(chunks: &[&[u8]]) -> (String, Vec<[usize; 2]>) {
    let mut rows = String::new();
    let mut starts = Vec::new();
    visit(chunks, |kind, text, old, new, _| {
        match kind {
            "@" => starts.push([old, new]),
            "\\" => {}
            _ => rows.push_str(kind),
        }
        rows.push_str(text);
        rows.push('\n');
    });
    (rows, starts)
}
