# Model promotion checklist

- [ ] Dataset snapshot is immutable and point-in-time correct.
- [ ] Feature, target, split, and model versions are recorded.
- [ ] Mandatory baselines were evaluated.
- [ ] Final holdout was not used for tuning.
- [ ] Backtest includes signal timing, liquidity, spread, slippage, commission, and risk limits.
- [ ] Model artifact checksum and trusted loading policy pass.
- [ ] Performance is stable across relevant periods and cohorts.
- [ ] Monitoring thresholds and rollback model are configured.
- [ ] Model validator approved.
- [ ] Risk owner approved.
- [ ] Deployment approver approved.
- [ ] Shadow evidence meets the minimum sample requirement.
- [ ] Automatic production promotion remains disabled.
