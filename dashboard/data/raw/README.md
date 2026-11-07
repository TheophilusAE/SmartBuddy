# data/raw

Put external labelled CSV files here if you have any (see `docs/DATA_DICTIONARY.md` for the required columns).
Treat them as untrusted input: `python -m ml.prepare_dataset --csv data/raw/<file>.csv` validates them as plain data.

Everything in this folder except this README is gitignored.
