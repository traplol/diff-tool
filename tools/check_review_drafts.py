"""Check comment, suggestion, and Markdown draft recovery in packaged Branchline."""

import smoke_native
from check_diff_resize import press

FIELD = "dialog[open] textarea"
REPLACEMENT = "dialog[open] textarea.replacement"
MESSAGE = "dialog[open] label:last-of-type textarea"
CHECKBOX = "dialog[open] input[type=checkbox]"
ESCAPE = "\ue00c"


def closed(driver):
    driver.wait('!document.querySelector("dialog[open]")')


def value(driver, field, expected):
    driver.wait(
        "document.querySelector(arguments[0])?.value === arguments[1]",
        field,
        expected,
    )


def action(driver, title):
    driver.click("#dialog-actions button", title)


def dismiss(driver, key=False):
    if key:
        press(driver, ESCAPE)
    else:
        driver.click("dialog .dialog-top [aria-label=Close]")
    closed(driver)


def select_capacity(driver):
    driver.click("#file-list button[aria-label='cache.txt']")
    driver.expect_text("#diff", "capacity = three")
    driver.click("#diff .cm-line.bl-row-add", "capacity = three")


def check_comment(driver):
    first = "Please describe the intended capacity for an empty queue."
    edited = "Please add the empty queue case to the change description."
    select_capacity(driver)
    driver.click("#comment")
    driver.fill(FIELD, first)
    dismiss(driver, key=True)
    driver.click("#file-list button[aria-label='history.txt']")
    driver.click("#comment")
    value(driver, FIELD, "")
    dismiss(driver)
    driver.click("#refresh")
    driver.wait('!document.querySelector("#app").hasAttribute("aria-busy")')
    select_capacity(driver)
    driver.click("#comment")
    value(driver, FIELD, first)
    driver.expect_text("#dialog [role=status]", "Draft restored")
    action(driver, "Save comment")
    closed(driver)
    driver.expect_text("#diff [data-note]", first)
    select_capacity(driver)
    driver.click("#comment")
    value(driver, FIELD, "")
    dismiss(driver)

    driver.click("#diff [data-note] button", "Edit")
    driver.fill(FIELD, edited)
    dismiss(driver)
    driver.click("#diff [data-note] button", "Edit")
    value(driver, FIELD, edited)
    action(driver, "Discard draft")
    closed(driver)
    driver.click("#diff [data-note] button", "Edit")
    value(driver, FIELD, first)
    dismiss(driver)


def check_suggestion(driver):
    proposal = "capacity = documented_limit"
    rationale = "Name the configured value so the fallback is visible to reviewers."
    select_capacity(driver)
    driver.click("#suggest")
    driver.fill(MESSAGE, rationale)
    action(driver, "Save suggestion")
    driver.expect_text("#dialog-error", "Edit the replacement")
    dismiss(driver, key=True)
    driver.click("#suggest")
    value(driver, MESSAGE, rationale)
    driver.fill(REPLACEMENT, proposal)
    action(driver, "Keep draft")
    closed(driver)
    driver.click("#suggest")
    value(driver, REPLACEMENT, proposal)
    value(driver, MESSAGE, rationale)
    action(driver, "Save suggestion")
    closed(driver)
    driver.expect_text("#diff .bl-card .bl-after", proposal)
    select_capacity(driver)
    driver.click("#suggest")
    value(driver, REPLACEMENT, "capacity = three")
    value(driver, MESSAGE, "")
    dismiss(driver)
    driver.click("#diff .bl-card:has(.bl-after) button", "Edit")
    assistant_text = "capacity = configured_maximum"
    reviewer_text = "Use the actual configuration key in this replacement."
    driver.fill(REPLACEMENT, assistant_text)
    driver.fill(MESSAGE, reviewer_text)
    dismiss(driver, key=True)
    driver.click("#diff .bl-card:has(.bl-after) button", "Edit")
    value(driver, REPLACEMENT, assistant_text)
    value(driver, MESSAGE, reviewer_text)
    action(driver, "Discard draft")
    closed(driver)
    driver.click("#diff .bl-card:has(.bl-after) button", "Edit")
    value(driver, REPLACEMENT, proposal)
    value(driver, MESSAGE, rationale)
    dismiss(driver)


