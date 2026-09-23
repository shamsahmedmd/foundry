# Baselines

Known-good `results.json` files, used by `run_evaluations.py --baseline` to detect
token-usage regressions (> 20% fails the `test`/`prod` gate profiles).

The Test stage reads `eval/baselines/test.json`. If the file doesn't exist, the
regression metric isn't computed. The `ci` profile only tracks it, but the `test` profile
enforces it, so commit a baseline before the first Test run or pass `--allow-missing`.

After a release is accepted:

    cp eval/results/test-results.json eval/baselines/test.json
