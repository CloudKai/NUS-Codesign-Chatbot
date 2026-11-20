# Sol-authored augmentation for Laya Learn

The course question and evidence manifest in `scripts/evals/datasets` informed
the training and evaluation prompts. All messages are synthetic. A leading
`+` means retrieve official course evidence. A leading `-` means skip it.
The optional two ` || ` fields hold the prior student message and assistant
response. The author of the training examples also authored the new evaluation
set. It is separate from training and calibration, with no exact normalized
message overlap, and has no independent human audit.

The experiment uses the original Phase 3d split and the same Laya Learn question,
Vega reader, gate eligibility, and threshold selection. It adds the eligible
synthetic examples to the original training set and fits a new bundle. The
61 original calibration rows determine its cutoffs before evaluation. The
historical comparison uses the same 84 rows as the earlier pilot. The fresh
comparison uses 30 retrieve and 30 skip messages, including follow-ups and
mixed-language phrasing. All fresh rows have no selected files.

Run the experiment from the repo root with the original Phase 3d artifacts and
checkpoint at the paths shown in `run.py`. Use the experiment environment with
Laya 0.4.38 and VegaML 0.17.1.

```sh
PYTHONPATH=. TOKENIZERS_PARALLELISM=false python -u /path/to/sol-teacher/run.py
```
