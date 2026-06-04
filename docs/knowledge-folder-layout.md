# Lance Knowledge Folder Layout

Lance can read `.txt` knowledge files from nested folders under:

- `data/faqs/`
- `data/instructions/`

Flat files in those folders still work. Nested folders are optional and are intended to make future maintenance easier.

## Recommended FAQ Folders

Use `data/faqs/` for policy and general Campus Store questions.

Suggested layout:

```text
data/faqs/
  immediate-access/
  returns/
  store-info/
  ordering-shipping/
  textbooks/
```

Examples:

```text
data/faqs/immediate-access/ia_overview.txt
data/faqs/returns/textbook_refund_policy.txt
data/faqs/store-info/campus_store_hours.txt
```

## Recommended Instruction Folders

Use `data/instructions/` for step-by-step troubleshooting and platform access instructions.

Suggested layout:

```text
data/instructions/
  immediate-access/
  platforms/
    cengage/
    mcgraw-hill/
    pearson/
    vitalsource/
    bedford/
    sage/
    wiley/
  browser-troubleshooting/
  digital-codes/
```

Examples:

```text
data/instructions/platforms/cengage/ia_cengage_mindtap_access.txt
data/instructions/platforms/mcgraw-hill/ia_mcgraw_hill_connect_access.txt
data/instructions/browser-troubleshooting/ia_browser_chrome_cookies_popups.txt
```

## Naming Guidance

- Keep filenames stable once they are published.
- Use lowercase words separated by underscores.
- Keep the `.txt` extension.
- Avoid duplicate filenames in different folders when possible.
- Do not place generated files such as `faqs_chunks.txt` or `instructions_chunks*.txt` in content folders.

## Source Metadata

Lance keeps existing `source_id` behavior based on file front matter or the filename stem. Moving a file into a folder does not need to change its `source_id`, but source paths shown by admin tools will include the folder path.

For now, existing production files remain in their current flat locations to avoid changing hardcoded Quick Help source paths and source ordering. Move them only as a coordinated follow-up after updating references and rerunning the retrieval/Quick Help regression suite.

## Admin Editing

The admin page can list, open, edit, archive, and remove flat or nested `.txt` files. When editing a published file, keep the YAML front matter at the top of the file and preserve these fields:

- `source_id`
- `source_type`
- `category`
- `platform`
- `issue_type`
- `priority`

Saving validates the front matter before publishing, keeps a timestamped backup of the previous version under `data/_archive/backups/`, and rebuilds the search index. Removing content moves the file under `data/_archive/removed/` instead of permanently deleting it.
