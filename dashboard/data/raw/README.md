# data/raw

Put external labelled CSV files here if you have any (columns: `recorded_at, session_id, temperature_c, humidity_pct, light_pct, comfort_rating`, optional `motion_detected`, `source`).
Treat them as untrusted input: `python -m ml.prepare_dataset --csv data/raw/<file>.csv` validates them as plain data.

Everything in this folder except this README is gitignored.
