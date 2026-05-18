# Known Issues

- The root workspace was not a Git repository before baseline setup.
- Imported source folders contain nested `.git` directories and dirty working trees. They are not part of the clean baseline unless explicitly approved later.
- V9 code contains hard-coded lab PC paths for model folders and campaign output folders. These are documented for later stabilization and are not changed in the baseline.
- Generated campaign data and analysis outputs exist in the workspace but are excluded from Git.
