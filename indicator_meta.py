"""Display metadata + explanations for each indicator.

Used by dashboard.py to enrich latest.json so the HTML dashboard can render
hover tooltips, click-to-zoom modals with explanations, and value formatting.
"""

INDICATOR_META = {
    "mri": {
        "label": "Mean Reversion Index (MRI)",
        "category": "Strategy Signal",
        "value_fmt": ".1f",
        "value_suffix": "",
        "direction": "lower = bullish (capitulation)",
        "regime_bands": [
            {"lo": 0,   "hi": 12,  "label": "Q-fire zone (capitulation)", "color": "#16c784"},
            {"lo": 12,  "hi": 30,  "label": "Accumulation",               "color": "#7bd88f"},
            {"lo": 30,  "hi": 60,  "label": "Mid-range",                  "color": "#f3c623"},
            {"lo": 60,  "hi": 100, "label": "Extended",                   "color": "#f9844a"},
            {"lo": 100, "hi": 200, "label": "Overheated",                 "color": "#ea3943"},
        ],
        "explanation": (
            "Checkonchain's Mean Reversion Index — a composite oscillator of BTC price vs its "
            "fair-value models (200WMA, realized price, VWAPs, power law). This is the SAME "
            "series v8.5 reads: when MRI prints below 12, the t1b Q-fire deploys 100% of cash "
            "long MSTR (≥30 days since the last fire). MRI is an exceptional bottom-caller and "
            "a weak top-caller — weighted accordingly."
        ),
        "use": (
            "Below 12 = the strategy's long trigger arms. The dashboard tracks the live value "
            "against that line so you see the Q-fire approaching."
        ),
    },
    "sth_sopr": {
        "label": "STH-SOPR",
        "category": "Cohort",
        "value_fmt": ".3f",
        "value_suffix": "",
        "direction": "sub-1 = tourists capitulating (bullish)",
        "regime_bands": [
            {"lo": 0.90, "hi": 0.97, "label": "STH capitulation",      "color": "#16c784"},
            {"lo": 0.97, "hi": 1.00, "label": "Reclaim zone",          "color": "#7bd88f"},
            {"lo": 1.00, "hi": 1.03, "label": "Healthy profit-taking", "color": "#f3c623"},
            {"lo": 1.03, "hi": 1.05, "label": "Heavy realization",     "color": "#f9844a"},
            {"lo": 1.05, "hi": 1.15, "label": "Euphoric realization",  "color": "#ea3943"},
        ],
        "explanation": (
            "Short-Term Holder SOPR — whether coins held <155 days are being spent at a profit "
            "(>1) or loss (<1). The clearest read on the 'tourist' cohort: sustained sub-1 means "
            "recent buyers are capitulating (bottoms); >1.05 means they're euphorically realizing "
            "gains (tops)."
        ),
        "use": "Sub-1 at an entry = tourists flushed, low risk of being late. >1.05 = late-cycle.",
    },
    "sth_mvrv": {
        "label": "Cohort Posture (STH-MVRV)",
        "category": "Cohort",
        "value_fmt": ".2f",
        "value_suffix": "x",
        "direction": "lower = tourists underwater (bullish)",
        "regime_bands": [
            {"lo": 0.6, "hi": 1.0, "label": "Tourists underwater",  "color": "#16c784"},
            {"lo": 1.0, "hi": 1.2, "label": "Break-even",           "color": "#7bd88f"},
            {"lo": 1.2, "hi": 1.4, "label": "Modest profit",        "color": "#f3c623"},
            {"lo": 1.4, "hi": 1.7, "label": "Tourists arriving",    "color": "#f9844a"},
            {"lo": 1.7, "hi": 3.0, "label": "Tourists pouring in",  "color": "#ea3943"},
        ],
        "explanation": (
            "Short-Term Holder MVRV — market value vs cost basis for the <155-day cohort. The "
            "core of the 'are the tourists here or gone' read: below 1.0 the recent crowd is "
            "underwater (they leave / capitulate → bottoms); well above 1.4 they're sitting on "
            "fat gains and piling in (→ tops). Paired with STH-SOPR for the posture label."
        ),
        "use": "Tourists gone (<1.0) is a strong accumulation tell; pouring in (>1.6) is a top warning.",
    },
    "feargreed": {
        "label": "Fear & Greed Index",
        "category": "Sentiment",
        "value_fmt": ".0f",
        "value_suffix": "",
        "direction": "extreme fear = bullish",
        "regime_bands": [
            {"lo": 0,  "hi": 25,  "label": "Extreme Fear", "color": "#16c784"},
            {"lo": 25, "hi": 45,  "label": "Fear",         "color": "#7bd88f"},
            {"lo": 45, "hi": 55,  "label": "Neutral",      "color": "#f3c623"},
            {"lo": 55, "hi": 75,  "label": "Greed",        "color": "#f9844a"},
            {"lo": 75, "hi": 100, "label": "Extreme Greed","color": "#ea3943"},
        ],
        "explanation": (
            "Crypto Fear & Greed Index (alternative.me, 0–100). Composite of volatility, momentum, "
            "social, and survey signals. Extreme fear historically marks accumulation; extreme "
            "greed marks froth. Asymmetric: fear bottoms snap, greed tops grind — so extreme fear "
            "is weighted heavier for longs than extreme greed is for shorts. Also v8.5's PUT IV input."
        ),
        "use": "Extreme fear (<25) corroborates a long; greed (>75) corroborates a hedge, more loosely.",
    },
    "tbl": {
        "label": "TBL Liquidity",
        "category": "Liquidity",
        "value_fmt": ".2f",
        "value_suffix": "",
        "direction": "expanding = bullish",
        "regime_bands": [],
        "explanation": (
            "The Bitcoin Layer's AI liquidity supertrend — a macro liquidity regime read. "
            "Expanding liquidity is risk-on (supports MSTR/BTC); contracting is risk-off. Feeds "
            "the SEPARATE macro/liquidity panel, never the core conviction. Fetched headlessly "
            "from a login-gated TBL research page in CI; carries no weight until its live scale "
            "is confirmed and its skill is measured by the calibrator."
        ),
        "use": "A liquidity tailwind/headwind backdrop, not a top/bottom timing signal.",
    },
    "rsi": {
        "label": "BTC RSI-14",
        "category": "Momentum",
        "value_fmt": ".1f",
        "value_suffix": "",
        "direction": "oversold = bullish",
        "regime_bands": [
            {"lo": 0,  "hi": 30,  "label": "Oversold (long)",  "color": "#16c784"},
            {"lo": 30, "hi": 45,  "label": "Weak",             "color": "#7bd88f"},
            {"lo": 45, "hi": 55,  "label": "Neutral",          "color": "#f3c623"},
            {"lo": 55, "hi": 70,  "label": "Strong",           "color": "#f9844a"},
            {"lo": 70, "hi": 100, "label": "Overbought (hedge)","color": "#ea3943"},
        ],
        "explanation": (
            "14-day Relative Strength Index on daily BTC close (Wilder's smoothing) — pure price "
            "momentum. RSI sinks below 30 at capitulation and pushes above 70 at blow-off tops, so "
            "as a signed score it leans long when cold and short when hot. It's the fast transition "
            "read that the slow on-chain value metrics (MVRV, NUPL) structurally lag — a momentum "
            "complement, lightly weighted, not a standalone call."
        ),
        "use": "Oversold (<30) corroborates a long entry; overbought (>70) corroborates a hedge.",
    },
    "slope_5d": {
        "label": "MA200 Slope (structural)",
        "category": "Structural",
        "value_fmt": ".2f",
        "value_suffix": "%",
        "direction": "positive = uptrend (bullish)",
        "regime_bands": [
            {"lo": -6, "hi": -1,  "label": "Downtrend (hedge armed)", "color": "#ea3943"},
            {"lo": -1, "hi": 0,   "label": "Rolling over",            "color": "#f9844a"},
            {"lo": 0,  "hi": 1,   "label": "Turning up",              "color": "#7bd88f"},
            {"lo": 1,  "hi": 6,   "label": "Uptrend",                 "color": "#16c784"},
        ],
        "explanation": (
            "5-trading-day percent slope of MSTR's 200-day moving average — the structural "
            "trend, and v8.5's hedge gate. Negative = structural downtrend, where v8.5 admits "
            "PUT/SHORT hedges. This is the signal that flagged the November-2025 short even "
            "while BTC on-chain looked mid-cycle, and it's why the oscillator tempers a 'buy' "
            "when the trend is still falling. Positive = structural uptrend."
        ),
        "use": (
            "The transition/top catcher. Negative slope pulls net conviction toward sell even "
            "when valuation looks cheap — exactly what kept the model from screaming buy into "
            "the Nov-2025 top before the drop to $112."
        ),
    },
    "mvrv_z": {
        "label": "MVRV Z-Score",
        "category": "Cycle Phase",
        "value_fmt": ".2f",
        "value_suffix": "",
        "direction": "lower = bullish",
        "regime_bands": [
            {"lo": -2, "hi": 0,  "label": "Deep capitulation",   "color": "#2E8B57"},
            {"lo": 0,  "hi": 2,  "label": "Accumulation",        "color": "#90EE90"},
            {"lo": 2,  "hi": 4,  "label": "Belief",              "color": "#F0E68C"},
            {"lo": 4,  "hi": 6,  "label": "Optimism / Late bull","color": "#FF8C00"},
            {"lo": 6,  "hi": 10, "label": "Euphoria / Top zone", "color": "#B22222"},
        ],
        "explanation": (
            "MVRV Z-Score = (Market Cap − Realized Cap) / σ(Market Cap). It measures how far "
            "BTC's market price sits above or below the aggregate cost basis of all coins, "
            "scaled by historical volatility. Historically: above 7 marks cycle tops; below 0 "
            "marks deep bottoms. The bands shown reflect the historical regime mapping. "
            "Current readings near 0–2 are in the accumulation zone — most coins are held "
            "near or below their cost basis."
        ),
        "use": (
            "At a strategy entry signal, MVRV-Z deep in the accumulation band is supportive "
            "(implies the upside path is structurally still ahead). Above 6 should make you "
            "scale size DOWN: the strategy may still fire, but historically you're entering "
            "near a euphoric top."
        ),
    },
    "nupl": {
        "label": "NUPL (Net Unrealized Profit/Loss)",
        "category": "Cycle Phase",
        "value_fmt": ".3f",
        "value_suffix": "",
        "direction": "lower = bullish",
        "regime_bands": [
            {"lo": -0.25, "hi": 0,    "label": "Capitulation",    "color": "#2E8B57"},
            {"lo": 0,     "hi": 0.25, "label": "Hope / Fear",     "color": "#90EE90"},
            {"lo": 0.25,  "hi": 0.5,  "label": "Optimism",        "color": "#F0E68C"},
            {"lo": 0.5,   "hi": 0.75, "label": "Belief",          "color": "#FF8C00"},
            {"lo": 0.75,  "hi": 1,    "label": "Euphoria / Greed","color": "#B22222"},
        ],
        "explanation": (
            "NUPL = (Market Cap − Realized Cap) / Market Cap. Sister metric to MVRV-Z, but "
            "expressed as the proportion of the market in unrealized profit. Range −1 to 1. "
            "Mapped to Glassnode's named bands: Capitulation (<0), Hope/Fear (0–0.25), "
            "Optimism (0.25–0.5), Belief (0.5–0.75), Euphoria (>0.75)."
        ),
        "use": (
            "Cleaner band-mapping than MVRV-Z for cycle-phase narrative. Use as a confirmation "
            "of MVRV: when both agree, the cycle phase read has higher confidence."
        ),
    },
    "sopr": {
        "label": "SOPR (7-day MA)",
        "category": "Cycle Phase",
        "value_fmt": ".4f",
        "value_suffix": "",
        "direction": "lower = bullish for entry",
        "regime_bands": [
            {"lo": 0.90, "hi": 0.97, "label": "Capitulation",            "color": "#2E8B57"},
            {"lo": 0.97, "hi": 1.0,  "label": "Sub-1 reclaim zone",      "color": "#90EE90"},
            {"lo": 1.0,  "hi": 1.02, "label": "Healthy profit-taking",   "color": "#F0E68C"},
            {"lo": 1.02, "hi": 1.05, "label": "Heavy profit realization","color": "#FF8C00"},
            {"lo": 1.05, "hi": 1.15, "label": "Euphoric realization",    "color": "#B22222"},
        ],
        "explanation": (
            "SOPR = ratio of price-at-spend / price-at-acquisition for moved coins. >1 means "
            "the average spend is in profit; <1 means at loss. Sustained <1 = capitulation "
            "phase (holders dumping below cost). A reclaim of 1 after sub-1 period historically "
            "marks the early-bull confirmation. We use the 7-day MA to smooth daily noise."
        ),
        "use": (
            "At entry, SOPR sub-1 or just reclaiming = low risk of being late. SOPR >1.05 = "
            "widespread profit-taking, late-cycle warning."
        ),
    },
    "lth_trend": {
        "label": "Liveliness  (90d Δ%, inverted)",
        "category": "Cycle Phase",
        "value_fmt": "+.2f",
        "value_suffix": "%",
        "direction": "negative % = bullish (LTHs accumulating)",
        "regime_bands": [
            {"lo": -10, "hi": -5,  "label": "Strong LTH accumulation",  "color": "#2E8B57"},
            {"lo": -5,  "hi": -1,  "label": "LTH accumulation",         "color": "#90EE90"},
            {"lo": -1,  "hi": 1,   "label": "Flat",                     "color": "#F0E68C"},
            {"lo": 1,   "hi": 5,   "label": "LTH distribution",         "color": "#FF8C00"},
            {"lo": 5,   "hi": 15,  "label": "Heavy LTH distribution",   "color": "#B22222"},
        ],
        "explanation": (
            "Liveliness = Coin-Days-Destroyed / Cumulative-Coin-Days-Created. Range 0–1. "
            "Rising liveliness = long-term holders (LTHs) are spending old coins. Falling "
            "liveliness = LTHs are sitting tight, accumulating. We show the 90-day percentage "
            "change. NEGATIVE change is bullish (LTHs not distributing). This is a slow-moving, "
            "high-conviction signal — LTHs are smart money. The score function inverts."
        ),
        "use": (
            "Negative 90d Δ% (LTHs accumulating) is one of the strongest pre-bull signals "
            "historically. Sustained positive Δ% is a top warning that the cycle-phase models "
            "may miss until later."
        ),
    },
    "m2_trend": {
        "label": "US M2 (12w Δ%)",
        "category": "Macro Liquidity",
        "value_fmt": "+.2f",
        "value_suffix": "%",
        "direction": "higher = bullish",
        "regime_bands": [
            {"lo": -5, "hi": -1, "label": "Contracting",       "color": "#B22222"},
            {"lo": -1, "hi": 0,  "label": "Mild contraction",  "color": "#FF8C00"},
            {"lo": 0,  "hi": 1,  "label": "Slow expansion",    "color": "#F0E68C"},
            {"lo": 1,  "hi": 2,  "label": "Healthy expansion", "color": "#90EE90"},
            {"lo": 2,  "hi": 10, "label": "Strong expansion",  "color": "#2E8B57"},
        ],
        "explanation": (
            "12-week percent change in US M2 money supply (FRED M2SL). M2 includes "
            "currency + checking + savings + small time deposits. Sustained expansion is "
            "BTC-tailwind on a 12-week lag historically (correlation ~0.65–0.75). Used as "
            "proxy for global liquidity since US M2 leads the global aggregate. "
            "FRED data is monthly with ~6-week lag — useful for cycle context, not tactical."
        ),
        "use": (
            "Positive trend + accelerating = global liquidity wind at BTC's back. Negative "
            "trend during an entry signal is a yellow flag: the strategy can still work, but "
            "the macro tailwind isn't there."
        ),
    },
    "netliq_trend": {
        "label": "US Net Liquidity (4w Δ%)",
        "category": "Macro Liquidity",
        "value_fmt": "+.2f",
        "value_suffix": "%",
        "direction": "higher = bullish",
        "regime_bands": [
            {"lo": -10, "hi": -2, "label": "Heavy contraction", "color": "#B22222"},
            {"lo": -2,  "hi": 0,  "label": "Contracting",       "color": "#FF8C00"},
            {"lo": 0,   "hi": 2,  "label": "Expanding",         "color": "#90EE90"},
            {"lo": 2,   "hi": 10, "label": "Strong expansion",  "color": "#2E8B57"},
        ],
        "explanation": (
            "Net Liquidity = Fed Balance Sheet (WALCL) − Treasury General Account (TGA) − "
            "Reverse Repo (RRPONTSYD). Measures the actual liquidity the Fed is releasing into "
            "the financial system. Strongly correlated with BTC and risk-asset moves 2022–24. "
            "Has weakened post-ETF as flows decouple BTC from pure US monetary plumbing, but "
            "still a clean tactical macro read. 4-week change captures recent direction."
        ),
        "use": (
            "Expanding = risk-on regime supportive of entry. Sharply contracting (TGA refill "
            "or RRP-spike events) = headwind that historically suppresses crypto for weeks."
        ),
    },
    "dxy_trend": {
        "label": "DXY (50d Δ%, inverse)",
        "category": "Macro Liquidity",
        "value_fmt": "+.2f",
        "value_suffix": "%",
        "direction": "lower = bullish",
        "regime_bands": [
            {"lo": -10, "hi": -3, "label": "Hard DXY breakdown",  "color": "#2E8B57"},
            {"lo": -3,  "hi": 0,  "label": "DXY softening",       "color": "#90EE90"},
            {"lo": 0,   "hi": 3,  "label": "DXY strengthening",   "color": "#F0E68C"},
            {"lo": 3,   "hi": 10, "label": "DXY squeezing higher","color": "#B22222"},
        ],
        "explanation": (
            "US Dollar Index, 50-day percent change. BTC and DXY are inversely correlated "
            "(historically −0.5 to −0.7). A breaking-down DXY is liquidity-positive for BTC "
            "and risk assets globally. A ripping DXY is a structural headwind. We invert the "
            "direction in scoring — negative DXY Δ% is bullish."
        ),
        "use": (
            "Confirms or contradicts the M2 / Net Liq read. If DXY is collapsing while macro "
            "liquidity is expanding, that's a clean risk-on macro alignment. If DXY is ripping "
            "while everything else is bullish, expect crypto headwinds even at a signal."
        ),
    },
    "hy_oas": {
        "label": "HY Credit Spread (OAS)",
        "category": "Risk Regime",
        "value_fmt": ".2f",
        "value_suffix": "%",
        "direction": "lower = bullish",
        "regime_bands": [
            {"lo": 0, "hi": 3, "label": "Risk-on / Tight",         "color": "#2E8B57"},
            {"lo": 3, "hi": 4, "label": "Normal",                  "color": "#90EE90"},
            {"lo": 4, "hi": 5, "label": "Widening / Caution",      "color": "#F0E68C"},
            {"lo": 5, "hi": 6, "label": "Stressed",                "color": "#FF8C00"},
            {"lo": 6, "hi": 12,"label": "Crisis / Deleveraging",   "color": "#B22222"},
        ],
        "explanation": (
            "High-Yield Credit Spread (ICE BofA US High Yield Index Option-Adjusted Spread). "
            "Measures the yield premium investors demand for sub-IG corporate bonds vs. "
            "Treasuries. Tight spreads = risk-on appetite, supportive of all risk assets "
            "including BTC. Widening = early sign of deleveraging cycle. BTC has historically "
            "followed risk-asset moves during stress events."
        ),
        "use": (
            "Best single 'risk regime' read on the dashboard. Tight + tightening = clean entry "
            "macro. Wide + widening = the entry signal can still fire but expect deeper drawdown."
        ),
    },
    "real_yield": {
        "label": "10Y Real Yield (TIPS, inverse)",
        "category": "Risk Regime",
        "value_fmt": ".2f",
        "value_suffix": "%",
        "direction": "lower = bullish",
        "regime_bands": [
            {"lo": -2, "hi": 0,   "label": "Negative — bullish",   "color": "#2E8B57"},
            {"lo": 0,  "hi": 1,   "label": "Low positive",         "color": "#90EE90"},
            {"lo": 1,  "hi": 2,   "label": "Neutral",              "color": "#F0E68C"},
            {"lo": 2,  "hi": 2.5, "label": "Restrictive",          "color": "#FF8C00"},
            {"lo": 2.5,"hi": 5,   "label": "Very restrictive",     "color": "#B22222"},
        ],
        "explanation": (
            "10-year Treasury Inflation-Protected Security yield. Real yield = nominal yield − "
            "expected inflation. Negative real yields historically correlate with risk-asset "
            "and gold rallies. High positive real yields = restrictive monetary policy, "
            "headwind for all risk assets. We invert in scoring."
        ),
        "use": (
            "Currently >2% = restrictive. The strategy's macro context is that the Fed can't "
            "cut without losing inflation control. Persistently high real yields are the bear "
            "case for risk-asset multiples — including MSTR's premium to NAV."
        ),
    },
    "mnav": {
        "label": "MSTR mNAV",
        "category": "MSTR-Specific",
        "value_fmt": ".2f",
        "value_suffix": "x",
        "direction": "lower = bullish for entry",
        "regime_bands": [
            {"lo": 0.5, "hi": 1.0, "label": "Structural cheap",    "color": "#2E8B57"},
            {"lo": 1.0, "hi": 1.3, "label": "Compressed",          "color": "#90EE90"},
            {"lo": 1.3, "hi": 1.8, "label": "Fair",                "color": "#F0E68C"},
            {"lo": 1.8, "hi": 2.3, "label": "Premium",             "color": "#FF8C00"},
            {"lo": 2.3, "hi": 4,   "label": "Blowoff / Top zone",  "color": "#B22222"},
        ],
        "explanation": (
            "mNAV = MSTR market cap / (BTC holdings × BTC price). Measures the premium the "
            "market assigns to MSTR's equity above its underlying BTC stack. Historical range "
            "0.8 to 3.5+. Below 1.0 is rare — implies the equity trades at a DISCOUNT to its "
            "BTC. Tier 2a (the strategy's short leg) targets mNAV blowoffs. Tier 1 long "
            "benefits most from entering when mNAV is compressed."
        ),
        "use": (
            "Single most important MSTR-specific dial. mNAV <1.3 = excellent entry zone for "
            "Tier 1. mNAV >2.3 = Tier 2a setup forming. The LEVEL matters more than the 50d "
            "trend below."
        ),
    },
    "mstr_btc_trend": {
        "label": "MSTR / BTC Ratio  (50d Δ%, inverse)",
        "category": "MSTR-Specific",
        "value_fmt": "+.2f",
        "value_suffix": "%",
        "direction": "negative % = bullish (mNAV compressing)",
        "regime_bands": [
            {"lo": -30, "hi": -10, "label": "Strong mNAV compression",  "color": "#2E8B57"},
            {"lo": -10, "hi": 0,   "label": "Mild compression",         "color": "#90EE90"},
            {"lo": 0,   "hi": 10,  "label": "Mild expansion",           "color": "#FF8C00"},
            {"lo": 10,  "hi": 30,  "label": "Blowoff expansion",        "color": "#B22222"},
        ],
        "explanation": (
            "50-day percent change in MSTR price ÷ BTC price ratio. Rising ratio = MSTR "
            "outperforming BTC = mNAV expanding (premium inflating). Falling ratio = MSTR "
            "compressing relative to its BTC stack = better entry zone. The current ratio "
            "level is captured by mNAV above; this card shows the TREND."
        ),
        "use": (
            "Timing kicker on top of mNAV level. mNAV LOW + ratio FALLING = best possible "
            "entry. mNAV LOW + ratio RISING (current state) = level is cheap but momentum "
            "is in the wrong direction; possibly wait or scale in."
        ),
    },
    "funding": {
        "label": "BTC Perp Funding (annualized)",
        "category": "Tactical",
        "value_fmt": "+.2f",
        "value_suffix": "%",
        "direction": "lower / negative = bullish for entry",
        "regime_bands": [
            {"lo": -50, "hi": 0,   "label": "Negative — clean",      "color": "#2E8B57"},
            {"lo": 0,   "hi": 5,   "label": "Cool",                  "color": "#90EE90"},
            {"lo": 5,   "hi": 15,  "label": "Normal",                "color": "#F0E68C"},
            {"lo": 15,  "hi": 30,  "label": "Heated",                "color": "#FF8C00"},
            {"lo": 30,  "hi": 100, "label": "Euphoric / Pre-flush",  "color": "#B22222"},
        ],
        "explanation": (
            "BTC perpetual futures funding rate, annualized (OKX BTC-USDT-SWAP, 8h interval). "
            "Funding is the payment longs make to shorts (positive) or shorts to longs "
            "(negative). Persistently elevated positive funding = leveraged long buildup, "
            "historically precedes squeezes/flushes. Neutral or negative = clean positioning."
        ),
        "use": (
            "Tactical timing read at signal-fire moment. Entering when funding is cool or "
            "negative reduces the odds of being a late long that gets flushed. Funding >30% "
            "annualized = the trade is crowded."
        ),
    },
    "ssr": {
        "label": "Stablecoin Supply Ratio",
        "category": "Tactical",
        "value_fmt": ".2f",
        "value_suffix": "",
        "direction": "lower = bullish (more dry powder)",
        "regime_bands": [
            {"lo": 0,  "hi": 5,   "label": "High dry powder",  "color": "#2E8B57"},
            {"lo": 5,  "hi": 10,  "label": "Balanced",         "color": "#90EE90"},
            {"lo": 10, "hi": 20,  "label": "BTC-heavy",        "color": "#FF8C00"},
            {"lo": 20, "hi": 50,  "label": "Low dry powder",   "color": "#B22222"},
        ],
        "explanation": (
            "SSR = BTC Market Cap / Total Stablecoin Supply (USDT + USDC + DAI). Proxy for "
            "how much capital is sitting on the sidelines in stables vs deployed in BTC. "
            "Low SSR = lots of stablecoin dry powder relative to BTC's size = future buying "
            "capacity. Was the cleanest 2023 bottom indicator."
        ),
        "use": (
            "Slow-moving structural read. Low SSR during an entry signal = there's capital "
            "to deploy into the move. High SSR = stablecoin pool already mostly drained into "
            "BTC, less buying capacity remaining."
        ),
    },
}
