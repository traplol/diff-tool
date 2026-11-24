use std::ffi::{OsStr, OsString};
use std::os::windows::process::CommandExt;
use std::path::{Component, Path, PathBuf, Prefix};
use std::process::{Command, Stdio};

use super::Result;

pub(super) struct WslCheckout {
    share: PathBuf,
    distribution: OsString,
    pub(super) directory: OsString,
}

impl WslCheckout {
    pub(super) fn from_path(path: &Path) -> Option<Self> {
        let path = std::path::absolute(path).ok()?;
        let mut components = path.components();
        let Component::Prefix(prefix) = components.next()? else {
            return None;
        };
        let (server, distribution) = match prefix.kind() {
            Prefix::UNC(server, share) | Prefix::VerbatimUNC(server, share) => (server, share),
            _ => return None,
        };
        if !["wsl.localhost", "wsl$"]
            .iter()
            .any(|host| server.eq_ignore_ascii_case(host))
        {
            return None;
        }

        let mut share = PathBuf::from(r"\\");
        share.as_mut_os_string().push(server);
        share.push(distribution);
        let mut directory = OsString::new();
        for component in components.filter(|c| *c != Component::RootDir) {
            directory.push("/");
            directory.push(component.as_os_str());
        }
        if directory.is_empty() {
            directory.push("/");
        }
        Some(Self {
            share,
            distribution: distribution.to_owned(),
            directory,
        })
    }

    pub(super) fn host_path(&self, path: &Path) -> Result<PathBuf> {
        let relative = path
            .to_str()
            .and_then(|path| path.strip_prefix('/'))
            .ok_or("Git did not return an absolute WSL path.")?;
        let mut host = self.share.clone();
        for part in relative.split('/').filter(|part| !part.is_empty()) {
            // A Linux filename containing a backslash cannot be represented on a UNC share.
            if part.contains(['\\', ':']) || matches!(part, "." | "..") {
                return Err(format!(
                    "Cannot access the WSL path {} from Windows.",
                    path.display()
                ));
            }
            host.push(part);
        }
        Ok(host)
    }

    fn launcher(&self) -> Result<Command> {
        let launcher = std::env::var_os("SystemRoot")
            .map(PathBuf::from)
            .filter(|root| root.is_absolute())
            .map(|root| root.join("System32").join("wsl.exe"))
            .filter(|path| path.is_file())
            .ok_or("Windows Subsystem for Linux is required to open this checkout.")?;
        let mut cmd = Command::new(launcher);
        cmd.arg("--distribution")
            .arg(&self.distribution)
            .creation_flags(0x08000000)
            .stdin(Stdio::null());
        Ok(cmd)
    }

    pub(super) fn link_target(&self, path: &OsStr) -> Result<Vec<u8>> {
        let output = self
            .launcher()?
            .arg("--cd")
            .arg(&self.directory)
            .args(["--exec", "/usr/bin/readlink", "-z", "--"])
            .arg(path)
            .output()
            .map_err(|e| format!("Could not start WSL to read the symbolic link. {e}"))?;
        if output.status.success() {
            if let Some(target) = output.stdout.strip_suffix(&[0]) {
                return Ok(target.to_vec());
            }
        }
        Err(format!(
            "Could not read the WSL symbolic link {}.",
            path.to_string_lossy()
        ))
    }
}

fn git_executable(directory: &Path) -> Result<PathBuf> {
    let dirs: Vec<_> = [std::env::current_dir().ok(), Some(directory.to_owned())]
        .into_iter()
        .flatten()
        .filter_map(|p| p.canonicalize().ok())
        .collect();
    let checkouts: Vec<_> = dirs
        .iter()
        .flat_map(|p| p.ancestors())
        .filter(|p| p.join(".git").is_file() || p.join(".git/HEAD").is_file())
        .collect();
    let installations = [
        "ProgramW6432",
        "ProgramFiles",
        "ProgramFiles(x86)",
        "LOCALAPPDATA",
    ]
    .into_iter()
    .filter_map(|key| {
        let mut dir = PathBuf::from(std::env::var_os(key)?);
        if key == "LOCALAPPDATA" {
            dir.push("Programs");
        }
        Some(dir.join("Git").join("cmd"))
    });
    let path = std::env::var_os("PATH").unwrap_or_default();
    installations
        .chain(std::env::split_paths(&path))
        .filter(|p| p.is_absolute())
        .filter_map(|p| p.join("git.exe").canonicalize().ok())
        .find(|p| {
            p.is_file()
                && !dirs.iter().any(|d| Some(d.as_path()) == p.parent())
                && !checkouts.iter().any(|d| p.starts_with(d))
        })
        .ok_or_else(|| "Install Git for Windows or add its installation directory to PATH.".into())
}

pub(super) fn command(root: &Path) -> Result<Command> {
    if let Some(wsl) = WslCheckout::from_path(root) {
        let mut cmd = wsl.launcher()?;
        cmd.args([
            "--exec",
            "/usr/bin/env",
            "LC_ALL=C",
            "GIT_NO_LAZY_FETCH=1",
            "GIT_TERMINAL_PROMPT=0",
            "GIT_OPTIONAL_LOCKS=0",
            "git",
            "--no-pager",
            "--literal-pathspecs",
            "-C",
        ])
        .arg(wsl.directory);
        return Ok(cmd);
    }
    let mut cmd = Command::new(git_executable(root)?);
    cmd.args(["--no-pager", "--literal-pathspecs", "-C"])
        .arg(root)
        .env("GIT_NO_LAZY_FETCH", "1")
        .env("GIT_TERMINAL_PROMPT", "0")
        .env("GIT_OPTIONAL_LOCKS", "0")
        .creation_flags(0x08000000)
        .stdin(Stdio::null());
    Ok(cmd)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn wsl_paths_round_trip_through_the_named_distribution() {
        for (input, host_path) in [
            (
                r"\\wsl.localhost\Ubuntu\home\alice\my repo\src",
                r"\\wsl.localhost\Ubuntu\home\alice\my repo",
            ),
            (
                r"\\?\UNC\WSL$\Debian\home\alice\my repo\src",
                r"\\WSL$\Debian\home\alice\my repo",
            ),
        ] {
            let checkout = WslCheckout::from_path(Path::new(input)).unwrap();
            assert_eq!(checkout.directory, "/home/alice/my repo/src");
            assert_eq!(
                checkout.host_path(Path::new("/home/alice/my repo")).unwrap(),
                Path::new(host_path),
            );
        }
        assert!(WslCheckout::from_path(Path::new(r"C:\work\repo")).is_none());
        assert!(WslCheckout::from_path(Path::new(r"\\server\share\repo")).is_none());
    }
}
