# Branchline

Branchline is a native desktop app for reviewing Git changes. Open a checkout to review a branch stack or your local edits, comment on changed lines, and export the review as Markdown.

## Run Branchline

Branchline runs as a local desktop application. It reads repositories and computes common review diffs in-process with libgit2. It uses the Git executable for repository formats and operations that require compatibility handling. Start it inside a repository or pass the directory you want to review.

**Linux and WSLg.** On a Debian-based distribution, install the release package and open a checkout:

```sh
sudo apt install ./Branchline_0.2.0_amd64.deb
cd /path/to/checkout
branchline .
```

You can also run the Linux executable directly with GTK 3, WebKitGTK 4.1, and Git installed. Under WSL2, use the Linux build and the Git executable inside the distribution. Desktop windows use WSLg.

**Windows.** Put the portable `branchline.exe` in a folder such as `C:\Tools\Branchline`. Install the Microsoft Edge WebView2 Runtime and Git for Windows if needed. From PowerShell:

```powershell
Set-Location C:\code\my-repository
C:\Tools\Branchline\branchline.exe .
```

Add the executable’s directory to PATH to use `branchline .` from any checkout. You can also open Branchline from your desktop and choose a directory.

The Windows app can open Windows paths and WSL paths such as `\\wsl.localhost\Ubuntu\home\you\project` or `\\wsl$\Ubuntu\home\you\project`. When Windows cannot verify ownership of a WSL checkout, Branchline checks it with Linux Git and keeps that checkout's validation in a temporary configuration for the life of the process. For compatibility operations, Branchline uses Git for Windows for Windows paths and Linux Git inside the named distribution for WSL paths.

### Build from source

