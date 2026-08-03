# Walk-Forward Validation Report
**Sequential Out-of-Sample Performance Stability Analysis**

## Rolling Validation Results
- **Training Window**: 3 Months (90 days)
- **Validation Window**: 1 Month (30 days)

| Window | Train Window | Validation Window | Train Exp | Val Exp | Train PF | Val PF | Val DD | Val Trades |
|:---|:---|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| Window 1 | 25/08/26-25/11/24 | 25/11/24-25/12/24 | -0.312R | +0.519R | 0.70 | 1.63 | 3.39% | 21 |
| Window 2 | 25/09/25-25/12/24 | 25/12/24-26/01/23 | -0.139R | -1.000R | 0.91 | 0.00 | 9.41% | 18 |
| Window 3 | 25/10/25-26/01/23 | 26/01/23-26/02/22 | -0.281R | -0.406R | 0.72 | 0.55 | 5.81% | 19 |
| Window 4 | 25/11/24-26/02/22 | 26/02/22-26/03/24 | -0.256R | +0.380R | 0.72 | 1.45 | 2.85% | 15 |
| Window 5 | 25/12/24-26/03/24 | 26/03/24-26/04/23 | -0.385R | -0.188R | 0.55 | 0.77 | 3.4% | 17 |
| Window 6 | 26/01/23-26/04/23 | 26/04/23-26/05/23 | -0.102R | -1.000R | 0.87 | 0.00 | 7.47% | 16 |
| Window 7 | 26/02/22-26/05/23 | 26/05/23-26/06/22 | -0.281R | +0.000R | 0.69 | 0.00 | 0.0% | 0 |

---

## Stability Assessment
- **Expectancy Stability**: Expectancies are evaluated across validation windows. Stability indicates if out-of-sample performance remains positive.
- **Drawdown Stability**: Drawdown variance between train and validation windows measures sizing robustness.
- **Trade Frequency**: Stable trade frequency ensures parameter settings are not fitting to micro-structures.
