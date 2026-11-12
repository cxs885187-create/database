# English Vocabulary Database

This repository stores a small, versioned English vocabulary database for computer science and Python study. The workbook is designed for quick lookup, review, and incremental extension in Excel.

## Pictures
You can see every version's picture in fold "pictures"

## Current version

`v0.3` is the current release. It contains 30 records: the 18 terms from v0.2 and twelve additional terms selected from page 1 of the supplied glossary document. It adds concise usage notes alongside the existing English definitions and examples.

## Repository layout

```text
version control/
|-- v0.1/
|   |-- dabase V0.1.xlsx
|   `-- v0.1 design.md
|-- v0.2/
|   |-- v0.2.xlsx
|   `-- v0.2 design.md
`-- v0.3/
    |-- v0.3.xlsx
    `-- v0.3 design.md
```

The supplied source glossary document is kept at the repository root as reference material. Version folders contain English workbook labels and English documentation.

## v0.3 workbook

Open `version control/v0.3/v0.3.xlsx` in Excel or another compatible spreadsheet application. The `Vocabulary` worksheet provides:

- A filterable table named `VocabularyTable`.
- `No.`, `Word`, `Part of Speech`, `Meaning`, `Example Sentence`, `Usage Note`, `Topic`, and `Source` fields.
- Frozen headers and the record-number column for easier scrolling.
- Source highlighting that distinguishes v0.1 seed terms from glossary additions.

## Version history

- **v0.1**: six-term prototype with the fields `No.`, `Word`, and `Meaning`.
- **v0.2**: expanded seven-field schema, 12 page-1 glossary additions, improved colors and layout, filtering, frozen panes, and source traceability.
- **v0.3**: 12 more page-1 glossary terms and a `Usage Note` field, while retaining the Excel-only workflow and v0.2 study fields.

See each version's design document for requirements, decisions, and known limitations.

## Contribution notes

Add new records only after checking the supplied source material and keeping the `Source` field accurate. Keep version-specific changes in a new folder under `version control` and update the root README when a new release becomes current.
