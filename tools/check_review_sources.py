"""Open unchanged text, binary and submodule palette destinations."""

import subprocess

import smoke_native
from check_review_context import resize
from check_review_controls import OPTIONS, QUERY
from smoke_native import git

SUBMODULE = "1234567890123456789012345678901234567890"


def fixture(repo):
    repo.mkdir()
    git(repo, "init", "-qb", "main")
    git(repo, "config", "user.name", "Branchline Smoke")
    git(repo, "config", "user.email", "smoke@example.test")
    git(repo, "config", "commit.gpgsign", "false")
    (repo / "baseline-logo.png").write_bytes(b"\x89PNG\0fixture")
    (repo / "empty-source.txt").write_text("")
    (repo / "guide.txt").write_text("Source destination text\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "update-index", "--add", "--cacheinfo",
        f"160000,{SUBMODULE},vendor/module")
    git(repo, "commit", "-qm", "Add baseline sources")
    (repo / "vendor/module").mkdir(parents=True)
    git(repo, "switch", "-qc", "feature/search")
    (repo / "changed.txt").write_text("Searchable feature change\n", encoding="utf-8")
    git(repo, "add", "changed.txt")
    git(repo, "commit", "-qm", "Add feature")
    entry = subprocess.check_output(["git", "-C", str(repo), "ls-tree", "HEAD", "--", "vendor/module"])
    assert SUBMODULE.encode() in entry


def open_source(driver, query, scope):
    driver.click("#search-review")
    driver.wait("document.querySelector('#search-palette').open")
    if scope != "all":
        driver.click(f"#palette-scope option[value={scope}]")
    driver.fill(QUERY, query)
    driver.click(OPTIONS + "[data-search-kind=path]", query, False)
    driver.wait("!document.querySelector('#search-palette').open")
    driver.expect_text("#dialog[open] h2", query)
    driver.expect_text("#dialog-body", "feature/search")


def exercise(driver, _repo, _screenshot):
    driver.expect_text("#diff", "Searchable feature change")
    driver.wait("!document.querySelector('#app').hasAttribute('aria-busy')")
    for width, height in ((1280, 720), (720, 460)):
        resize(driver, width, height)
        for scope in ("all", "branch"):
            open_source(driver, "baseline-logo.png", scope)
            driver.expect_text("#dialog-body", "Binary file · 12 bytes")
            assert not driver.script("return document.querySelector('#dialog .cm-editor')")
            driver.click("#dialog-actions button", "Close")
            open_source(driver, "vendor/module", scope)
            driver.expect_text("#dialog-body", "Git submodule")
            driver.expect_text("#dialog-body pre", SUBMODULE)
            driver.click("#dialog-actions button", "Close")
        open_source(driver, "empty-source.txt", "all")
        driver.wait("!!document.querySelector('#dialog .cm-editor')")
        driver.click("#dialog-actions button", "Close")
        open_source(driver, "guide.txt", "all")
        driver.expect_text("#dialog .cm-content", "Source destination text")
        driver.click("#dialog-actions button", "Close")
        print(f"Text, empty, binary and submodule destinations passed at {width}×{height}.",
              flush=True)


if __name__ == "__main__":
    smoke_native.fixture = fixture
    smoke_native.exercise = exercise
    smoke_native.main()
