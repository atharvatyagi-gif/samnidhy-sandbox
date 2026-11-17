# Head-to-head result: the strategy desk against model E on survivorship-free data

Run 2026-11-17 by scripts/blab/head_to_head.py under the rules in HEAD_TO_HEAD.md (written before any result).
Data: NSE's daily files 2008-01-01 to 2026-11-16, 4,283 companies including delisted ones; 1,300
splits and bonuses from NSE's corporate-actions record. Both models: same simulator, costs, next-open fills, risk control
(70% invested, 35% below the 200-day average), no kill switch. Hold-out from 2024-11-16.

## Verdict: **keep model E; the desk stays a research page**

| Gate | Passed? |
|---|---|
| 1 risk (worst fall no deeper than -25%) | **no** |
| 2 quality (higher Sharpe than model E, design years) | **no** |
| 3 hold-out (yearly return within 2 points of model E) | **no** |
| 4 stress (Sharpe above model E with vanished holdings at zero) | **no** |

## Results (yearly return / worst fall / Sharpe)

| Base case | Whole period | Design years | Hold-out |
|---|---|---|---|
| Model E | 16.9% / -33.3% / 0.94 | 17.4% / -28.8% / 0.98 | 13.3% / -26.6% / 0.69 |
| Strategy desk (blend) | 8.7% / -35.2% / 0.73 | 10.0% / -35.2% / 0.83 | 0.1% / -18.9% / 0.08 |
| NIFTY 50 held | 10.0% / -38.4% / 0.66 | 10.9% / -38.4% / 0.7 | 3.6% / -15.6% / 0.33 |

| Stress case (vanished holdings worth nothing) | Whole period | Design years | Hold-out |
|---|---|---|---|
| Model E | 14.5% / -34.5% / 0.82 | 14.8% / -30.6% / 0.85 | 12.2% / -28.6% / 0.64 |
| Strategy desk (selector) | -1.7% / -45.3% / -0.14 | -0.7% / -45.3% / -0.02 | -8.5% / -21.5% / -1.14 |

## How big the survivorship bias was (same rules, old cache of companies listed today)

| | Old cache (biased) | Bias-free |
|---|---|---|
| Model E | 17.4% / -34.2% / 0.98 | 17.5% / -33.7% / 0.99 (first run) |
| Strategy desk | 14.0% / -44.1% / 0.95 | 11.5% / -33.5% / 0.92 (first run) |

## Fix after the first run (recorded as the rules require)

The first run read only the EQ series, so a company moved to NSE's trade-to-trade list (BE) or suspended list (BZ) looked
like it had vanished: 77 of model E's holdings, which the stress case then counted as total losses. Holdings are now valued
and sold at their BE/BZ trades (new buys still need an EQ day). Model E's vanished holdings fell from 77 to
10. First run, base case: model E 17.5% / -33.7% / 0.99, desk 11.5% / -33.5% / 0.92;
stress case: model E -1.0% / -77.8% / 0.06, desk -9.7% / -81.1% / -1.17. The verdict did not change.

## Notes

- Model E itself falls deeper than the owner's -25% limit on this data (worst fall -33.3% with its
  risk control); in live trading its kill switch stops new buying at -25%, which this test leaves out for both models.
- The desk stays a research page; its selector also did not beat its own equal blend (STRATEGY_EVIDENCE.md).
