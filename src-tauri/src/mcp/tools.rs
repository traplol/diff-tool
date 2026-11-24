use crate::{
    config,
    git::{self, Comparison, Repository, WORKTREE},
    review::{self, Store},
    service, tracking,
};
use serde::Deserialize;
use serde_json::{json, Value};
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
};

struct Tool {
    name: &'static str,
    description: &'static str,
    properties: Value,
    required: &'static [&'static str],
    writes: bool,
}

fn definitions() -> Vec<Tool> {
    let id = json!({"type": "integer", "minimum": 1, "description": "Saved comment ID"});
    let pair = json!({"type": "array", "minItems": 2, "maxItems": 2, "items": {"type": "string"},
        "description": "Two refs from get_repository. Use :worktree: as the right ref for local changes."});
    vec![
        Tool {
            name: "list_repositories",
            description: "List configured checkout paths and their repoId values. Worktrees of the same Git repository are separate checkouts.",
            properties: json!({}),
            required: &[],
            writes: false,
        },
        Tool {
            name: "get_repository",
            description: "Read the checkout, available refs, configured review stack, and working-tree comparison.",
            properties: json!({}),
            required: &[],
            writes: false,
        },
        Tool {
            name: "discover_stack",
            description: "Discover stack layers and fork choices around a branch relative to a base.",
            properties: json!({"base": {"type": "string"}, "branch": {"type": "string"}}),
            required: &["base", "branch"],
            writes: false,
        },
        Tool {
            name: "list_changes",
            description: "List changed files for a branch pair or the working tree, including group and blob IDs.",
            properties: json!({"pair": pair}),
            required: &["pair"],
            writes: false,
        },
        Tool {
            name: "get_patch",
            description: "Read the diff for a changed path. Provide its group when a file appears in more than one group.",
            properties: json!({"pair": pair, "path": {"type": "string"}, "group": {"type": "string"}}),
            required: &["pair", "path"],
            writes: false,
        },
        Tool {
            name: "list_commits",
            description: "List commits for a branch comparison.",
            properties: json!({"pair": pair}),
            required: &["pair"],
            writes: false,
        },
        Tool {
            name: "list_comments",
            description: "List saved review threads by ID, including their original anchors, suggestions, replies and status. Pass nextAfterId as afterId to continue.",
            properties: json!({
                "status": {"type": "string", "enum": ["all", "open", "resolved"], "default": "all"},
                "afterId": {"type": "integer", "minimum": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50}
            }),
            required: &[],
            writes: false,
        },
        Tool {
            name: "get_comment",
            description: "Read one thread with its saved anchor and current matches in the stack or working tree.",
            properties: json!({"id": id}),
            required: &["id"],
            writes: false,
        },
        Tool {
            name: "reply_to_comment",
            description: "Append a reply as the given author. Optional resolved changes the thread status in the same transaction.",
            properties: json!({
                "id": id, "author": {"type": "string", "minLength": 1, "maxLength": 120},
                "body": {"type": "string", "minLength": 1, "maxLength": 32768},
                "resolved": {"type": "boolean"}
            }),
            required: &["id", "author", "body"],
            writes: true,
        },
        Tool {
            name: "set_comment_resolved",
            description: "Resolve a review thread, or reopen it with resolved=false.",
            properties: json!({"id": id, "resolved": {"type": "boolean"}}),
            required: &["id", "resolved"],
            writes: true,
        },
        Tool {
            name: "export_review",
            description: "Export the repository's saved review threads and their replies as Markdown.",
            properties: json!({"openOnly": {"type": "boolean", "default": false}}),
            required: &[],
            writes: false,
        },
    ]
}