def check_markdown(driver):
    full = "Review summary prepared for the feature owner"
    open_only = "Remaining work before approval"
    driver.click("#export")
    driver.fill(FIELD, full)
    driver.click(CHECKBOX)
    driver.preview(includes=["Open comments only"], excludes=[full])
    driver.fill(FIELD, open_only)
    driver.click(CHECKBOX)
    value(driver, FIELD, full)
    dismiss(driver, key=True)

    driver.click("#tab-comments")
    driver.click("#scope option[value=all]")
    driver.click("#export")
    driver.preview(includes=["Code review"], excludes=[full, open_only])
    dismiss(driver)
    driver.click("#scope option[value=current]")
    driver.click("#export")
    value(driver, FIELD, full)
    driver.click(CHECKBOX)
    value(driver, FIELD, open_only)
    action(driver, "Reset this version")
    driver.wait("document.activeElement.matches(arguments[0])", FIELD)
    driver.preview(
        includes=["Open comments only", "Please describe the intended capacity"],
        excludes=[open_only],
    )
    driver.click(CHECKBOX)
    value(driver, FIELD, full)
    action(driver, "Keep drafts")
    closed(driver)
    driver.click("#export")
    value(driver, FIELD, full)
    driver.click(CHECKBOX)
    driver.preview(includes=["Open comments only"], excludes=[open_only])
    dismiss(driver)


def check_relaunch(driver):
    new_comment = "Record why the queue can safely run without an override."
    edited_comment = "Please link the capacity policy from the operator guide."
    new_code = "capacity = queue_limit"
    new_rationale = "Use the configured capacity for the current queue."
    edited_code = "capacity = configured_queue_limit"
    edited_rationale = "Match the name of the setting in the operator guide."
    full_markdown = "Draft overview for the whole review"
    open_markdown = "Draft handoff for unresolved questions"
    comment_edit = "#diff .bl-card:not(:has(.bl-after)) button"
    suggestion_edit = "#diff .bl-card:has(.bl-after) button"

    driver.click("#tab-changes")
    select_capacity(driver)
    driver.click("#comment")
    driver.fill(FIELD, new_comment)
    dismiss(driver, key=True)
    driver.click(comment_edit, "Edit")
    driver.fill(FIELD, edited_comment)
    dismiss(driver)
    driver.click("#suggest")
    driver.fill(REPLACEMENT, new_code)
    driver.fill(MESSAGE, new_rationale)
    dismiss(driver)
    driver.click(suggestion_edit, "Edit")
    driver.fill(REPLACEMENT, edited_code)
    driver.fill(MESSAGE, edited_rationale)
    dismiss(driver, key=True)
    driver.click("#export")
    driver.fill(FIELD, full_markdown)
    driver.click(CHECKBOX)
    driver.fill(FIELD, open_markdown)

    # End the actual app session with the edited preview still open.
    driver.restart_session()
    select_capacity(driver)
    driver.click("#comment")
    value(driver, FIELD, new_comment)
    driver.expect_text("#dialog [role=status]", "Draft restored")
    dismiss(driver)
    driver.click(comment_edit, "Edit")
    value(driver, FIELD, edited_comment)
    dismiss(driver)
    driver.click("#suggest")
    value(driver, REPLACEMENT, new_code)
    value(driver, MESSAGE, new_rationale)
    dismiss(driver)
    driver.click(suggestion_edit, "Edit")
    value(driver, REPLACEMENT, edited_code)
    value(driver, MESSAGE, edited_rationale)
    dismiss(driver)
    driver.click("#export")
    value(driver, FIELD, full_markdown)
    driver.click(CHECKBOX)
    value(driver, FIELD, open_markdown)
    dismiss(driver)


def exercise(driver, _repo, _screenshot):
    check_comment(driver)
    check_suggestion(driver)
    check_markdown(driver)
    check_relaunch(driver)
    print("Packaged comment, suggestion, and Markdown draft recovery passed after app relaunch.")


if __name__ == "__main__":
    smoke_native.exercise = exercise
    smoke_native.main()
