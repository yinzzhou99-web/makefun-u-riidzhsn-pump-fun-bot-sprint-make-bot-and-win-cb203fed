"""Pump.fun Bot Sprint: momentum rider on the agent-fun/replay/v2 replay.

Stdlib only. The harness speaks hello / batch / done on stdin/stdout; this bot
reads each batch of market events as it arrives and answers with orders.

Strategy, from the dev window's own shape: most coins round-trip back to ~1x,
but runners jump fast (median 1.6x by their 3rd trade) and grind to a peak
around trade 50. So: buy early strength only (price 1.2-1.9x its create price,
buy-dominated flow, still young), build up to ~0.20 SOL per coin in small
batches capped at 1% of real reserves, then exit fast: half at +40%, the rest
at +80% or on a 12% trailing stop, hard stop at -15%, stall exit after 600
slots. At most 5 open positions, so slots turn over quickly and the bot can
cover the 20-coin round-trip guardrail. No clock, no randomness, no network:
the same replay gives the same orders, byte for byte.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bot

LAMPORTS_PER_SOL = makefun_bot.LAMPORTS_PER_SOL


def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


# --- tuning knobs (set from the dev-window analysis; defaults are the best
# driver-graded set: early momentum, small size, creator-dump exit) ---
TARGET_PER_COIN = _env_int("BOT_TARGET_PER_COIN", 100_000_000)   # 0.10 SOL total per coin
BUY_PER_REPLY = _env_int("BOT_BUY_PER_REPLY", 30_000_000)        # 0.03 SOL max in one reply per coin
MIN_RATIO = _env_float("BOT_MIN_RATIO", 1.15)                     # enter at >= this x create price
MAX_RATIO = _env_float("BOT_MAX_RATIO", 1.45)                     # never chase above this x create price
MAX_TRADES_ENTRY = _env_int("BOT_MAX_TRADES_ENTRY", 6)            # only young coins
BUY_VOL_RATIO = _env_float("BOT_BUY_VOL_RATIO", 1.0)              # buy vol must exceed sell vol by this
TAKE_HALF = _env_float("BOT_TAKE_HALF", 1.35)                     # sell half at this x entry
TAKE_REST = _env_float("BOT_TAKE_REST", 1.70)                     # sell rest at this x entry
TRAIL_START = _env_float("BOT_TRAIL_START", 1.20)                 # trailing stop arms at this x entry
TRAIL_DROP = _env_float("BOT_TRAIL_DROP", 0.12)                   # sell all this far below peak since entry
STOP_LOSS = _env_float("BOT_STOP_LOSS", 0.85)                     # hard stop at this x entry
STALL_SLOTS = _env_int("BOT_STALL_SLOTS", 250)                    # exit a flat position after this many slots
MAX_NEW_PER_BATCH = 2                # at most 2 fresh entries per batch
SLIPPAGE_BPS = 2000                  # 20%: fills resolve 2 slots later, prices move
CASH_BUFFER = 500_000_000            # keep 0.5 SOL uncommitted
CAP_MARGIN = 0.90                    # buy at most 90% of the size cap: the engine's
                                     # decision-time reserves are shifted by our own
                                     # fills, which the bot-visible curve does not show
SORT_EARLIEST = os.environ.get("BOT_SORT", "early") == "early"
                                     # rank entry candidates youngest/earliest first:
                                     # sorting by highest ratio buys the top, and the
                                     # top is where the move is already over


class Coin:
    __slots__ = ("p0", "trades", "buy_vol", "sell_vol", "last_slot", "creator", "creator_dumped")

    def __init__(self, p0, creator=None):
        self.p0 = p0
        self.trades = 0
        self.buy_vol = 0
        self.sell_vol = 0
        self.last_slot = -1
        self.creator = creator
        self.creator_dumped = False


class Position:
    __slots__ = ("tokens", "spent", "peak", "half_sold", "born_slot")

    def __init__(self, born_slot):
        self.tokens = 0
        self.spent = 0          # lamports paid (curve quote + fees) for tokens held
        self.peak = 0.0         # best price/entry ratio seen since entry
        self.half_sold = False
        self.born_slot = born_slot


coins = {}       # mint -> Coin
positions = {}   # mint -> Position (mirrors fills; engine account is the truth)
offset_dq = {}   # mint -> net quote lamports our fills put into the curve
                 # (the engine's decision-time reserves are the recorded ones
                 # shifted by this; the bot-visible curve shows unshifted)
sell_cap = {}    # mint -> max tokens per sell order: a sell the engine rejects
                 # for size pays out more than the curve's real reserves, so a
                 # smaller sell is the only way out of a rugged coin
last_sell = {}   # mint -> tokens of the most recent sell order sent


def price_of(curve):
    vt = curve.virtual_token_reserves
    if vt <= 0:
        return 0.0
    return curve.virtual_quote_reserves / vt


def on_hello(state):
    coins.clear()
    positions.clear()
    offset_dq.clear()
    sell_cap.clear()
    last_sell.clear()


def on_batch(state, batch):
    slot = batch["slot"]
    # --- fold this batch's events into per-coin stats ---
    for e in batch["events"]:
        kind = e["event"]
        mint = e["mint"]
        if kind == "CreateEvent":
            vq = int(e["virtual_quote_reserves"])
            vt = int(e["virtual_token_reserves"])
            if vt > 0 and mint not in coins:
                coins[mint] = Coin(vq / vt, e.get("creator"))
            elif mint in coins and coins[mint].creator is None:
                coins[mint].creator = e.get("creator")
        elif kind == "TradeEvent":
            c = coins.get(mint)
            if c is None:
                vq = int(e["virtual_quote_reserves"])
                vt = int(e["virtual_token_reserves"])
                if vt <= 0:
                    continue
                c = Coin(vq / vt)
                coins[mint] = c
            c.trades += 1
            c.last_slot = slot
            if e.get("is_buy"):
                c.buy_vol += int(e["sol_amount"])
            else:
                c.sell_vol += int(e["sol_amount"])
            # the creator selling is the rug signal: on this window the price
            # never again exceeds the creator's sell price (median), and ends
            # 25% below it, so exit at once and never enter afterwards
            if (c.creator is not None and e.get("user") == c.creator
                    and not e.get("is_buy") and int(e["sol_amount"]) >= 50_000_000):
                c.creator_dumped = True
        elif kind == "CompleteEvent":
            coins.pop(mint, None)
            positions.pop(mint, None)

    # --- fold fills: what actually landed ---
    for f in batch["fills"]:
        mint = f["mint"]
        if f["status"] == "rejected" and f["side"] == "sell":
            # the payout exceeded the curve's real reserves: halve the next try
            prev = last_sell.get(mint)
            if prev:
                sell_cap[mint] = max(1, prev // 2)
            continue
        if f["status"] != "filled":
            continue
        if f["side"] == "buy":
            pos = positions.get(mint)
            if pos is None:
                pos = Position(slot)
                positions[mint] = pos
            pos.tokens += int(f["token_amount"])
            pos.spent += int(f["quote_lamports"])
            offset_dq[mint] = offset_dq.get(mint, 0) + int(f["quote_lamports"])
        else:
            offset_dq[mint] = offset_dq.get(mint, 0) - int(f["quote_lamports"])
            sell_cap.pop(mint, None)
            pos = positions.get(mint)
            if pos is not None:
                sold = int(f["token_amount"])
                if pos.tokens > 0:
                    pos.spent = pos.spent * (pos.tokens - sold) // pos.tokens
                pos.tokens -= sold
                if pos.tokens <= 0:
                    positions.pop(mint, None)

    # orders sent in earlier batches, not yet reported: never double-spend them
    inflight_buy = {}
    inflight_sell = {}
    for p in state.pending.values():
        o = p.order
        if o["side"] == "buy":
            inflight_buy[o["mint"]] = inflight_buy.get(o["mint"], 0) + int(o["quote_lamports"])
        else:
            inflight_sell[o["mint"]] = inflight_sell.get(o["mint"], 0) + int(o["token_amount"])

    orders = []
    # --- exits first: free the 5 position slots ---
    for mint in sorted(positions):
        pos = positions[mint]
        curve = state.curves.get(mint)
        holding = state.positions.get(mint)
        if curve is None or holding is None or holding.token_amount <= 0:
            continue
        entry = pos.spent / pos.tokens if pos.tokens > 0 else 0.0
        if entry <= 0:
            continue
        price = price_of(curve)
        ratio = price / entry
        if ratio > pos.peak:
            pos.peak = ratio
        # tokens already being sold: never sell the same tokens twice
        free_tokens = holding.token_amount - inflight_sell.get(mint, 0)
        if free_tokens <= 0:
            continue
        sell = None
        if coins.get(mint) is not None and coins[mint].creator_dumped:
            sell = free_tokens
        elif ratio <= STOP_LOSS:
            sell = free_tokens
        elif not pos.half_sold and ratio >= TAKE_HALF:
            sell = free_tokens // 2
            pos.half_sold = True
        elif pos.half_sold and ratio >= TAKE_REST:
            sell = free_tokens
        elif pos.peak >= TRAIL_START and ratio <= pos.peak * (1.0 - TRAIL_DROP):
            sell = free_tokens
        elif slot - pos.born_slot >= STALL_SLOTS and ratio < 1.10:
            sell = free_tokens
        if sell and sell > 0:
            if mint in sell_cap:
                sell = min(sell, sell_cap[mint])
            if sell > 0:
                orders.append({"side": "sell", "mint": mint, "token_amount": sell,
                               "max_slippage_bps": SLIPPAGE_BPS})
                last_sell[mint] = sell

    # --- entries: strongest young momentum first ---
    committed = state.committed_position_count()
    free_cash = state.free_cash_lamports()
    if committed < state.hello["caps"]["max_open_positions"] and free_cash > CASH_BUFFER:
        candidates = []
        for mint, c in coins.items():
            if c.trades < 1 or c.trades > MAX_TRADES_ENTRY:
                continue
            if c.creator_dumped:
                continue
            if mint in positions or mint in inflight_buy:
                continue
            curve = state.curves.get(mint)
            if curve is None or curve.complete:
                continue
            price = price_of(curve)
            ratio = price / c.p0 if c.p0 > 0 else 0.0
            if ratio < MIN_RATIO or ratio > MAX_RATIO:
                continue
            if c.buy_vol <= c.sell_vol * BUY_VOL_RATIO:
                continue
            candidates.append((c.trades, ratio, c.buy_vol, mint))
        if SORT_EARLIEST:
            candidates.sort()
        else:
            candidates.sort(key=lambda t: (-t[1], -t[2]))
        for _trades, _ratio, _vol, mint in candidates[:MAX_NEW_PER_BATCH]:
            if state.committed_position_count() >= state.hello["caps"]["max_open_positions"]:
                break
            curve = state.curves[mint]
            # the engine caps buys at 1% of decision-time real reserves, and
            # those reserves are shifted by our own fills (offset_dq); the
            # bot-visible curve shows them unshifted, so correct for it
            shifted_rq = curve.real_quote_reserves + offset_dq.get(mint, 0)
            shifted_cap = max(0, shifted_rq * state.hello["caps"]["max_order_bps_of_real_reserve"] // 10000)
            cap = int(min(state.max_buy_lamports(mint), shifted_cap) * CAP_MARGIN)
            if cap <= 0:
                continue
            held = positions.get(mint)
            already = (held.spent if held else 0) + inflight_buy.get(mint, 0)
            room = TARGET_PER_COIN - already
            if room <= 0:
                continue
            amount = min(cap, BUY_PER_REPLY, room, free_cash - CASH_BUFFER)
            if amount < 10_000_000:  # below the 0.01 SOL round-trip bar
                continue
            orders.append({"side": "buy", "mint": mint, "quote_lamports": amount,
                           "max_slippage_bps": SLIPPAGE_BPS})
            free_cash -= amount

    return orders


def on_done(state, done):
    return None


makefun_bot.run(on_batch, on_hello=on_hello, on_done=on_done)
