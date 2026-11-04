# Experiment register template

Record every material experiment, including unsuccessful trials.

| Field | Entry |
|---|---|
| Experiment ID | |
| Owner | |
| Date | |
| Hypothesis | |
| Dataset version and fingerprint | |
| Feature-set version | |
| Target version | |
| Split-plan fingerprint | |
| Model plugin and version | |
| Configuration hash | |
| Random seeds | |
| Compute environment | |
| Baselines | |
| Validation metrics | |
| Holdout metrics | |
| Backtest assumptions and costs | |
| Robustness checks | |
| Result | accepted / rejected / inconclusive |
| Reason | |
| Known limitations | |
| Artifact references | |
| Reviewer | |

The final holdout must not be reused as an iterative tuning set. When repeated analysis makes a holdout operationally contaminated, retire it and document the decision before defining a new holdout.
