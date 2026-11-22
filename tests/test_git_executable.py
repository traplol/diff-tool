import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from branchline import git


class GitExecutableTest(unittest.TestCase):
    def test_windows_git_uses_only_an_absolute_path_outside_the_checkout(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            checkout = root / "review"
            nested = checkout / "src"
            tools = checkout / "tools"
            cwd = root / "launcher"
            installed = root / "Git" / "cmd"
            for directory in (checkout / ".git", nested, tools, cwd, installed):
                directory.mkdir(parents=True)
            (checkout / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
            for directory in (tools, installed, cwd):
                (directory / "git.exe").touch()
            entries = ["", ".", "tools", str(cwd), str(tools)]
            # These empty files exercise lookup only. No process is launched.
            with (
                patch.object(Path, "cwd", return_value=cwd),
                patch("sys.platform", "win32"),
                patch.object(git.subprocess, "run") as run,
            ):
                run.return_value.returncode = 0
                with patch.dict(os.environ, PATH=os.pathsep.join(entries + [str(installed)])):
                    git.git(nested, "--version")
                self.assertEqual(Path(run.call_args.args[0][0]), installed / "git.exe")
                run.reset_mock()
                with patch.dict(os.environ, PATH=os.pathsep.join(entries)), self.assertRaisesRegex(
                    git.GitError, "Install Git"
                ):
                    git.git(nested, "--version")
                run.assert_not_called()
