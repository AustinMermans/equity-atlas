# November 2026 proof of concept

The first market snapshot was captured on 2026-11-09 UTC (November 8 Pacific). All names remain visible even when their statements, industry mapping or valuation inputs are missing.

| Check | Largest 100 | Expansion to 250 |
| --- | ---: | ---: |
| Companies shown | 100 | 250 |
| Business archetype assigned | 100 | 192 |
| Recent annual statement | 90 | 178 |
| At least one observed market multiple | 85 | 172 |
| Lead model passed input checks | 50 | 103 |
| Historical cycle read | 15 | 34 |

The review checked three distinct cases: positive common book and clean-surplus history support residual income for a bank; a loss and incompatible peer set keep an earnings valuation off an IPO case; a cyclical producer's most recent margin can sit well above its prior-period median without becoming the terminal margin. The published Prosus NAV table also exercises the asset route independently of statement freshness. Automated FCFE was possible for only three issuers in the larger run. These are mechanically eligible scenarios, not issuer models signed off for investment decisions.

The first run exposed missed capex and depreciation tags, inappropriate promotion of dividend-only models for reinvesting businesses, and weak peers for companies with different economics. The revised engine preserves the source tag for each alias, uses DDM as a cross-check for ordinary operating firms, and requires same-group, accounting, period, size and profitability checks for peer valuation. EDGAR remains the main source; the proof also exercised ESEF and verified issuer-report fallbacks. Two warm runs of the expanded data produced identical snapshot bytes. Formula tests independently tie Gordon and residual income together, confirm terminal value timing, and check loss, funding, filing and currency guards.

The wider sample does not meet the 85% recent-statement coverage gate for expanding to 1,000. The most useful next step is a provider that covers global exchange identifiers, current and historical caps, and standardized IFRS data with allowed display rights. Annual/LTM reconciliation and more precise risk and EV bridge data should come before trusting a universe-wide valuation rank.
