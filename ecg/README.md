# ECG sex discordance on open data

Replication on open data of Sau et al., *Lancet Digital Health* 2025 ("AI-enhanced electrocardiography for the identification of a sex-related cardiovascular risk continuum").

- `code15_sex_discordance.ipynb`: the Kaggle notebook (the `.py` file is the same code).
- Data: CODE-15% (Zenodo 4916206, CC BY 4.0), downloaded inside the notebook. Death is from any cause, not only cardiovascular.
- Model: the residual network design of Ribeiro et al. 2020 (github.com/antonior92/automatic-ecg-diagnosis, MIT), in PyTorch.

Run on Kaggle: New notebook → File → Import notebook → this file. Settings: Accelerator GPU, Internet on. Then Save version → Save & Run All (about 2–4 hours). Outputs: `results.json`, `ecg_sex_discordance.png`, `test_predictions.csv`, `ecg_sex_resnet.pt`.

Research use only; not a diagnostic tool.