pub(super) fn list(require_repo_id: bool) -> Vec<Value> {
    definitions()
        .into_iter()
        .map(|mut tool| {
            let mut required = tool.required.to_vec();
            if tool.name != "list_repositories" {
                tool.properties["repoId"] = json!({
                    "type": "string",
                    "description": "Exact checkout identifier returned by list_repositories."
                });
                if require_repo_id {
                    required.push("repoId");
                }
            }
            json!({
                "name": tool.name,
                "description": tool.description,
                "inputSchema": {
                    "type": "object", "properties": tool.properties, "required": required,
                    "additionalProperties": false
                },
                "annotations": {
                    "readOnlyHint": !tool.writes, "destructiveHint": false,
                    "idempotentHint": tool.name != "reply_to_comment", "openWorldHint": false
                }
            })
        })
        .collect()
}

pub(super) fn contains(name: &str) -> bool {
    definitions().iter().any(|tool| tool.name == name)
}

#[derive(Deserialize)]
#[serde(
    tag = "tool",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
enum Call {
    GetRepository {},
    DiscoverStack {
        base: String,
        branch: String,
    },
    ListChanges {
        pair: [String; 2],
    },
    GetPatch {
        pair: [String; 2],
        path: String,
        group: Option<String>,
    },
    ListCommits {
        pair: [String; 2],
    },
    ListComments {
        status: Option<CommentStatus>,
        after_id: Option<u64>,
        limit: Option<usize>,
    },
    GetComment {
        id: i64,
    },
    ReplyToComment {
        id: i64,
        author: String,
        body: String,
        resolved: Option<bool>,
    },
    SetCommentResolved {
        id: i64,
        resolved: bool,
    },
    ExportReview {
        open_only: Option<bool>,
    },
}

#[derive(Deserialize)]
#[serde(rename_all = "lowercase")]
enum CommentStatus {
    All,
    Open,
    Resolved,
}

fn stack(repo: &Repository, store: &Store) -> Result<Vec<String>, String> {
    let settings = config::read(&config::path()?)?.unwrap_or_default();
    let saved = if let Some(saved) = settings.repositories.get(&git::path_name(&repo.root)) {
        saved.clone()
    } else if let Some(refs) = store.saved_stack(repo)? {
        let mut saved = config::RepoSettings::default();
        saved.base_branch = refs[0].clone();
        saved.layers = refs[1..].to_vec();
        saved
    } else {
        config::RepoSettings::default()
    };
    service::open_stack(repo, &saved)
}

fn comparison(repo: &Repository, pair: [String; 2]) -> Result<Comparison, String> {
    git::compare(repo, &pair[0], &pair[1])
}

fn comment(repo: &Repository, store: &Store, id: i64) -> Result<Value, String> {
    store
        .note(repo, id)?
        .ok_or_else(|| "Comment not found.".into())
}

pub(super) fn call(
    repositories: &BTreeMap<String, PathBuf>,
    name: &str,
    mut args: Value,
) -> Result<Value, String> {
    let fields = args.as_object_mut().ok_or("Expected named arguments.")?;
    if name == "list_repositories" {
        if !fields.is_empty() {
            return Err("list_repositories takes no arguments.".into());
        }
        let entries: Vec<_> = repositories
            .iter()
            .map(|(id, path)| json!({"repoId": id, "path": git::path_name(path)}))
            .collect();
        return Ok(json!({"repositories": entries}));
    }
    let requested = fields.remove("repoId");
    let (id, root) = match requested {
        Some(value) => {
            let id = value.as_str().ok_or("repoId must be a string.")?;
            repositories
                .get_key_value(id)
                .ok_or("Unknown repoId. Call list_repositories.")?
        }
        None if repositories.len() == 1 => repositories.first_key_value().unwrap(),
        None => return Err("repoId is required. Call list_repositories.".into()),
    };
    let mut result = call_repository(root, name, args)?;
    result["repoId"] = json!(id);
    Ok(result)
}

