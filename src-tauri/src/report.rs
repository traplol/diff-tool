use super::{s, span, suggestion_source, Locations};
use crate::git::{ref_name, Repository, WORKTREE};
use serde_json::Value;
use std::fmt::Write;

fn label(text: &str) -> String {
    text.replace('\n', "\\n")
        .replace('\r', "\\r")
        .replace('\t', "\\t")
}
fn reference(text: &str) -> String {
    label(&ref_name(text))
}
fn range(first: usize, last: usize) -> String {
    if first == last {
        format!("L{first}")
    } else {
        format!("L{first}–{last}")
    }
}
fn location(n: &Value) -> String {
    let parts = ["old", "new"]
        .iter()
        .filter_map(|side| span(n, side).map(|(a, b)| format!("{side} {}", range(a, b))))
        .collect::<Vec<_>>();
    if parts.is_empty() {
        "Whole file".into()
    } else {
        parts.join(" · ")
    }
}
fn receipt(r: &Value) -> String {
    let lines = span(r, "new")
        .map(|(a, b)| range(a, b))
        .unwrap_or_else(|| "unknown lines".into());
    let branch = if s(r, "branch").is_empty() {
        String::new()
    } else {
        format!(" on {}", reference(s(r, "branch")))
    };
    format!(
        "{} · {lines}{branch} (before replacement)",
        label(s(r, "path"))
    )
}
fn fenced(text: &str, lang: &str) -> String {
    let mut longest = 0;
    let mut consecutive = 0;
    for c in text.chars() {
        if c == '`' {
            consecutive += 1;
            longest = longest.max(consecutive);
        } else {
            consecutive = 0;
        }
    }
    let fence = "`".repeat(3.max(longest + 1));
    format!("{fence}{lang}\n{text}\n{fence}")
}

