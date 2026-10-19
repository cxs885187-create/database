# English Vocabulary Database

This repository stores a small, versioned English vocabulary database for computer science and Python study. The workbook is designed for quick lookup, review, and incremental extension in Excel.

## Current version

`v0.2` is the current release. It contains 18 records: the six terms from the v0.1 prototype and twelve additional terms selected from page 1 of the supplied glossary document.

## Repository layout

```text
version control/
|-- v0.1/
|   |-- dabase V0.1.xlsx
|   `-- v0.1 design.md
`-- v0.2/
    |-- v0.2.xlsx
    `-- v0.2 design.md
```

The supplied source glossary document is kept at the repository root as reference material. Version folders contain English workbook labels and English documentation.

## v0.2 workbook

Open `version control/v0.2/v0.2.xlsx` in Excel or another compatible spreadsheet application. The `Vocabulary` worksheet provides:

- A filterable table named `VocabularyTable`.
- `No.`, `Word`, `Part of Speech`, `Meaning`, `Example Sentence`, `Topic`, and `Source` fields.
- Frozen headers and the record-number column for easier scrolling.
- Source highlighting that distinguishes v0.1 seed terms from new glossary terms.

## Version history

- **v0.1**: six-term prototype with the fields `No.`, `Word`, and `Meaning`.
- **v0.2**: expanded seven-field schema, 12 page-1 glossary additions, improved colors and layout, filtering, frozen panes, and source traceability.

See each version's design document for requirements, decisions, and known limitations.

## Contribution notes

Add new records only after checking the supplied source material and keeping the `Source` field accurate. Keep version-specific changes in a new folder under `version control` and update the root README when a new release becomes current.
