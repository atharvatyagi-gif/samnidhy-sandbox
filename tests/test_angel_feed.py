"""Angel One source: identical to relay/relay.py on the same input (parity), secrets never leak, login failures fall back to the free feed, focus symbols are faster."""
import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import angel_feed as af  # noqa: E402
import aladin_ticker_daemon as dm  # noqa: E402

ENV = {"ANGEL_API_KEY": "KEY-123", "ANGEL_CLIENT_CODE": "C1234", "ANGEL_MPIN": "9876", "ANGEL_TOTP_SECRET": "JBSWY3DPEHPK3PXP"}
SECRETS = list(ENV.values())


def master_rows(n_stocks=2500):
    rows = [{"exch_seg": "NSE", "symbol": f"STK{i:04d}-EQ", "token": str(1000 + i), "instrumenttype": ""} for i in range(n_stocks)]
    rows += [{"exch_seg": "NSE", "symbol": "STK0001-BE", "token": "9001", "instrumenttype": ""},           # a second series of the same stock: -EQ wins
            {"exch_seg": "NSE", "symbol": "BEONLY-BE", "token": "9002", "instrumenttype": ""},            # only a -BE listing: kept
            {"exch_seg": "NSE", "symbol": "NIFTY25OCTFUT", "token": "9003", "instrumenttype": "FUTIDX"},      # a derivative: ignored
            {"exch_seg": "BSE", "symbol": "BSESTK-EQ", "token": "9004", "instrumenttype": ""},              # not NSE: ignored
            {"exch_seg": "NSE", "symbol": "ODD", "token": "9005", "instrumenttype": ""}]                    # no recognised series: ignored
    return rows


