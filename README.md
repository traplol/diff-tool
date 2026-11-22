# Branchline

Branchline is a native desktop app for reviewing Git changes. Open a checkout to review a branch stack or your local edits, comment on changed lines, and export the review as Markdown.

## Run Branchline

Branchline runs as a local desktop application. The native executable contains the interface and uses Git from your PATH. Start it inside a repository or pass the directory you want to review.

**Linux and WSLg.** On a Debian-based distribution, install the release package and open a checkout:

```sh
sudo apt install ./Branchline_0.2.0_amd64.deb
cd /path/to/checkout
branchline .
```

You can also run the Linux executable directly with GTK 3, WebKitGTK 4.1, and Git installed. Under WSL2, use the Linux build and the Git executable inside the distribution. Desktop windows use WSLg.

**Windows.** Extract the Windows x64 portable bundle to a folder such as `C:\Tools\Branchline`. Keep `branchline.exe` and `WebView2Loader.dll` together. Install the Microsoft Edge WebView2 Runtime and Git for Windows if needed. From PowerShell:

```powershell
Set-Location C:\code\my-repository
C:\Tools\Branchline\branchline.exe .
```

Add the executable’s directory to PATH to use `branchline .` from any checkout. You can also open Branchline from your desktop and choose a directory.

### Build from source