pub fn markdown(
    repo: &Repository,
    stack: Option<&[String]>,
    notes: &[Value],
    locations: &Locations,
    open_only: bool,
) -> String {
    let mut out = String::new();
    let title = if open_only {
        "# Code review · Open comments only"
    } else {
        "# Code review"
    };
    let scope = match stack {
        None => "Scope: entire repository".into(),
        Some([]) => "Scope: working tree".into(),
        Some(stack) => format!(
            "Branch stack: {}",
            stack
                .iter()
                .map(|r| reference(r))
                .collect::<Vec<_>>()
                .join(" → ")
        ),
    };
    let open = notes.iter().filter(|n| n["resolved"] != true).count();
    let summary = if open_only {
        format!("{open} open")
    } else {
        format!("{open} open · {} resolved", notes.len() - open)
    };
    let instructions = if open == 0 {
        "No open comments need work in this scope."
    } else if open_only {
        "Address the open comments."
    } else {
        "Address the open comments. Use resolved comments as review history."
    };
    writeln!(
        out,
        "{title}\n\nRepository: {}\n{scope}\n\n**{summary}**\n\n{instructions}\n",
        label(&repo.root.file_name().unwrap_or_default().to_string_lossy())
    )
    .unwrap();
    if notes
        .iter()
        .any(|n| n["resolved"] != true && n["suggestion"].is_string())
    {
        writeln!(out,"Check open suggestions against the current code. An application receipt records a working-file edit. Use the current locations to see whether the change reached the index or a commit.\n").unwrap();
    }
    let mut index = 0;
    for resolved in [false, true] {
        if resolved && open_only {
            break;
        }
        let group = notes
            .iter()
            .filter(|n| (n["resolved"] == true) == resolved)
            .collect::<Vec<_>>();
        if group.is_empty() {
            continue;
        }
        let status = if resolved { "Resolved" } else { "Open" };
        writeln!(out, "## {status} comments\n").unwrap();
        for note in group {
            index += 1;
            let path = label(s(note, "path"));
            writeln!(out, "### {index}. {path}\n\n- Review status: {status}").unwrap();
            if note["right"] == WORKTREE {
                writeln!(
                    out,
                    "- Working tree: {} · {}\n- Checkout base: {}\n- Working tree snapshot: {}",
                    reference(s(note, "left")),
                    s(note, "group"),
                    s(note, "left_tip"),
                    s(note, "head")
                )
                .unwrap();
            } else {
                writeln!(
                    out,
                    "- Comparison: {} → {}\n- Base tip: {}\n- Diff base: {}\n- Head: {}",
                    reference(s(note, "left")),
                    reference(s(note, "right")),
                    s(note, "left_tip"),
                    s(note, "base"),
                    s(note, "head")
                )
                .unwrap();
            }
            if note["old_path"] != note["path"] {
                writeln!(out, "- Previous path: {}", label(s(note, "old_path"))).unwrap();
            }
            let tracked = note["right"] == WORKTREE || !note["applied_anchor"].is_null();
            let line_label = if tracked { "Original lines" } else { "Lines" };
            writeln!(out, "- {line_label}: {}\n", location(note)).unwrap();
            if tracked {
                match note["id"].as_i64().and_then(|id|locations.get(&id)){
                    None=>out.push_str("Current location unverified in the selected stack and checkout. Use the saved excerpt as historical context.\n\n"),
                    Some(matches) if matches.is_empty()=>out.push_str("The reviewed lines have no unambiguous match in the current working-tree or stack diffs. The excerpt below is historical.\n\n"),
                    Some(matches)=>{
                        for dest in matches{
                            let version=if dest["right"]==WORKTREE {format!("{} on {} (file blob {})",s(dest,"group"),reference(s(dest,"left")),s(dest,"blob"))}
                                else{format!("Committed in {} → {} (head {})",reference(s(dest,"left")),reference(s(dest,"right")),s(dest,"head"))};
                            let content=if dest["applied_text"]!=true{"reviewed code"}else if s(note,"suggestion").is_empty(){"applied deletion"}else{"replacement"};
                            writeln!(out,"- Current location of {content}: {version} · {} · {}",label(s(dest,"path")),location(dest)).unwrap();
                        }
                        out.push('\n');
                    }
                }
            }
            if let Some(code) = note["suggestion"].as_str() {
                let applied = note["applied_location"].is_object();
                writeln!(
                    out,
                    "- Suggestion status: {}\n",
                    if applied {
                        "applied to working file"
                    } else {
                        "proposed"
                    }
                )
                .unwrap();
                if applied {
                    writeln!(
                        out,
                        "- Applied at: {}\n",
                        receipt(&note["applied_location"])
                    )
                    .unwrap();
                }
                let replacement = if code.is_empty() {
                    "Delete the selected lines.".into()
                } else {
                    fenced(code, "suggestion")
                };
                writeln!(
                    out,
                    "**Original selected code**\n\n{}\n\n**Replacement**\n\n{replacement}\n",
                    fenced(&suggestion_source(note), "")
                )
                .unwrap();
                if let Some(earlier) = note.get("earlier_application") {
                    let code = s(earlier, "suggestion");
                    let history = if code.is_empty() {
                        "Deleted the selected lines.".into()
                    } else {
                        fenced(code, "")
                    };
                    writeln!(out,"**Earlier replacement applied to working file**\n\n- Applied at: {}\n\n{history}\n",receipt(&earlier["applied_location"])).unwrap();
                }
            } else if !s(note, "excerpt").is_empty() {
                if tracked {
                    out.push_str("**Original excerpt**\n\n");
                }
                writeln!(out, "{}\n", fenced(s(note, "excerpt"), "diff")).unwrap();
            }
            if !s(note, "body").is_empty() {
                writeln!(out, "**Reviewer comment**\n\n{}\n", s(note, "body")).unwrap();
            }
            if let Some(replies) = note["replies"].as_array() {
                for reply in replies {
                    writeln!(
                        out,
                        "**Reply from {}**\n\n{}\n",
                        label(s(reply, "author")),
                        s(reply, "body")
                    )
                    .unwrap();
                }
            }
        }
    }
    out
}
