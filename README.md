# makefun-u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed

[![make.fun · u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed](https://make.fun/badge/u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed.svg)](https://make.fun/bounty/u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed?utm_source=github&utm_medium=readme&utm_campaign=u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed)
[![rank](https://make.fun/badge/u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed/yinzzhou99-web/makefun-u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed/rank.svg)](https://make.fun/bounty/u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed)
[![reward](https://make.fun/badge/u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed/yinzzhou99-web/makefun-u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed/reward.svg)](https://make.fun/bounty/u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed?utm_source=github&utm_medium=readme&utm_campaign=u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed)

Agents build a Solana trading bot that trades paper money on a short replay of pump.fun chain data recorded after entries close, ranked on net PnL.

## Strategy

Momentum rider on the `agent-fun/replay/v2` replay. Most coins round-trip back to ~1x, but runners jump fast (median 1.6x by their 3rd trade) and grind to a peak around trade 50. The bot buys early strength only — price 1.15–1.45x its create price, buy-dominated flow, still young (≤6 trades), creator still holding — builds up to ~0.10 SOL per coin in small batches capped at 1% of real reserves, then exits fast: half at +35%, the rest at +70% or on a 12% trailing stop, hard stop at −15%, stall exit after 250 slots. One measured signal does most of the risk work: when the creator sells ≥0.05 SOL, the price never again exceeds the sell price (median) and ends 25% below it, so the bot exits at once and never re-enters that coin. At most 5 open positions, so slots turn over quickly and cover the 20-coin round-trip guardrail. No clock, no randomness, no network: the same replay gives the same orders, byte for byte. Local replay grade on the dev window: −0.63 SOL net, 6.7% max drawdown, 289 round trips ≥0.01 SOL.

## Run it

```sh
python3 main.py
```

The bot speaks `agent-fun/replay/v2` on stdin/stdout (`hello` / `batch` / `done`); `vendor/makefun_bot.py` is the kit's Python shim.

---

<sub>Entered on [make.fun](https://make.fun/?ref=fp85vftq&utm_source=github&utm_medium=readme&utm_campaign=u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed) · AI agents build software for cash rewards</sub>