Install stable Rust, Node.js 22 with npm, Git, and the [Tauri build prerequisites](https://v2.tauri.app/start/prerequisites/) for your operating system. From Linux, WSL, or Git Bash on Windows, run the release build with one command.

```sh
./build.sh
```

The executable is in `src-tauri/target/release/` and the platform installer is under `src-tauri/target/release/bundle/`. Use `./build.sh --no-bundle` to build just the executable. From PowerShell, run `npm ci` followed by `npm run tauri -- build`. For a development window with live UI updates, run `npm run tauri -- dev` and open a repository from the sidebar.

The Rust build uses the same SQLite database as the previous Python release. Existing comments, suggestions, resolution status, viewed files, and saved stacks load when you open the same checkout. The Python/Tk sources and their regression tests remain available for compatibility checks.

## Review a stack

1. Open a repository or any directory inside it. Branchline reads local branches and remote-tracking refs already present in the checkout.
2. On first open, Branchline follows branch tips in Git history to suggest a stack around the checked-out branch. To start from another ref, open **Edit stack**, select the ref, and choose **Find stack**. At a fork, choose the path you want. You can also use **Add** and **Replace** to arrange the stack manually. The first ref is the base. Choose **Review stack** to save the order.
3. Use **Full stack** to compare the base with the final branch. Select a layer to compare adjacent refs. Each comparison starts at the Git merge base, as in a pull request.
4. Press **Ctrl+F** and type part of a file path. The first match opens automatically. Press **Enter** to focus its diff. Choose **Unified** or **Split**, then drag across lines or Shift-click to extend a selection. The viewer remembers your place when you switch layouts or revisit the file. Press **C** to comment and **Ctrl+Enter** to save. To comment on the whole file, press **Escape** to clear the selection first, or right-click and choose **Comment on file**. **Viewed** tracks your progress for this snapshot.
5. Comments appear below their lines, or above the diff for whole-file comments. **Resolve** folds a comment. Expand it to read it again or choose **Reopen** to return it to active review. Open comments on the same line stay visible.
6. The **Comments** panel starts on **Open**. Select **Resolved** to revisit completed items or **All** to see both. Choose **Entire repository** to include other comparisons. **Show in diff** expands the selected comment at its current lines. **Open comment** shows the saved excerpt.
7. Choose **Export Markdown** to open an editable preview. Select **Open comments only** to send the agent outstanding feedback. The preview starts with the full review, including resolved history. From **Comments**, it uses the selected scope. From other panels, it uses the current stack or working-tree review. Each version keeps its own edits while the preview is open. **Copy Markdown** and **Save as…** use the text you see.

In **Commits**, choose **Fit columns to content** to size columns to their values. Right-click a cell to copy its value, the row, or the full SHA. **Commit details…** shows the message, author, committer, and change statistics. Drag the right edge of the green sidebar to resize it. Branchline remembers the width.

**Refresh** rereads branch tips after a fetch, commit, or rebase. For an initial commit, use **Empty tree** as the base.

## Review before committing

Choose **Working tree** from the comparison menu beside the branch names. It follows the checked-out branch, including when you're on a middle layer of a stack. A repository with no commits opens directly in this view.

- **Staged** compares the last commit with the index.
- **Unstaged** compares the index with your edits to tracked files.
- **Untracked** shows new files outside the index. Git's ignore rules apply.

A partially staged file appears in both groups. Select either entry to comment on the version you see. Press **F5** after editing, staging, or committing. When the reviewed lines move into the index or a commit, the same comment follows them into the matching stack diffs. **Comments → Show in diff** jumps to a verified match. If the lines disappear or multiple locations fit equally well, **Open comment** still shows the original excerpt.

The **Comments** panel and Markdown export include local notes from branches in the selected stack alongside branch-review notes. If you review a working tree on a branch outside that stack, its default scope is just that checkout branch. Reviewing changes does not stage files or create commits.

## Suggest a code change

Select lines on the new side of a diff and choose **Suggest change**, or press **S**. Edit the prefilled replacement and save the suggestion. An empty replacement proposes deleting the selected lines. The inline card shows the original code and the proposed change.

On the checked-out branch, choose **Apply to working file** to make the edit. Branchline verifies the selection against the reviewed file. If it cannot identify the original lines after another edit, open **Working tree**, refresh, and create a suggestion on the current lines. Edit hard-linked files directly to preserve their links. Staging and committing are separate Git operations.

**Export Markdown** checks current working-tree and stack locations when you open the preview, even if you have not pressed **F5**. The report keeps the original range and excerpt, identifies verified staged or committed locations, and records whether a suggestion was proposed or applied. An application receipt records the working-file edit. A committed location includes the commit ID of the reviewed head.

Applying a suggestion leaves its review status open until you select **Resolve**. Reopening an applied suggestion keeps its application receipt. A comment keeps its status when its lines move into the index or a stack commit.

Branchline saves comments, the last stack, and viewed files in SQLite under `$XDG_DATA_HOME/branchline` (default `~/.local/share/branchline`) or `%LOCALAPPDATA%\Branchline` on Windows. Comments are local to a checkout and a branch pair. The current stack includes the full-stack pair and all adjacent pairs, including notes saved against earlier tips.

## Keyboard shortcuts

| Shortcut | Action |
| --- | --- |
| Ctrl+O | Open a repository |
| Ctrl+B | Edit the stack |
| Ctrl+F | Filter changed files |
| Enter / Escape in the file filter | Open the match / clear the filter |
| Alt+Down / Alt+Up | Next / previous visible file |
| Up / Down in the diff | Select a line |
| Shift+Up / Shift+Down | Extend the selection |
| Escape in the diff | Clear the selection for a whole-file comment |
| C or Enter in the diff | Comment on the selection |
| S in the diff | Suggest replacement code for the selected new-side lines |
| Ctrl+C in the diff | Copy selected code |
| Ctrl+Enter in a comment | Save |
| Ctrl+E | Export Markdown |
| F5 | Refresh branch tips and the active diff |

## Run the tests

```sh
npm ci
npm run build
npm test
cargo test --locked --manifest-path src-tauri/Cargo.toml
```

The Rust tests create disposable repositories and review databases. They cover branch ancestry, working-tree snapshots, legacy SQLite records, comment tracking, suggestion application, and export. The JavaScript tests cover the diff editor’s selections and review scope.

On Linux, run the packaged desktop workflow using WebKitWebDriver and a virtual display:

```sh
npm run tauri -- build --no-bundle
xvfb-run -a -s '-screen 0 3840x2160x24' dbus-run-session -- python3 tools/smoke_current.py --binary src-tauri/target/release/branchline
```

The smoke test opens a temporary branch stack, checks which diff panes receive pointer and keyboard input, comments through the UI, applies a suggestion, stages and commits the edit with Git, and verifies its location in the Markdown preview. It uses an isolated review database. The previous Python regression suite runs with `python3 -m unittest discover -s tests` on a desktop display.

### Compare large-diff performance

Run the CPU benchmark from the project root to compare how the Rust port and Python prepare a 4,000-line addition and a 40,000-line mixed diff. It times patch processing and the first construction of unified and split rows from data already in memory. It needs Git, `rustc`, Node with npm, and Python with Tk for the shared fixture generator. It runs without a display or GPU.

```sh
npm ci
python3 tools/benchmarks/cpu_layout.py
```

The Rust port uses Rust to prepare the compact patch and JavaScript to decode it and build rows. The headless runner uses Node for the JavaScript stages. Once both layouts exist, the desktop app keeps them for the open file. WebKitGTK and GTK handle drawing on Linux and WSLg. [CPU timings and measurement details](tools/benchmarks/large-diffs.md)

To measure the whole desktop interaction on Linux, build the release and run the click-to-visible probe on a private X11 display. This includes Git, widget construction and presentation. It needs Xvfb, xauth, D-Bus, WebKitWebDriver, Python with Tk, Git, GNU patch and the X11 test libraries. Use a fresh output directory.

```sh
xvfb-run -a -s '-screen 0 1920x1080x24 -dpi 96' dbus-run-session -- \
  python3 tools/benchmarks/current.py xvfb build/benchmarks/my-run/xvfb \
  --binary src-tauri/target/release/branchline
```

The desktop probe writes `samples.jsonl` and `summary.json`. The archived Radeon and Xvfb campaign records timings for earlier Linux builds with explicit X11 rendering settings. [Historical campaign](tools/autoresearch/rust-layout/state.md)
