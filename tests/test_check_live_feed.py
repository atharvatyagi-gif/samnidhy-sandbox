"""scripts/check_live_feed.py: the smoke test the owner runs with their own keys. Here it runs against fakes: stages, percentiles, no secrets, no tracebacks."""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_live_feed as cl  # noqa: E402

ENV = {"ANGEL_API_KEY": "KEY-SECRET-123", "ANGEL_CLIENT_CODE": "C1234", "ANGEL_MPIN": "9876", "ANGEL_TOTP_SECRET": "TOTPSECRETXYZ"}
OPEN = datetime(2026, 10, 6, 5, 0, tzinfo=timezone.utc)        # 10:30 IST on a Tuesday
CLOSED = datetime(2026, 10, 4, 5, 0, tzinfo=timezone.utc)      # a Sunday


class Feed:
    def __init__(self, env, on_row, ticks=0, login_error=None, conns=1):
        self.on_row, self.ticks, self.login_error, self.conns = on_row, ticks, login_error, conns
        self.sym_token = {"RELIANCE": ("NSE", "2885"), "TCS": ("NSE", "11536"), "OTHER": ("NSE", "1")}
        self.status = {"symbols": 3, "connections": 0, "last_error": None}
        self.stopped = False

    def prepare(self):
        if self.login_error:
            raise RuntimeError(self.login_error)

    def start(self):
        self.status["connections"] = self.conns
        self.kept = dict(self.sym_token)

    def stop(self):
        self.stopped = True


def out_of(env, feed_kw=None, now=OPEN, seconds=0, importer=None, clock=None, sleep=None, feed_holder=None):
    lines = []
    def factory(env_, on_row):
        f = Feed(env_, on_row, **(feed_kw or {}))
        if feed_holder is not None:
            feed_holder.append(f)
        return f
    code, res = cl.run(env, ["RELIANCE", "TCS", "MISSING"], seconds, feed_factory=factory, importer=importer or (lambda m: None), now=now, sleep=sleep or (lambda s: None), out=lines.append, **({"clock": clock} if clock else {}))
    return code, res, "\n".join(lines)


def test_no_keys_is_a_clear_message_and_a_nonzero_exit_without_a_traceback(capsys):
    code, res, text = out_of({})
    assert code == 2 and res == [False] and "keys missing" in text and "ANGEL_API_KEY" in text and "Traceback" not in text
    assert "ANGEL_API_KEY: missing" in text


def test_main_with_no_keys_exits_nonzero_cleanly(monkeypatch, capsys):
    import aladin_env
    monkeypatch.setattr(aladin_env, "load_env", lambda *a, **k: None)            # never read the real .env in a test
    for k in ENV:
        monkeypatch.delenv(k, raising=False)
    assert cl.main(["--seconds", "0"]) == 2
    o = capsys.readouterr().out
    assert "KEYS MISSING" in o and "Traceback" not in o


def test_keys_are_reported_as_set_or_missing_and_no_value_is_ever_printed():
    code, res, text = out_of(ENV, now=CLOSED)
    for secret in ("KEY-SECRET-123", "9876", "TOTPSECRETXYZ", "C1234"):
        assert secret not in text
    assert "ANGEL_API_KEY: set" in text and "ANGEL_MPIN: set" in text


def test_a_refused_login_fails_that_stage_with_the_reason_and_stops():
    code, res, text = out_of(ENV, {"login_error": "Angel One refused the login: Invalid totp"})
    assert code == 1 and "FAIL  login" in text and "Invalid totp" in text and "feed" not in text.split("login")[-1]


def test_a_missing_package_is_named():
    def importer(m):
        if m == "pyotp":
            raise ImportError("no pyotp", name="pyotp")
    code, res, text = out_of(ENV, importer=importer)
    assert code == 1 and "FAIL  packages" in text and "pyotp" in text and "requirements-angel.txt" in text


def test_closed_market_skips_the_ticks_stage_but_login_and_connection_pass():
    code, res, text = out_of(ENV, now=CLOSED)
    assert code == 0 and "PASS  login" in text and "PASS  feed" in text and "SKIP  ticks" in text and "market closed" in text
    assert "not in the instrument list: MISSING" in text


def test_open_market_with_no_ticks_is_a_failure():
    code, res, text = out_of(ENV, now=OPEN)
    assert code == 1 and "FAIL  ticks" in text and "no price arrived" in text


def test_no_connection_is_a_failure_with_the_feeds_last_error():
    holder = []
    code, res, text = out_of(ENV, {"conns": 0}, feed_holder=holder)
    assert code == 1 and "FAIL  feed" in text and "no connection opened" in text and holder[0].stopped


def test_ticks_give_counts_delay_percentiles_and_gaps():
    t = [1_000_000.0]
    holder = []

    def clock():
        return t[0]

    def sleep(s):
        t[0] += s
        if s == 0.5 or holder and not getattr(holder[0], "fed", False) and holder[0].status["connections"]:
            pass
    lines = []
    def factory(env_, on_row):
        f = Feed(env_, on_row)
        holder.append(f)
        return f
    f_holder = holder
    # feed three ticks per symbol with known exchange times: delay 0.2 s, 0.4 s, 1.0 s
    orig_start = Feed.start
    def start(self):
        orig_start(self)
        for i, d in enumerate((200, 400, 1000)):
            t[0] += 1
            self.on_row("RELIANCE", [100, 100, 100, 100, 100, 1, int(t[0] * 1000 - d)])
            t[0] += 1
            self.on_row("TCS", [100, 100, 100, 100, 100, 1, int(t[0] * 1000 - d)])
    Feed.start = start
    try:
        code, res = cl.run(ENV, ["RELIANCE", "TCS"], 0, feed_factory=factory, importer=lambda m: None, now=OPEN, clock=clock, sleep=lambda s: None, out=lines.append)
    finally:
        Feed.start = orig_start
    text = "\n".join(lines)
    assert code == 0 and "PASS  ticks" in text and "6 ticks (RELIANCE 3, TCS 3)" in text
    assert "p50 0.40 s" in text and "p95 1.00 s" in text and "max 1.00 s" in text and "gap between ticks" in text


def test_percentile_helper():
    assert cl.pct([], 50) is None and cl.pct([1, 2, 3, 4], 50) == 2 and cl.pct([1, 2, 3, 4], 95) == 4