Install stable Rust, Node.js 22 with npm, Git, and the [Tauri build prerequisites](https://v2.tauri.app/start/prerequisites/) for your operating system. From Linux, WSL, or Git Bash on Windows, run the release build with one command.

```sh
./build.sh
```

The executable is in `src-tauri/target/release/` and the platform installer is under `src-tauri/target/release/bundle/`. Use `./build.sh --no-bundle` to build just the executable. From PowerShell, run `npm ci` followed by `npm run tauri -- build`. For a development window with live UI updates, run `npm run tauri -- dev` and open a repository from the sidebar.

To build a single portable Windows x64 executable, run:

```sh
./build.sh --windows
```

The output is `src-tauri/target/x86_64-pc-windows-msvc/release/branchline.exe`. Install the Rust target with `rustup target add x86_64-pc-windows-msvc`. Cross-compiling from Linux or WSL also requires Clang, LLVM (including `llvm-rc`), LLD, and `cargo-xwin` (`cargo install --locked cargo-xwin`). On Git Bash, use the native MSVC toolchain. Windows still needs the WebView2 Runtime and Git to run Branchline.

The Rust build uses the same SQLite database as the previous Python release. Existing comments, suggestions, resolution status, viewed files, and saved stacks load when you open the same checkout. The Python/Tk sources and their regression tests remain available for compatibility checks.

## Agent review over MCP

Open the checkout in Branchline and leave comments on the agent's changes. Start the MCP server against that same checkout, then add its Streamable HTTP URL to your agent's MCP configuration.

```sh
branchline --mcp /path/to/checkout --port 8765
```

The endpoint is `http://127.0.0.1:8765/mcp`. On Windows, run `branchline.exe --mcp C:\code\my-repository --port 8765`. Run the desktop and MCP server as the same user and on the same platform so they share the review database.

When you open a checkout in the desktop app, Branchline checks the configured port. It reuses an existing Branchline MCP server or starts one in the background. The server stays running when you close the desktop windows. Every checkout you open is added to the running server and appears in `list_repositories` immediately. This works with native Windows paths, WSL UNC paths in the Windows app, and Linux paths (including `/mnt/c/...`) in the WSL app. Automatically added checkouts stay available until the server stops. Set `"mcp_auto_start": false` in Branchline's `config.json` to start the server manually.

One endpoint can serve multiple checkouts and agents. Pass checkout paths as separate arguments, or configure names in Branchline's `config.json` and start with `branchline --mcp`.

```json
{
  "mcp_port": 8765,
  "mcp_repositories": {
    "api": "/path/to/api",
    "web": "/path/to/web"
  }
}
```

Command-line checkout paths override the configured list and use their absolute paths as IDs. With neither, the server serves the current checkout. Agents can call `list_repositories` to see each ID and its checkout path. With multiple checkouts, every repository tool requires the exact `repoId`, including calls to read, reply to, or resolve a comment. Worktrees have their own checkout entries and review state. Desktop window focus has no effect on which checkout an agent targets. Restart the MCP server to reload the startup list after editing `mcp_repositories`.

Pass `--port`, set `BRANCHLINE_MCP_PORT`, or add `"mcp_port": 8765` to Branchline's `config.json`, in that order of precedence. The default is `8765`. The config file is under `$XDG_CONFIG_HOME/branchline` or `~/.config/branchline` on Linux, and `%APPDATA%\Branchline` on Windows. The server runs offline and listens only on IPv4 loopback. By default, local clients can connect without credentials. To require a token, set `BRANCHLINE_MCP_TOKEN` before starting Branchline and configure the client to send `Authorization: Bearer <token>`.

1. The agent calls `list_repositories` to choose the checkout, then calls `list_comments` with `{"status":"open","repoId":"api"}`, using the ID returned for that checkout. When only one checkout is configured, `repoId` is optional. If `nextAfterId` is present and non-null, pass it back as `afterId` to read the next page.
2. The agent uses `get_comment` with the comment ID to read the thread, saved excerpt, and any current match. It can use `get_repository`, `list_changes`, and `get_patch` to inspect the checkout before making edits with its coding tools.
3. The agent calls `reply_to_comment` with `id`, `author`, and `body` to record what changed and how it was verified. Add `"resolved":true` to resolve in the same operation. Omit it to keep the thread's current status. Use `set_comment_resolved` to resolve or reopen separately.
4. Branchline updates replies and status changes automatically. Resolved threads are under **Comments → Resolved** or **All**. Replies also appear in Markdown exports.

## Review a stack

1. Open a repository or any directory inside it. Branchline reads local branches and remote-tracking refs already present in the checkout.
2. On first open, Branchline follows branch tips in Git history to suggest a stack around the checked-out branch. To start from another ref, open **Edit stack**, select the ref, and choose **Find stack**. At a fork, choose the path you want. You can also use **Add** and **Replace** to arrange the stack manually. The first ref is the base. Choose **Review stack** to save the order.
3. Use **Full stack** to compare the base with the final branch. Select a layer to compare adjacent refs. Each comparison starts at the Git merge base, as in a pull request.
4. Use **Ctrl+P** to search by path, or type in **Filter files** to narrow the displayed comparison. In **Unified** or **Split**, use the down or up arrow in a gap to reveal 20 lines from its start or end. Click the hidden-line count to open the rest of the gap. **Full file** opens every gap, and **Changes only** restores the patch. Drag or Shift-click to select patch lines, press **C** to comment, then **Ctrl+Enter** to save. Closing a draft keeps it on this device so you can reopen it on the same lines. Use **Discard draft** to remove it. Press **Escape** in the diff to clear the selection before commenting on the whole file. **Viewed** tracks your progress for this snapshot.
5. Comments appear below their lines, or above the diff for whole-file comments. **Resolve** folds a comment. Expand it to read it again or choose **Reopen** to return it to active review. Open comments on the same line stay visible.
6. The **Comments** panel starts on **Open**. Select **Resolved** to revisit completed items or **All** to see both. Choose **Entire repository** to include other comparisons. **Jump to comment** refreshes the review and opens the verified line or the current file if those lines changed. **Open comment** shows the saved excerpt.
7. Choose **Export Markdown** to open an editable preview. Select **Open comments only** to send the agent outstanding feedback. The preview starts with the full review, including resolved history. From **Comments**, it uses the selected scope. From other panels, it uses the current stack or working-tree review. Full and open-only versions keep independent local drafts for the selected review scope. Use **Reset this version** to regenerate the active version from the review. **Copy Markdown** and **Save as…** use the text you see.

Use the tabs beneath the branch names to switch between **Changes**, **Commits**, and **Comments**. In **Commits**, choose **Fit columns to content** to size columns to their values. Right-click a cell to copy its value, the row, or the full SHA. With the row focused, press **Shift+F10** or the **Menu** key to open the same commands. **Commit details…** shows the message, author, committer, and change statistics. Drag the project sidebar’s right edge to resize it, or use the sidebar button beside **Branchline** to hide it. Branchline remembers the width.

**Refresh** rereads branch tips after a fetch, commit, or rebase. For an initial commit, use **Empty tree** as the base.

### Search a review

Press **Ctrl+F**, **Ctrl+Shift+F**, or **Ctrl+P** to open the search palette. File paths appear first. Search defaults to **Current review**. Choose **Entire branch** to include unchanged tracked files.

| Scope | Search contents |
| --- | --- |
| Current review | Changed paths and patches, comments, commits, and branches in the current stack. Local changes are included when the checked-out branch belongs to the stack. In an off-stack Working tree, only that checkout's changes and comments are searched. |
| This patch | The selected file’s patch, including additions, deletions, and the context Git included. |
| Full file | The selected file, including hidden context and removed lines. A match in hidden context expands that part of the diff. |
| Whole diff | Patches for every changed file in the active comparison. In Working tree this includes staged, unstaged, and untracked files. |
| Entire branch | Tracked paths and text at the selected branch tip, including unchanged files. In Working tree this uses the checked-out commit. Text opens at its matching line, while binary files and submodules open revision details. |
| Stack changes | Each adjacent pair in the stack, including intermediate edits. Local changes are included when the checked-out branch belongs to the stack or Working tree is active. |

Search is literal and case-insensitive. Use **Up** and **Down** to select a result, then press **Enter** or click it to open its location. **Escape** closes the palette and restores focus. If results are capped, narrow the query to see more specific matches.

Search uses the current review snapshot. Press **Refresh** to pick up new staged, unstaged, or untracked changes.

## Review before committing

Choose **Working tree** from the comparison menu beside the branch names. It follows the checked-out branch, including when you're on a middle layer of a stack. A repository with no commits opens directly in this view.

- **Staged** compares the last commit with the index.
- **Unstaged** compares the index with your edits to tracked files.
- **Untracked** shows new files outside the index. Git's ignore rules apply.

A partially staged file appears in both groups. Select either entry to comment on the version you see. Press **F5** after editing, staging, or committing. When the reviewed lines move into the index or a commit, the same comment follows them into the matching stack diffs. **Comments → Jump to comment** opens a verified match when available. If the lines disappear or multiple locations fit equally well, it opens the current file when available and keeps the original comment accessible.

The **Comments** panel and Markdown export include local notes from branches in the selected stack alongside branch-review notes. If you review a working tree on a branch outside that stack, its default scope is just that checkout branch. Reviewing changes does not stage files or create commits.

## Suggest a code change

Select lines on the new side of a diff and choose **Suggest change**, or press **S**. Edit the prefilled replacement and save the suggestion. An empty replacement proposes deleting the selected lines. The inline card shows the original code and the proposed change.

On the checked-out branch, choose **Apply to working file** to make the edit. Branchline verifies the selection against the reviewed file. If it cannot identify the original lines after another edit, open **Working tree**, refresh, and create a suggestion on the current lines. Edit hard-linked files directly to preserve their links. Staging and committing are separate Git operations.

**Export Markdown** checks current working-tree and stack locations when you open the preview, even if you have not pressed **F5**. The report keeps the original range and excerpt, identifies verified staged or committed locations, and records whether a suggestion was proposed or applied. An application receipt records the working-file edit. A committed location includes the commit ID of the reviewed head.

Applying a suggestion leaves its review status open until you select **Resolve**. Reopening an applied suggestion keeps its application receipt. A comment keeps its status when its lines move into the index or a stack commit.

Branchline saves comments and viewed files in SQLite under `$XDG_DATA_HOME/branchline` (default `~/.local/share/branchline`) or `%LOCALAPPDATA%\Branchline` on Windows. Comments are local to a checkout and a branch pair. The current stack includes the full-stack pair and all adjacent pairs, including notes saved against earlier tips.

## Preferences

On Linux and WSL, preferences live in `~/.config/branchline/config.json`. Setting `XDG_CONFIG_HOME` changes the parent directory. On Windows the usual path is `%APPDATA%\Branchline\config.json`.

Choose **Edit stack → Review stack** to remember the base branch for that checkout. Branchline reuses it when a review head is renamed or deleted. Switching between **Unified** and **Split** and resizing the sidebar save those preferences across repositories. Branchline creates the file when you open a repository and imports your existing stack and sidebar width. After editing the branch or layout settings by hand, press **F5** to reload them.

```json
{
  "hardware_acceleration": true,
  "diff_layout": "split",
  "sidebar_width": 280,
  "repositories": {
    "/home/alex/src/project": {
      "base_branch": "refs/heads/develop",
      "layers": ["refs/heads/feature/search"]
    }
  }
}
```

Hardware acceleration is enabled by default. The system graphics libraries choose an available device and handle fallback. To use software rendering, set `hardware_acceleration` to `false`, close all Branchline windows, and relaunch.

## Keyboard shortcuts

| Shortcut | Action |
| --- | --- |
| Ctrl+O | Open a repository |
| Ctrl+B | Edit the stack |
| Ctrl+F / Ctrl+Shift+F / Ctrl+P | Open the search palette |
| Up / Down in search | Select the previous / next result |
| Enter / Escape in search | Open the selected result / dismiss search |
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
xvfb-run -a -s '-screen 0 3840x2160x24' dbus-run-session -- python3 tools/smoke_native.py --binary src-tauri/target/release/branchline
```

The smoke test opens a temporary branch stack, checks which diff panes receive pointer and keyboard input, comments through the UI, applies a suggestion, stages and commits the edit with Git, and verifies its location in the Markdown preview. It uses an isolated review database. The previous Python regression suite runs with `python3 -m unittest discover -s tests` on a desktop display.

### Compare large-diff performance

Run the CPU benchmark from the project root to compare how the Rust port and Python prepare a 4,000-line addition and a 40,000-line mixed diff. It times patch processing and the first construction of unified and split rows from data already in memory. It needs Git, `rustc`, Node with npm, and Python with Tk for the shared fixture generator. It runs without a display or GPU.

```sh
npm ci
python3 tools/benchmarks/cpu_layout.py
```

The Rust port uses Rust to prepare the compact patch and JavaScript to decode it and build rows. The headless runner uses Node for the JavaScript stages. Once both layouts exist, the desktop app keeps them for the open file. WebKitGTK and GTK handle drawing on Linux and WSLg. [CPU timings and measurement details](tools/benchmarks/large-diffs.md)

To measure the whole desktop interaction on Linux, build the release and run the click-to-visible probe on a private X11 display. This includes Git, widget construction and presentation. It needs Xvfb, xauth, D-Bus, WebKitWebDriver, Python with Tk, Git, GNU patch and the X11 test libraries. Use a fresh output directory and a Git checkout containing the original benchmark revision. The launcher materializes that revision in a temporary directory and runs its checksum-verified driver against the executable passed with `--binary`.

```sh
xvfb-run -a -s '-screen 0 1920x1080x24 -dpi 96' dbus-run-session -- \
  python3 tools/benchmarks/current.py xvfb build/benchmarks/my-run/xvfb \
  --binary src-tauri/target/release/branchline
```

The frozen contract describes the original benchmark revision. It rejects the current feature tree because its source and tests have changed. Use the packaged smoke workflow above to verify the current app.

The desktop probe writes `samples.jsonl` and `summary.json`. The archived Radeon and Xvfb campaign records timings for earlier Linux builds with explicit X11 rendering settings. [Historical campaign](tools/autoresearch/rust-layout/state.md)