fn call_repository(root: &Path, name: &str, mut args: Value) -> Result<Value, String> {
    let fields = args.as_object_mut().ok_or("Expected named arguments.")?;
    if fields.insert("tool".into(), json!(name)).is_some() {
        return Err("Unexpected tool argument.".into());
    }
    let call: Call = serde_json::from_value(args).map_err(|e| e.to_string())?;
    let repo = git::open_repo(root)?;
    if repo.root != root {
        return Err("The configured checkout is no longer available.".into());
    }
    match call {
        Call::DiscoverStack { base, branch } => {
            let (refs, alternatives) = git::discover_stack(&repo, &base, &branch)?;
            return Ok(json!({"stack": refs, "alternatives": alternatives}));
        }
        Call::ListChanges { pair } => return Ok(json!({"comparison": comparison(&repo, pair)?})),
        Call::GetPatch { pair, path, group } => {
            let c = comparison(&repo, pair)?;
            let mut files = c
                .files
                .iter()
                .filter(|f| f.path == path && group.as_ref().is_none_or(|group| f.group == *group));
            let file = files.next().ok_or("Changed file not found.")?;
            if files.next().is_some() {
                return Err("Specify a group to identify this changed file.".into());
            }
            return Ok(json!({
                "file": file, "base": c.base, "head": c.head, "lines": git::patch(&repo, &c, file)?
            }));
        }
        Call::ListCommits { pair } => {
            return Ok(json!({"commits": git::commits(&repo, &comparison(&repo, pair)?)?}));
        }
        _ => {}
    }

    let mut store = Store::open()?;
    match call {
        Call::GetRepository {} => Ok(json!({
            "repository": repo,
            "stack": stack(&repo, &store)?,
            "workingTreePair": [repo.checkout, WORKTREE]
        })),
        Call::ListComments {
            status,
            after_id,
            limit,
        } => {
            let limit = limit.unwrap_or(50);
            if !(1..=100).contains(&limit) {
                return Err("limit must be between 1 and 100.".into());
            }
            let after = i64::try_from(after_id.unwrap_or(0))
                .map_err(|_| "afterId exceeds the supported comment ID range.")?;
            let resolved = match status {
                Some(CommentStatus::Open) => Some(false),
                Some(CommentStatus::Resolved) => Some(true),
                _ => None,
            };
            let mut notes = store.notes_after(&repo, after, resolved, (limit + 1) as i64)?;
            let next = if notes.len() > limit {
                notes.pop();
                notes.last().map(|note| &note["id"])
            } else {
                None
            };
            Ok(json!({"comments": notes, "nextAfterId": next}))
        }
        Call::GetComment { id } => {
            let note = comment(&repo, &store, id)?;
            let mut locations = tracking::locate_notes(
                &repo,
                &stack(&repo, &store)?,
                None,
                std::slice::from_ref(&note),
            );
            let left = review::s(&note, "left");
            let right = review::s(&note, "right");
            let matches = locations.entry(id).or_default();
            if right != WORKTREE
                && !matches
                    .iter()
                    .any(|m| m["left"] == left && m["right"] == right)
            {
                // The tracking pass skips branch notes whose original tips still match.
                if let Ok(c) = git::compare(&repo, left, right) {
                    if let Some(file) = c
                        .files
                        .iter()
                        .find(|f| review::note_matches_file(&c, f, &note))
                    {
                        matches.push(tracking::location_for(&c, file, &note));
                    }
                }
            }
            Ok(json!({"comment": note, "locations": matches}))
        }
        Call::ReplyToComment {
            id,
            author,
            body,
            resolved,
        } => {
            store.reply(&repo, id, &author, &body, resolved)?;
            Ok(json!({"comment": comment(&repo, &store, id)?}))
        }
        Call::SetCommentResolved { id, resolved } => {
            if !store.set_resolved(&repo, id, resolved)? {
                return Err("Comment not found.".into());
            }
            Ok(json!({"comment": comment(&repo, &store, id)?}))
        }
        Call::ExportReview { open_only } => {
            let notes = store.notes(&repo)?;
            let locations = tracking::locate_notes(&repo, &stack(&repo, &store)?, None, &notes);
            Ok(json!({
                "markdown": review::markdown(&repo, None, &notes, &locations, open_only.unwrap_or(false))
            }))
        }
        _ => unreachable!(),
    }
}
