//! Read-only Git wire operations. Review storage and logical roots stay in the desktop.
use super::{Change, Comparison, Repository};
use base64::{engine::general_purpose::STANDARD, Engine as _};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashSet;

type Result<T> = std::result::Result<T, String>;
pub(crate) const PROTOCOL: u32 = 1;

pub(crate) fn encode_bytes(bytes: &[u8]) -> String {
    STANDARD.encode(bytes)
}

pub(crate) fn decode_bytes(encoded: &str) -> Result<Vec<u8>> {
    STANDARD
        .decode(encoded)
        .map_err(|error| format!("Invalid Git worker byte payload: {error}"))
}

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct OpenResult {
    pub repo: Repository,
    pub git_executable: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub(crate) struct ComparisonHeader {
    pub left: String,
    pub right: String,
    pub left_tip: String,
    pub base: String,
    pub head: String,
}

impl ComparisonHeader {
    pub fn from_comparison(comparison: &Comparison) -> Self {
        Self {
            left: comparison.left.clone(),
            right: comparison.right.clone(),
            left_tip: comparison.left_tip.clone(),
            base: comparison.base.clone(),
            head: comparison.head.clone(),
        }
    }

    fn into_comparison(self, files: Vec<Change>) -> Comparison {
        Comparison {
            left: self.left,
            right: self.right,
            left_tip: self.left_tip,
            base: self.base,
            head: self.head,
            files,
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct WireChange {
    #[serde(flatten)]
    pub change: Change,
    pub local_sections: Vec<String>,
}

impl WireChange {
    pub fn from_change(change: &Change) -> Self {
        Self::from(change.clone())
    }

    pub fn decode(mut self) -> Result<Change> {
        self.change.local_sections = self
            .local_sections
            .iter()
            .map(|section| decode_bytes(section))
            .collect::<Result<_>>()?;
        Ok(self.change)
    }
}

impl From<Change> for WireChange {
    fn from(mut change: Change) -> Self {
        let local_sections = std::mem::take(&mut change.local_sections)
            .into_iter()
            .map(|section| encode_bytes(&section))
            .collect();
        Self {
            change,
            local_sections,
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct WireComparison {
    #[serde(flatten)]
    pub header: ComparisonHeader,
    pub files: Vec<WireChange>,
}

impl From<Comparison> for WireComparison {
    fn from(comparison: Comparison) -> Self {
        let header = ComparisonHeader::from_comparison(&comparison);
        Self {
            header,
            files: comparison.files.into_iter().map(WireChange::from).collect(),
        }
    }
}

impl WireComparison {
    pub fn decode(self) -> Result<Comparison> {
        let files = self
            .files
            .into_iter()
            .map(WireChange::decode)
            .collect::<Result<_>>()?;
        Ok(self.header.into_comparison(files))
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(tag = "op", rename_all = "snake_case")]
pub(crate) enum Request {
    Hello,
    Open {
        path: String,
    },
    CheckoutState,
    DiscoverStack {
        view: Repository,
        base: String,
        branch: String,
    },
    Compare {
        view: Repository,
        left: String,
        right: String,
    },
    CompareTrees {
        left: String,
        right: String,
        tip: String,
        base: String,
        head: String,
    },
    WorkingTree {
        view: Repository,
        checkout: String,
        untracked_paths: Option<HashSet<String>>,
    },
    WorkingTreePaths {
        view: Repository,
        checkout: String,
        paths: HashSet<String>,
    },
    MergeBase {
        a: String,
        b: String,
    },
    Descends {
        origin: String,
        head: String,
    },
    Blob {
        object: String,
    },
    Patch {
        comparison: ComparisonHeader,
        file: WireChange,
    },
    DisplayPatch {
        comparison: ComparisonHeader,
        file: WireChange,
    },
    FileContents {
        file: WireChange,
    },
    RevisionFile {
        revision: String,
        path: String,
    },
    Commits {
        comparison: ComparisonHeader,
    },
    Details {
        sha: String,
    },
}

#[cfg(any(feature = "storage-worker", test))]
#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct Envelope {
    pub id: u64,
    #[serde(flatten)]
    pub request: Request,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(untagged)]
pub(crate) enum Outcome {
    Success { result: Value },
    Failure { error: String },
}

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct Response {
    pub id: u64,
    #[serde(flatten)]
    pub outcome: Outcome,
}

impl Response {
    pub fn into_result(self) -> Result<Value> {
        match self.outcome {
            Outcome::Success { result } => Ok(result),
            Outcome::Failure { error } => Err(error),
        }
    }
}

#[cfg(feature = "storage-worker")]
mod server {
    use super::*;
    use crate::git;
    use serde_json::json;
    use std::{
        io::{self, BufRead, Write},
        path::PathBuf,
    };

    #[derive(Default)]
    struct Server {
        repo: Option<Repository>,
    }

    impl Server {
        fn repo(&self) -> Result<&Repository> {
            self.repo
                .as_ref()
                .ok_or_else(|| "Open a repository first.".into())
        }

        fn git_executable(&self) -> Option<String> {
            #[cfg(windows)]
            return git::command(&self.repo.as_ref()?.root)
                .ok()
                .map(|command| git::path_name(std::path::Path::new(command.get_program())));
            #[cfg(not(windows))]
            None
        }

        fn view(&self, view: Repository) -> Result<Repository> {
            if !view.refs.contains_key(git::EMPTY) {
                return Err("Missing repository object-format metadata.".into());
            }
            let mut repo = self.repo()?.clone();
            // Keep execution rooted in the worker's discovered checkout, even
            // when the caller's logical root is a path on the other OS.
            repo.refs = view.refs;
            repo.initial = view.initial;
            repo.default_branch = view.default_branch;
            repo.checkout = view.checkout;
            Ok(repo)
        }

        fn execute(&mut self, request: Request) -> Result<Value> {
            match request {
                Request::Hello => Ok(json!({"protocol":PROTOCOL,"os":std::env::consts::OS,
                    "architecture":std::env::consts::ARCH,"pid":std::process::id()})),
                Request::Open { path } => {
                    self.repo = Some(git::open_repo(&PathBuf::from(git::path_arg(&path)?))?);
                    Ok(json!(OpenResult {
                        repo: self.repo()?.clone(),
                        git_executable: self.git_executable()
                    }))
                }
                Request::CheckoutState => Ok(json!(git::checkout_state(&self.repo()?.root))),
                Request::DiscoverStack { view, base, branch } => Ok(json!(git::discover_stack(
                    &self.view(view)?,
                    &base,
                    &branch
                )?)),
                Request::Compare { view, left, right } => Ok(json!(WireComparison::from(
                    git::compare(&self.view(view)?, &left, &right)?
                ))),
                Request::CompareTrees {
                    left,
                    right,
                    tip,
                    base,
                    head,
                } => Ok(json!(WireComparison::from(git::compare_trees(
                    self.repo()?,
                    &left,
                    &right,
                    &tip,
                    &base,
                    &head
                )?))),
                Request::WorkingTree {
                    view,
                    checkout,
                    untracked_paths,
                } => Ok(json!(WireComparison::from(git::working_tree(
                    &self.view(view)?,
                    &checkout,
                    untracked_paths.as_ref()
                )?))),
                Request::WorkingTreePaths {
                    view,
                    checkout,
                    paths,
                } => Ok(json!(WireComparison::from(git::working_tree_paths(
                    &self.view(view)?,
                    &checkout,
                    &paths
                )?))),
                Request::MergeBase { a, b } => Ok(json!(git::merge_base(self.repo()?, &a, &b)?)),
                Request::Descends { origin, head } => {
                    Ok(json!(git::descends(self.repo()?, &origin, &head)?))
                }
                Request::Blob { object } => Ok(json!(encode_bytes(&git::blob_bytes(
                    &self.repo()?.root,
                    &object
                )?))),
                Request::Patch { comparison, file } => Ok(json!(git::patch(
                    self.repo()?,
                    &comparison.into_comparison(Vec::new()),
                    &file.decode()?
                )?)),
                Request::DisplayPatch { comparison, file } => Ok(json!(git::display_patch(
                    self.repo()?,
                    &comparison.into_comparison(Vec::new()),
                    &file.decode()?
                )?)),
                Request::FileContents { file } => {
                    Ok(json!(git::file_contents(self.repo()?, &file.decode()?)?))
                }
                Request::RevisionFile { revision, path } => {
                    Ok(json!(git::revision_file(self.repo()?, &revision, &path)?))
                }
                Request::Commits { comparison } => Ok(json!(git::commits(
                    self.repo()?,
                    &comparison.into_comparison(Vec::new())
                )?)),
                Request::Details { sha } => Ok(json!(git::commit_details(self.repo()?, &sha)?)),
            }
        }
    }

    pub fn run_stdio() -> Result<()> {
        let mut server = Server::default();
        let mut output = io::BufWriter::new(io::stdout().lock());
        for line in io::stdin().lock().lines() {
            let line = line.map_err(|error| error.to_string())?;
            let call = serde_json::from_str::<Envelope>(&line);
            let id = call.as_ref().map_or_else(
                |_| {
                    serde_json::from_str::<Value>(&line)
                        .ok()
                        .and_then(|value| value["id"].as_u64())
                        .unwrap_or(0)
                },
                |call| call.id,
            );
            let outcome = match call
                .map_err(|error| format!("Invalid Git worker request: {error}"))
                .and_then(|call| server.execute(call.request))
            {
                Ok(result) => Outcome::Success { result },
                Err(error) => Outcome::Failure { error },
            };
            serde_json::to_writer(&mut output, &Response { id, outcome })
                .map_err(|error| error.to_string())?;
            output
                .write_all(b"\n")
                .and_then(|_| output.flush())
                .map_err(|error| error.to_string())?;
        }
        Ok(())
    }
}

#[cfg(feature = "storage-worker")]
pub(crate) use server::run_stdio;

#[cfg(test)]
mod tests {
    use super::*;

    fn change() -> Change {
        Change {
            status: "M".into(),
            old: "file".into(),
            path: "file".into(),
            added: Some(1),
            removed: Some(1),
            old_mode: "100644".into(),
            mode: "100644".into(),
            old_oid: "a".repeat(40),
            oid: "b".repeat(40),
            group: "Unstaged".into(),
            local_sections: vec![b"patch\n\xff\0".to_vec()],
        }
    }

    #[test]
    fn wire_sections_are_lossless_and_do_not_change_frontend_serialization() {
        let original = change();
        assert!(serde_json::to_value(&original)
            .unwrap()
            .get("local_sections")
            .is_none());
        let bytes = serde_json::to_vec(&WireChange::from_change(&original)).unwrap();
        let wire: WireChange = serde_json::from_slice(&bytes).unwrap();
        assert_eq!(
            wire.decode().unwrap().local_sections,
            original.local_sections
        );
    }

    #[test]
    fn invalid_sections_are_rejected_before_git_access() {
        let mut wire = WireChange::from(change());
        wire.local_sections[0] = "!not base64!".into();
        assert!(wire
            .decode()
            .unwrap_err()
            .contains("Invalid Git worker byte payload"));
    }

    #[test]
    fn protocol_rejects_mutating_and_unknown_operations() {
        assert!(serde_json::from_str::<Envelope>(r#"{"id":1,"op":"checkout"}"#).is_err());
        assert!(serde_json::from_str::<Envelope>(r#"{"id":1,"op":"run_shell"}"#).is_err());
        assert!(serde_json::from_str::<Envelope>(r#"{"id":1,"op":"future_unknown_op"}"#).is_err());
    }

    #[test]
    fn null_success_is_distinct_from_failure() {
        let response: Response = serde_json::from_str(r#"{"id":1,"result":null}"#).unwrap();
        assert!(response.into_result().unwrap().is_null());
        let response: Response = serde_json::from_str(r#"{"id":2,"error":"bad request"}"#).unwrap();
        assert_eq!(response.into_result().unwrap_err(), "bad request");
    }
}
