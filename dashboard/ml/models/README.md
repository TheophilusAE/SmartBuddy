# ml/models

`ml.train_model` writes here:

- `comfort_v<date>-<time>.joblib` - the trained model (only if it beat the baseline)
- `current.json` - metadata of the deployed model, including the SHA-256 of the .joblib
- `last_training.json` - result of the latest training attempt (also when it was refused)
- `actual_vs_predicted_<version>.png` - optional plot (`--plot`)

**Never copy a .joblib file from anywhere else into this folder.** joblib files are pickles and can run code
when loaded. The backend only loads a file whose hash matches `current.json`, but that only proves the file
wasn't changed since training here.

Everything except this README is gitignored.