@pytest.fixture
def relay(monkeypatch):
    """relay/relay.py imported with its Angel One / Firebase libraries stubbed (it needs a server and keys to run for real)."""
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    pyotp = types.ModuleType("pyotp")
    pyotp.TOTP = lambda s: types.SimpleNamespace(now=lambda: "123456")
    smart = types.ModuleType("SmartApi")
    smart.SmartConnect = object
    sws = types.ModuleType("SmartApi.smartWebSocketV2")
    sws.SmartWebSocketV2 = object
    for name, mod in (("pyotp", pyotp), ("SmartApi", smart), ("SmartApi.smartWebSocketV2", sws)):
        monkeypatch.setitem(sys.modules, name, mod)
    spec = importlib.util.spec_from_file_location("relay_under_test", ROOT / "relay" / "relay.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- parity with the relay
def test_instrument_master_parsing_matches_the_relay(relay, monkeypatch):
    rows = master_rows(40)
    monkeypatch.setattr(relay.requests, "get", lambda *a, **k: types.SimpleNamespace(json=lambda: rows))
    relay.SYM_TOKEN.clear()
    relay.load_master()
    mine, mine_ts = af.parse_master(rows)
    assert mine == relay.SYM_TOKEN and mine_ts == relay.TOKEN_SYM
    assert mine["STK0001"] == ("NSE", "1001") and mine["BEONLY"] == ("NSE", "9002") and "NIFTY25OCTFUT" not in mine and "BSESTK" not in mine and "ODD" not in mine
    assert mine["^NSEI"] == ("NSE", "99926000") and mine["^BSESN"] == ("BSE", "99919000")


MSGS = [
    {"token": "1001", "exchange_type": 1, "last_traded_price": 123450, "open_price_of_the_day": 120000, "high_price_of_the_day": 125000, "low_price_of_the_day": 119000,
     "closed_price": 121000, "volume_trade_for_the_day": 5500, "exchange_timestamp": 1790000000000},
    {"token": "1002", "exchange_type": 1, "last_traded_price": 0, "volume_trade_for_the_day": 10},                  # a zero price: dropped
    {"token": "424242", "exchange_type": 1, "last_traded_price": 100},                                              # a token we do not know
    {"token": "99919000", "exchange_type": 3, "last_traded_price": 8123456, "closed_price": 8000000},               # the SENSEX, on the BSE
    {"token": "1003", "exchange_type": 1, "last_traded_price": 5000, "volume_trade_for_the_day": None, "exchange_timestamp": None},
    {"token": "1004"},                                                                                              # no price at all
    {"exchange_type": 1},                                                                                           # no token at all
]


def test_tick_conversion_matches_the_relay_message_by_message(relay):
    sym_token, token_sym = af.parse_master(master_rows(40))
    relay.TOKEN_SYM.clear()
    relay.TOKEN_SYM.update(token_sym)
    for m in MSGS:
        relay.QUOTES.clear()
        relay.DIRTY.clear()
        relay.on_tick(m)
        mine = af.tick_row(m, token_sym)
        if mine is None:
            assert relay.QUOTES == {} and relay.DIRTY == set(), m
        else:
            assert relay.QUOTES == {mine[0]: mine[1]} and relay.DIRTY == {mine[0]}, m
    assert af.tick_row(MSGS[0], token_sym) == ("STK0001", [1234.5, 1200.0, 1250.0, 1190.0, 1210.0, 5500, 1790000000000])
    assert af.tick_row(MSGS[3], token_sym) == ("^BSESN", [81234.56, 0.0, 0.0, 0.0, 80000.0, 0, 0])


@pytest.mark.parametrize("n_stocks", [10, 996, 2500, 3200])
def test_connection_grouping_matches_the_relay(relay, monkeypatch, n_stocks):
    rows = master_rows(n_stocks)
    sym_token, _ = af.parse_master(rows)
    captured = []

    class FakeThread:
        def __init__(self, target=None, args=(), daemon=None):
            captured.append(args)

        def start(self):
            pass
    monkeypatch.setattr(relay.threading, "Thread", FakeThread)
    relay.SYM_TOKEN.clear()
    relay.SYM_TOKEN.update(sym_token)
    relay.start_feeds()
    groups, left = af.token_groups(sym_token)
    assert [list(g) for _, g in captured] == [list(g) for g in groups] and [i for i, _ in captured] == list(range(len(groups)))
    assert len(groups) <= 3 and all(sum(len(x["tokens"]) for x in g) <= 1000 for g in groups)
    assert left == max(0, len(sym_token) - 3000)


def test_constants_match_the_relay(relay):
    assert (af.MASTER_URL, af.SERIES, af.INDEXES, af.EXCH_TYPE, af.PER_CONN) == (relay.MASTER_URL, relay.SERIES, relay.INDEXES, relay.EXCH_TYPE, relay.PER_CONN)


# ---------------------------------------------------------------- login and secrets
class FakeApi:
    def __init__(self, result):
        self.result, self.calls = result, []

    def generateSession(self, client, mpin, totp):
        self.calls.append((client, mpin, totp))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def getfeedToken(self):
        return "FEEDTOK"


def feed_with(api, rows=None, env=None, **kw):
    return af.AngelFeed(ENV if env is None else env, lambda s, r: None, http_get=lambda *a, **k: types.SimpleNamespace(json=lambda: rows or master_rows(20)),
                        smart_connect=lambda api_key: api, totp=lambda secret: "654321", **kw)


def test_prepare_logs_in_with_the_totp_and_loads_the_master():
    api = FakeApi({"status": True, "data": {"jwtToken": "JWT"}})
    f = feed_with(api)
    f.prepare()
    assert api.calls == [("C1234", "9876", "654321")] and f.session == {"jwt": "JWT", "feed": "FEEDTOK"} and f.status["symbols"] == 21 and f.status["login_at"]


@pytest.mark.parametrize("result", [{"status": False, "message": "Invalid MPIN 9876"}, None, RuntimeError("boom 9876 KEY-123 JBSWY3DPEHPK3PXP")])
def test_a_failed_login_raises_a_message_without_any_secret(result):
    f = feed_with(FakeApi(result))
    with pytest.raises(RuntimeError) as e:
        f.prepare()
    text = str(e.value)
    assert text and all(s not in text for s in SECRETS if s != "9876") or "Angel One refused the login" in text      # the broker's own message is shown; our code adds none
    for s in ("KEY-123", "JBSWY3DPEHPK3PXP", "C1234", "654321"):
        assert s not in text


def test_missing_settings_are_named_never_their_values():
    assert af.missing_env({}) == list(af.REQUIRED_ENV)
    assert af.missing_env({**ENV, "ANGEL_MPIN": "  "}) == ["ANGEL_MPIN"] and af.missing_env(ENV) == []
    f = feed_with(FakeApi({}), env={"ANGEL_API_KEY": "k"})
    with pytest.raises(RuntimeError, match="ANGEL_CLIENT_CODE"):
        f.prepare()


def test_an_unreadable_instrument_list_is_reported_without_details_of_the_request():
    f = af.AngelFeed(ENV, lambda s, r: None, http_get=lambda *a, **k: (_ for _ in ()).throw(ConnectionError("https://secret-url?token=KEY-123")), smart_connect=lambda api_key: FakeApi({}), totp=lambda s: "1")
    with pytest.raises(RuntimeError) as e:
        f.prepare()
    assert "ConnectionError" in str(e.value) and "KEY-123" not in str(e.value) and "secret-url" not in str(e.value)


def test_feed_hands_usable_ticks_on_and_counts_them():
    got = []
    f = af.AngelFeed(ENV, lambda s, r: got.append((s, r)))
    f.token_sym = {"NSE:1": "AAA"}
    f._on_data({"token": "1", "exchange_type": 1, "last_traded_price": 1000})
    f._on_data({"token": "2", "exchange_type": 1, "last_traded_price": 1000})
    f._on_data({"token": "1", "last_traded_price": 0})
    assert got == [("AAA", [10.0, 0.0, 0.0, 0.0, 0.0, 0, 0])] and f.status["ticks"] == 1


def test_connections_use_the_subscription_shape_the_relay_uses_and_reconnect_forever():
    events = []

    class WS:
        def __init__(self, jwt, key, client, feed, max_retry_attempt=3):
            events.append(("new", jwt, key, client, feed, max_retry_attempt))

        def subscribe(self, cid, mode, groups):
            events.append(("sub", cid, mode, groups))

        def connect(self):
            self.on_open(self)
            self.on_data(self, {"token": "1", "exchange_type": 1, "last_traded_price": 500})
            raise ConnectionError("dropped")
    got = []
    f = af.AngelFeed(ENV, lambda s, r: got.append(s), ws_cls=WS)
    f.token_sym, f.session = {"NSE:1": "AAA"}, {"jwt": "J", "feed": "F"}
    calls = []

    def sleep(s):
        calls.append(s)
        if len(calls) >= 2:
            f.stop()
    f.sleep = sleep
    f._run_conn(0, [{"exchangeType": 1, "tokens": ["1"]}])
    assert events[0] == ("new", "J", "KEY-123", "C1234", "F", 3) and events[1] == ("sub", "blab0", 2, [{"exchangeType": 1, "tokens": ["1"]}])
    assert got == ["AAA", "AAA"] and calls == [5, 5] and f.status["last_error"] == "feed 0 stopped: ConnectionError"


# ---------------------------------------------------------------- the daemon's source
class FakeFeed:
    def __init__(self):
        self.status, self.started, self.stopped = {"feed": "live"}, False, False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def prepare(self):
        pass


class FakeHub:
    def __init__(self):
        self.calls, self.src_name, self.src_status = [], None, None

    def on_tick(self, sym, ltp, o, h, l, pc, vol, ts, kind):
        self.calls.append((sym, ltp, kind))


def test_focus_symbols_are_applied_every_cycle_and_the_rest_once_a_second():
    src = dm.AngelSource(feed=FakeFeed())
    src.set_focus(["AAA"])
    hub, rounds, stop = FakeHub(), [], None

    async def go():
        nonlocal stop
        stop = asyncio.Event()
        n = 0

        async def broadcast():
            nonlocal n
            n += 1
            rounds.append(list(hub.calls))
            if n == 1:
                src.q.put(("AAA", [1, 1, 1, 1, 1, 1, 1])); src.q.put(("BBB", [2, 2, 2, 2, 2, 2, 2])); src.q.put(("^NSEI", [3, 3, 3, 3, 3, 3, 3]))
            if n >= 6:
                stop.set()
        await src.run(hub, broadcast, stop, fast=0.01, slow=0.05)
    asyncio.run(go())
    kinds = {c[0]: c[2] for c in hub.calls}
    assert kinds == {"AAA": "stock", "BBB": "stock", "^NSEI": "index"} and src.feed.started and src.feed.stopped
    first_aaa = next(i for i, r in enumerate(rounds) if any(c[0] == "AAA" for c in r))
    first_bbb = next(i for i, r in enumerate(rounds) if any(c[0] == "BBB" for c in r))
    assert first_aaa < first_bbb or first_aaa == first_bbb                                # the focus symbol is never slower than the others
    assert hub.src_name == "angel" and hub.src_status["source"] == "angel"


def test_newest_tick_per_symbol_wins():
    src = dm.AngelSource(feed=FakeFeed())
    hub = FakeHub()

    async def go():
        stop = asyncio.Event()
        src.q.put(("AAA", [1, 1, 1, 1, 1, 1, 1])); src.q.put(("AAA", [9, 1, 1, 1, 1, 1, 1]))

        async def broadcast():
            stop.set()
        await src.run(hub, broadcast, stop, fast=0.01, slow=0.0)
    asyncio.run(go())
    assert hub.calls == [("AAA", 9, "stock")]


def run_main(monkeypatch, argv, env, prepare=None):
    captured = {}

    async def fake_serve(hub, source, port, **kw):
        captured["source"], captured["hub"] = source, hub
    monkeypatch.setattr(dm, "serve", fake_serve)
    for k in list(ENV):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(dm, "NseSession", lambda *a, **k: types.SimpleNamespace(status={"ok": True, "heals": 0}))
    if prepare is not None:
        monkeypatch.setattr(af.AngelFeed, "prepare", prepare)
    import aladin_env
    monkeypatch.setattr(aladin_env, "load_env", lambda *a, **k: None)
    monkeypatch.setattr(aladin_env, "announce", lambda *a, **k: None)
    assert dm.main(argv) == 0
    return captured


def test_without_keys_the_daemon_uses_the_free_feed_and_says_nothing_about_angel(monkeypatch, capsys):
    c = run_main(monkeypatch, [], {})
    assert c["source"].name == "nse-web" and "Angel" not in capsys.readouterr().out and "note" not in vars(c["source"])


def test_with_keys_and_a_working_login_the_angel_source_is_used(monkeypatch, capsys):
    c = run_main(monkeypatch, [], ENV, prepare=lambda self: None)
    assert c["source"].name == "angel" and c["hub"].src_name == "angel" and "source angel" in capsys.readouterr().out


def test_a_failed_login_falls_back_to_the_free_feed_and_the_reason_reaches_health(monkeypatch, capsys):
    def boom(self):
        raise RuntimeError("Angel One refused the login: Invalid totp")
    c = run_main(monkeypatch, ["--source", "angel"], ENV, prepare=boom)
    src = c["source"]
    assert src.name == "nse-web" and src.status["fallback_from"] == "angel" and "Invalid totp" in src.status["reason"]
    out = capsys.readouterr().out
    assert "using the free NSE web feed" in out and all(s not in out for s in ("KEY-123", "JBSWY3DPEHPK3PXP"))
    c["hub"].src_status = None
    assert dm.health_json(c["hub"], src, set(), 8787)["session"]["fallback_from"] == "angel"            # what /health shows


def test_explicitly_asking_for_angel_without_keys_names_the_missing_settings_and_falls_back(monkeypatch, capsys):
    c = run_main(monkeypatch, ["--source", "angel"], {"ANGEL_API_KEY": "only-this"})
    out = capsys.readouterr().out
    assert c["source"].name == "nse-web" and "missing ANGEL_CLIENT_CODE, ANGEL_MPIN, ANGEL_TOTP_SECRET" in out and "only-this" not in out


def test_the_optional_requirements_match_the_relays():
    a = (ROOT / "requirements-angel.txt").read_text(encoding="utf-8")
    r = (ROOT / "relay" / "requirements.txt").read_text(encoding="utf-8")
    for lib in ("smartapi-python", "pyotp", "websocket-client", "logzero"):
        assert lib in a and lib in r
