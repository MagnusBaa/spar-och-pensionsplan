# -*- coding: utf-8 -*-
"""Utdelningskalkyl. Egna köp är grundbeloppet. Aktier köpta för utdelning är gratis."""

import contextvars
import json
import os
import sys
import threading
import time
import uuid
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen

COURTAGE = 0.0025
COURTAGE_MIN = 1.0


def courtage(amount):
    value = float(amount or 0)
    if value <= 0:
        return 0.0
    return round(max(value * COURTAGE, COURTAGE_MIN), 2)


def kassa_delta(kind, shares, price):
    """Hur kontantkassan ändras. Egna köp drar, försäljning av betalda aktier lägger till."""
    net = round(float(shares) * float(price), 2)
    fee = courtage(net)
    if kind == "own":
        return round(-(net + fee), 2)
    if kind == "sell_own":
        return round(net - fee, 2)
    return 0.0


def forsaljning_netto(kind, shares, price) -> float:
    """Det en försäljning ger efter courtage."""
    if kind not in ("sell_own", "sell_free"):
        return 0.0
    net = round(float(shares or 0) * float(price or 0), 2)
    return round(net - courtage(net), 2)


def _resultat_per_rad(stock) -> dict[int, float]:
    """Vinst eller förlust för varje försäljningsrad, i köpordning."""
    paid = 0.0
    free = 0.0
    base = 0.0
    resultat: dict[int, float] = {}
    for index, buy in enumerate((stock or {}).get("buys") or []):
        shares = float(buy.get("shares") or 0)
        kind = buy.get("kind")
        if kind == "own":
            paid += shares
            cost = shares * float(buy.get("price") or 0)
            base += cost + courtage(cost)
        elif kind == "sell_own":
            if paid <= 0 or shares <= 0:
                paid -= shares
                continue
            antal = min(shares, paid)
            bort = base * (antal / paid)
            betalt = forsaljning_netto("sell_own", antal, buy.get("price") or 0)
            resultat[index] = round(betalt - bort, 2)
            base -= bort
            paid -= shares
        elif kind == "sell_free":
            if free > 0 and shares > 0:
                antal = min(shares, free)
                resultat[index] = forsaljning_netto("sell_free", antal, buy.get("price") or 0)
            free -= shares
        else:
            free += shares
    return resultat


def realiserat_resultat(stock) -> float:
    """Vinst eller förlust på aktier som redan är sålda. Nya köp ändrar den inte."""
    return round(sum(_resultat_per_rad(stock).values()), 2)


def _till_utdelning(vinst: float, pott: float) -> float:
    """Vinst läggs i utdelningskassan. Förlust dras därifrån, men aldrig under noll."""
    if vinst >= 0:
        return round(vinst, 2)
    return round(max(vinst, -max(pott, 0.0)), 2)


def dividend_kostnad(shares, price) -> float:
    """Vad ett gratisköp tar ur utdelningskassan, inklusive courtage."""
    net = round(float(shares) * float(price or 0), 2)
    return round(net + courtage(net), 2)


def amount_text(value):
    text = f"{float(value):,.2f}".replace(",", " ").replace(".", ",")
    return text[:-3] if text.endswith(",00") else text


def _belopp(value, valuta):
    if value is None:
        return "okänt"
    return f"{amount_text(value)} {valuta or 'kr'}".strip()


def _antal(value):
    if value is None:
        return "0"
    return f"{float(value):g}"


def _procent(value):
    if value is None:
        return "okänt"
    return f"{float(value):.2f} %".replace(".", ",")


def chatgpt_fraga(stock, med_utdelning=True) -> str:
    """Färdig fråga om en aktie man redan äger. Ingen köp- eller säljorder."""
    namn = stock.get("name") or stock.get("ticker") or "aktien"
    ticker = stock.get("ticker") or ""
    valuta = stock.get("currency") or "kr"
    rader = [
        "Jag äger den här aktien privat och vill förstå läget.",
        "Svara på svenska, kort och konkret, med rubriker.",
        "Ge ingen order om att köpa eller sälja. Säg vad som är osäkert.",
        "",
        f"Aktie: {namn} ({ticker})",
        f"Börskurs: {_belopp(stock.get('price'), valuta)}",
        f"Antal aktier: {_antal(stock.get('totalShares'))}",
    ]
    if med_utdelning:
        rader.append(
            f"Varav betalda: {_antal(stock.get('paidShares'))}, "
            f"köpta för utdelning: {_antal(stock.get('freeShares'))}"
        )
    rader.append(
        f"Grundinsats, det jag betalat inklusive courtage: {_belopp(stock.get('grundbelopp'), valuta)}"
    )
    if stock.get("avgPaidPrice"):
        rader.append(f"Snittkurs på betalda aktier: {_belopp(stock.get('avgPaidPrice'), valuta)}")
    rader.append(f"Börsvärde: {_belopp(stock.get('marketValue'), valuta)}")
    if med_utdelning and stock.get("annualDividend") is not None:
        varje = {12: "månad", 4: "kvartal", 2: "halvår", 1: "år"}.get(stock.get("periodsPerYear"), "period")
        rader.append(
            f"Utdelning: {_belopp(stock.get('dividendPerPeriod'), valuta)} per {varje}, "
            f"{_belopp(stock.get('annualDividend'), valuta)} per aktie och år"
        )
        rader.append(f"Utdelning på det jag betalat: {_procent(stock.get('yieldOnCost'))}")
        rader.append(f"Direktavkastning på dagens kurs: {_procent(stock.get('marketYield'))}")
        rader.append(f"Utdelning per år på hela innehavet: {_belopp(stock.get('annualIncome'), valuta)}")
    elif stock.get("marketValue") is not None and stock.get("grundbelopp"):
        tal = (float(stock["marketValue"]) - float(stock["grundbelopp"])) / float(stock["grundbelopp"]) * 100
        rader.append(f"Utveckling mot det jag betalat: {_procent(tal)}")
    rader.extend([
        "",
        "Skriv så här:",
        "1. Vad bolaget tjänar pengar på, i två meningar.",
    ])
    if med_utdelning:
        rader.extend([
            "2. Utdelningen: om nivån ser hållbar ut, om den brukar ändras, och vad som kan sänka den.",
            "3. De två eller tre största riskerna för just det här bolaget just nu.",
            "4. Hur mitt innehav ser ut mot det jag betalat, i vanliga ord.",
        ])
    else:
        rader.extend([
            "2. De två eller tre största riskerna för just det här bolaget just nu.",
            "3. Hur mitt innehav ser ut mot det jag betalat, i vanliga ord.",
        ])
    rader.append("Använd färska uppgifter om du kan. Hitta inte på siffror.")
    return "\n".join(rader)


def oppna_chatgpt(stock, med_utdelning=True) -> None:
    """Öppnar ChatGPT i webbläsaren med frågan ifylld. Skickar inte själv."""
    text = chatgpt_fraga(stock, med_utdelning=med_utdelning)
    webbrowser.open("https://chatgpt.com/?q=" + quote(text) + "&hints=search")


def data_file():
    if getattr(sys, "frozen", False):
        folder = Path(os.environ.get("APPDATA", str(Path.home()))) / "Utdelning"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / "portfolj.json"
        if not target.exists():
            bundled = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "portfolj.json"
            if bundled.exists():
                target.write_bytes(bundled.read_bytes())
            else:
                target.write_text('{"stocks": []}\n', encoding="utf-8")
        return target
    return Path(__file__).resolve().parent / "portfolj.json"


DATA = data_file()
HOST = "127.0.0.1"
PORT = 8765
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5y&events=div"


_loader = None
_saver = None
_storage_stack: contextvars.ContextVar[tuple] = contextvars.ContextVar("utdelning_storage", default=())


def set_storage(loader, saver):
    """Koppla läsning och sparning till ett annat program. Utan koppling används portfolj.json."""
    global _loader, _saver
    _loader = loader
    _saver = saver


def push_storage(loader, saver):
    """Tillfällig lagring, till exempel ett annat konto. Återställ med pop_storage."""
    return _storage_stack.set(_storage_stack.get() + ((loader, saver),))


def pop_storage(token) -> None:
    _storage_stack.reset(token)


def _aktiv_lagring():
    stack = _storage_stack.get()
    if stack:
        return stack[-1]
    return (_loader, _saver)


def _normalisera(data):
    if not isinstance(data, dict):
        data = {}
    data.setdefault("stocks", [])
    data.setdefault("dividends", [])
    pot = float(data.get("cash") or 0)
    for stock in data["stocks"]:
        left = float(stock.get("cash") or 0)
        if left:
            pot += left
            stock["cash"] = 0
    data["cash"] = round(pot, 2)
    return data


def load():
    loader, _aktiv_saver = _aktiv_lagring()
    if loader is not None:
        return _normalisera(loader())
    if not DATA.exists():
        return {"stocks": [], "cash": 0, "dividends": []}
    return _normalisera(json.loads(DATA.read_text(encoding="utf-8")))


def save(data):
    _aktiv_loader, saver = _aktiv_lagring()
    if saver is not None:
        saver(data)
        return
    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _ar_kronor(currency):
    return (currency or "").strip().upper() in ("", "SEK", "KR")


def portfolj_siffror(data):
    """Börsvärde och avkastning på grundinsatsen. Kassan ingår inte i värdet."""
    value = 0.0
    income = 0.0
    base = 0.0
    for stock in (data or {}).get("stocks") or []:
        view = stock_view(stock)
        if not _ar_kronor(view.get("currency")):
            continue
        value += float(view.get("marketValue") or 0)
        income += float(view.get("annualIncome") or 0)
        base += float(view.get("grundbelopp") or 0)
    ranta = round(income / base * 100, 2) if base else 0.0
    return {
        "borsvarde": int(round(value)),
        "grundinsats": int(round(base)),
        "utdelning_ar": int(round(income)),
        "ranta": ranta,
        "kassa": round(float((data or {}).get("cash") or 0), 2),
    }


def varde_siffror(data):
    """Börsvärde och plus eller minus mot grundinsatsen. Utdelning räknas inte."""
    value = 0.0
    base = 0.0
    for stock in (data or {}).get("stocks") or []:
        view = stock_view(stock)
        if not _ar_kronor(view.get("currency")):
            continue
        value += float(view.get("marketValue") or 0)
        base += float(view.get("grundbelopp") or 0)
    plus = round((value - base) / base * 100, 2) if base else 0.0
    return {
        "borsvarde": int(round(value)),
        "grundinsats": int(round(base)),
        "plus": plus,
        "resultat": int(round(value - base)),
    }


def fetch_kurs(ticker):
    """Senaste börskurs. Utdelningar och köp lämnas orörda."""
    ticker = ticker.strip().upper()
    if not ticker:
        raise ValueError("Skriv en ticker, till exempel CIBUS.ST")
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{quote(ticker)}?interval=1d&range=1d"
    )
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(req, timeout=12) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        raise ValueError(f"Yahoo svarade {exc.code} för {ticker}") from exc
    except URLError as exc:
        raise ValueError(f"Kunde inte nå Yahoo: {exc.reason}") from exc
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        err = ((payload.get("chart") or {}).get("error") or {}).get("description")
        raise ValueError(err or f"Hittade inte {ticker} på Yahoo Finance")
    price = (result[0].get("meta") or {}).get("regularMarketPrice")
    if price is None:
        raise ValueError(f"Ingen kurs för {ticker}")
    return round(float(price), 4)


def fetch_yahoo(ticker):
    ticker = ticker.strip().upper()
    if not ticker:
        raise ValueError("Skriv en ticker, till exempel CIBUS.ST")
    url = YAHOO.format(ticker=ticker)
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        raise ValueError(f"Yahoo svarade {exc.code} för {ticker}") from exc
    except URLError as exc:
        raise ValueError(f"Kunde inte nå Yahoo: {exc.reason}") from exc

    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        err = ((payload.get("chart") or {}).get("error") or {}).get("description")
        raise ValueError(err or f"Hittade inte {ticker} på Yahoo Finance")

    meta = result[0].get("meta") or {}
    price = meta.get("regularMarketPrice")
    if price is None:
        raise ValueError(f"Ingen kurs för {ticker}")

    raw = ((result[0].get("events") or {}).get("dividends") or {})
    dividends = sorted(
        ({"date": int(item["date"]), "amount": float(item["amount"])} for item in raw.values()),
        key=lambda item: item["date"],
    )
    annual, per_period, periods = dividend_stats(dividends)
    return {
        "ticker": meta.get("symbol") or ticker,
        "name": meta.get("longName") or meta.get("shortName") or ticker,
        "currency": meta.get("currency") or "",
        "price": round(float(price), 4),
        "annualDividend": annual,
        "dividendPerPeriod": per_period,
        "periodsPerYear": periods,
        "dividends": dividends[-24:],
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def search_yahoo(query):
    query = (query or "").strip()
    if len(query) < 2:
        return []
    url = (
        "https://query2.finance.yahoo.com/v1/finance/search"
        f"?q={quote(query)}&quotesCount=12&newsCount=0"
    )
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError) as exc:
        raise ValueError("Kunde inte söka på Yahoo just nu") from exc
    hits = []
    for item in payload.get("quotes") or []:
        if item.get("quoteType") != "EQUITY" or not item.get("symbol"):
            continue
        hits.append(
            {
                "symbol": item["symbol"],
                "name": item.get("longname") or item.get("shortname") or item["symbol"],
                "exchange": item.get("exchDisp") or "",
            }
        )
    return hits


def dividend_stats(dividends):
    if not dividends:
        return None, None, 12
    now = time.time()
    year = [item["amount"] for item in dividends if item["date"] >= now - 370 * 86400]
    span = [item for item in dividends if item["date"] >= now - 3 * 365 * 86400]
    if len(span) >= 2:
        years = max((span[-1]["date"] - span[0]["date"]) / (365.25 * 86400), 0.5)
        per_year = len(span) / years
    else:
        per_year = float(len(year) or 1)
    if per_year >= 9:
        periods = 12
    elif per_year >= 3.2:
        periods = 4
    elif per_year >= 1.5:
        periods = 2
    else:
        periods = 1
    recent = [float(item["amount"]) for item in dividends[-periods:]]
    if not recent:
        return None, None, periods
    latest = recent[-1]
    older = recent[:-1]
    # Senaste utbetalningen är en ny, högre nivå och resten av året är inte betald ännu.
    # Tele2: 5,25 kr har kommit en gång, beslutet är 5,25 kr två gånger = 10,50 kr.
    raised = bool(older) and all(latest > amount * 1.1 for amount in older)
    if raised or len(recent) < periods:
        per_period = round(latest, 4)
        annual = round(per_period * periods, 4)
    else:
        annual = round(sum(recent), 4)
        per_period = round(annual / periods, 4)
    return annual, per_period, periods


def stock_view(stock):
    paid = float(stock.get("paidShares") or 0)
    free = float(stock.get("freeShares") or 0)
    total = paid + free
    base = float(stock.get("grundbelopp") or 0)
    price = stock.get("price")
    per_period = stock.get("dividendPerPeriod")
    periods = stock.get("periodsPerYear")
    if stock.get("dividends"):
        annual_ps, per_period, periods = dividend_stats(stock["dividends"])
    else:
        annual_ps = stock.get("annualDividend")
    value = round(total * price, 2) if price is not None else None
    annual = round(total * annual_ps, 2) if annual_ps is not None else None
    yoc = round(annual / base * 100, 2) if annual is not None and base > 0 else None
    ytm = round(annual_ps / price * 100, 2) if annual_ps is not None and price else None
    return {
        **stock,
        "annualDividend": annual_ps,
        "dividendPerPeriod": per_period,
        "periodsPerYear": periods,
        "totalShares": round(total, 4),
        "marketValue": value,
        "annualIncome": annual,
        "yieldOnCost": yoc,
        "marketYield": ytm,
        "realiserat": realiserat_resultat(stock),
        "avgPaidPrice": round(base / paid, 2) if paid > 0 else None,
        "avgAllPrice": round(base / total, 2) if total > 0 else None,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def send_json(self, code, body):
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            raw = (ROOT / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if parsed.path == "/api/portfolio":
            data = load()
            self.send_json(200, {"stocks": [stock_view(s) for s in data["stocks"]]})
            return
        if parsed.path == "/api/quote":
            ticker = (parse_qs(parsed.query).get("ticker") or [""])[0]
            try:
                self.send_json(200, fetch_yahoo(ticker))
            except ValueError as exc:
                self.send_json(400, {"error": str(exc)})
            return
        self.send_json(404, {"error": "Finns inte"})

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            body = self.read_json()
        except json.JSONDecodeError:
            self.send_json(400, {"error": "Ogiltig JSON"})
            return
        parts = [p for p in parsed.path.split("/") if p]
        try:
            if parts == ["api", "stocks"]:
                self.send_json(200, add_stock(body))
                return
            if len(parts) == 4 and parts[:2] == ["api", "stocks"] and parts[3] == "buy":
                self.send_json(200, buy(parts[2], body))
                return
            if len(parts) == 4 and parts[:2] == ["api", "stocks"] and parts[3] == "refresh":
                self.send_json(200, refresh(parts[2]))
                return
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})
            return
        self.send_json(404, {"error": "Finns inte"})

    def do_DELETE(self):
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        if len(parts) == 3 and parts[:2] == ["api", "stocks"]:
            data = load()
            before = len(data["stocks"])
            data["stocks"] = [s for s in data["stocks"] if s["id"] != parts[2]]
            if len(data["stocks"]) == before:
                self.send_json(404, {"error": "Aktien finns inte"})
                return
            save(data)
            self.send_json(200, {"ok": True})
            return
        self.send_json(404, {"error": "Finns inte"})


def find(data, stock_id):
    for stock in data["stocks"]:
        if stock["id"] == stock_id:
            return stock
    raise ValueError("Aktien finns inte")


def num(value, label):
    try:
        number = float(str(value).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        raise ValueError(f"{label} måste vara ett tal") from None
    if number < 0:
        raise ValueError(f"{label} kan inte vara negativt")
    return number


def add_stock(body):
    quote = fetch_yahoo(body.get("ticker") or "")
    shares = num(body.get("shares"), "Antal")
    if shares <= 0:
        raise ValueError("Antal måste vara större än noll")
    price = num(body["price"], "Köpkurs") if str(body.get("price") or "").strip() else quote["price"]
    if price <= 0:
        raise ValueError("Köpkurs måste vara större än noll")
    stock = {
        "id": uuid.uuid4().hex[:10],
        "ticker": quote["ticker"],
        "name": quote["name"],
        "currency": quote["currency"],
        "paidShares": 0,
        "freeShares": 0,
        "grundbelopp": 0,
        "cash": 0,
        "price": quote["price"],
        "annualDividend": quote["annualDividend"],
        "dividendPerPeriod": quote["dividendPerPeriod"],
        "periodsPerYear": quote["periodsPerYear"],
        "dividends": quote["dividends"],
        "updated": quote["updated"],
        "buys": [
            {
                "kind": "own",
                "shares": round(shares, 4),
                "price": round(price, 4),
                "date": datetime.now().isoformat(timespec="minutes"),
            }
        ],
    }
    recalc(stock)
    data = load()
    data["stocks"].append(stock)
    save(data)
    return stock_view(stock)


def buy(stock_id, body):
    kind = body.get("kind")
    if kind not in ("own", "dividend"):
        raise ValueError("Välj egna pengar eller utdelning")
    shares = num(body.get("shares"), "Antal")
    if shares <= 0:
        raise ValueError("Antal måste vara större än noll")
    data = load()
    stock = find(data, stock_id)
    if kind == "own":
        price = num(body.get("price"), "Köpkurs") if str(body.get("price") or "").strip() else None
        if not price or price <= 0:
            raise ValueError("Ange vad du betalade per aktie")
    elif str(body.get("price") or "").strip():
        price = num(body.get("price"), "Kurs")
        if price <= 0:
            raise ValueError("Kursen måste vara större än noll")
    else:
        price = stock.get("price") or 0
    currency = stock.get("currency") or "kr"
    note = None
    if kind == "dividend":
        net = round(shares * float(price or 0), 2)
        fee = courtage(net)
        cost = dividend_kostnad(shares, price)
        pot = round(float(data.get("cash") or 0), 2)
        if cost > pot + 1e-6:
            raise ValueError(
                f"Köpet kostar {amount_text(cost)} {currency} med courtage men utdelningskassan har "
                f"bara {amount_text(pot)} {currency}. Du saknar {amount_text(cost - pot)} {currency}."
            )
        data["cash"] = round(pot - cost, 2)
        note = (
            f"Tog {amount_text(cost)} {currency} ur utdelningskassan "
            f"({amount_text(net)} plus {amount_text(fee)} i courtage). "
            f"Kvar: {amount_text(data['cash'])} {currency}."
        )
    stock.setdefault("buys", []).append(
        {
            "kind": kind,
            "shares": round(shares, 4),
            "price": round(float(price), 4),
            "date": datetime.now().isoformat(timespec="minutes"),
        }
    )
    recalc(stock)
    save(data)
    view = stock_view(stock)
    view["cashPot"] = data["cash"]
    if kind == "own":
        fee = courtage(shares * float(price))
        note = f"Courtage {amount_text(fee)} {currency} ingår i grundinsatsen."
    if note:
        view["note"] = note
    return view


def sell(stock_id, body, till_utdelning=False):
    """Säljer aktier. Med till_utdelning hamnar vinsten i utdelningskassan och resten i kontantkassan."""
    kind = body.get("kind")
    if kind not in ("paid", "free"):
        raise ValueError("Välj betalda eller gratisaktier")
    shares = num(body.get("shares"), "Antal")
    if shares <= 0:
        raise ValueError("Antal måste vara större än noll")
    data = load()
    stock = find(data, stock_id)
    price = num(body["price"], "Försäljningskurs") if str(body.get("price") or "").strip() else stock.get("price")
    if not price or price <= 0:
        raise ValueError("Ange försäljningskursen")
    owned = float(stock.get("paidShares") or 0) if kind == "paid" else float(stock.get("freeShares") or 0)
    if shares > owned + 1e-6:
        label = "betalda" if kind == "paid" else "gratis"
        raise ValueError(f"Du har bara {owned:g} {label} aktier")
    rad = {
        "kind": "sell_own" if kind == "paid" else "sell_free",
        "shares": round(shares, 4),
        "price": round(float(price), 4),
        "date": datetime.now().isoformat(timespec="minutes"),
    }
    stock.setdefault("buys", []).append(rad)
    recalc(stock)
    netto = forsaljning_netto(rad["kind"], shares, price)
    valuta = stock.get("currency") or "kr"
    fee = courtage(shares * float(price))
    note = f"Sålde {shares:g} aktier. Courtaget är {amount_text(fee)} {valuta}."
    if till_utdelning and _ar_kronor(stock.get("currency")):
        vinst = _resultat_per_rad(stock).get(len(stock["buys"]) - 1, 0.0)
        pott = round(float(data.get("cash") or 0), 2)
        del_ = _till_utdelning(vinst, pott)
        rad["utdelning_del"] = del_
        data["cash"] = round(pott + del_, 2)
        kontant_del = round(netto - del_, 2)
        if del_ > 0:
            note += f" Vinsten {amount_text(del_)} kr lades i Utdelning och vinst."
        elif del_ < 0:
            note += f" Förlusten {amount_text(-del_)} kr drogs från Utdelning och vinst."
    else:
        kontant_del = netto if rad["kind"] == "sell_own" else 0.0
    save(data)
    view = stock_view(stock)
    view["cashPot"] = data["cash"]
    view["kontantDel"] = kontant_del
    view["note"] = note
    return view


def recalc(stock):
    paid = 0.0
    free = 0.0
    base = 0.0
    for buy in stock.get("buys") or []:
        shares = float(buy["shares"])
        kind = buy.get("kind")
        if kind == "own":
            paid += shares
            cost = shares * float(buy["price"])
            base += cost + courtage(cost)
        elif kind == "sell_own":
            if shares > paid + 1e-6:
                raise ValueError("Försäljningen är större än de betalda aktierna")
            if paid > 0:
                base -= base * (shares / paid)
            paid -= shares
        elif kind == "sell_free":
            if shares > free + 1e-6:
                raise ValueError("Försäljningen är större än gratisaktierna")
            free -= shares
        else:
            free += shares
    stock["paidShares"] = round(max(paid, 0), 4)
    stock["freeShares"] = round(max(free, 0), 4)
    stock["grundbelopp"] = round(max(base, 0), 2)
    if stock.get("dividends"):
        annual, per_period, periods = dividend_stats(stock["dividends"])
        if annual is not None:
            stock["annualDividend"] = annual
            stock["dividendPerPeriod"] = per_period
            stock["periodsPerYear"] = periods


def update_buy(stock_id, index, shares, price=None):
    shares = num(shares, "Antal")
    if shares <= 0:
        raise ValueError("Antal måste vara större än noll")
    data = load()
    stock = find(data, stock_id)
    buys = stock.get("buys") or []
    if index < 0 or index >= len(buys):
        raise ValueError("Köpet finns inte")
    buy = buys[index]
    old_shares = buy.get("shares")
    old_price = buy.get("price")
    new_shares = round(shares, 4)
    new_price = old_price
    if buy.get("kind") in ("own", "sell_own", "sell_free", "dividend"):
        label = "Försäljningskurs" if str(buy.get("kind")).startswith("sell") else "Köpkurs"
        amount = num(price, label) if str(price or "").strip() else None
        if not amount or amount <= 0:
            raise ValueError(f"Ange {label.lower()}en")
        new_price = round(amount, 4)
    if buy.get("kind") == "dividend":
        skillnad = round(dividend_kostnad(old_shares, old_price) - dividend_kostnad(new_shares, new_price), 2)
        pot = round(float(data.get("cash") or 0) + skillnad, 2)
        if pot < -0.005:
            saknas = round(-pot, 2)
            raise ValueError(
                f"Utdelningskassan räcker inte till den ändringen. Du saknar {amount_text(saknas)} kr."
            )
        data["cash"] = pot
    kontant_diff = 0.0
    if "utdelning_del" in buy:
        gammal_del = float(buy.get("utdelning_del") or 0)
        gammal_netto = forsaljning_netto(buy.get("kind"), old_shares, old_price)
        buy["shares"] = new_shares
        buy["price"] = new_price
        try:
            recalc(stock)
        except Exception:
            buy["shares"] = old_shares
            buy["price"] = old_price
            recalc(stock)
            raise
        vinst = _resultat_per_rad(stock).get(index, 0.0)
        pott_utan = round(float(data.get("cash") or 0) - gammal_del, 2)
        ny_del = _till_utdelning(vinst, pott_utan)
        if pott_utan + ny_del < -0.005:
            buy["shares"] = old_shares
            buy["price"] = old_price
            recalc(stock)
            saknas = round(-(pott_utan + ny_del), 2)
            raise ValueError(
                f"Utdelning och vinst räcker inte till den ändringen. Du saknar {amount_text(saknas)} kr."
            )
        buy["utdelning_del"] = ny_del
        data["cash"] = round(pott_utan + ny_del, 2)
        ny_netto = forsaljning_netto(buy.get("kind"), new_shares, new_price)
        kontant_diff = round((ny_netto - ny_del) - (gammal_netto - gammal_del), 2)
    else:
        buy["shares"] = new_shares
        buy["price"] = new_price
        recalc(stock)
    save(data)
    view = stock_view(stock)
    view["cashPot"] = data["cash"]
    view["kontantDiff"] = kontant_diff
    view["note"] = "Köpet är ändrat."
    return view


def delete_buy(stock_id, index):
    data = load()
    stock = find(data, stock_id)
    buys = stock.get("buys") or []
    if index < 0 or index >= len(buys):
        raise ValueError("Köpet finns inte")
    removed = buys.pop(index)
    stock["buys"] = buys
    try:
        recalc(stock)
    except Exception:
        buys.insert(index, removed)
        stock["buys"] = buys
        raise
    note = "Köpet är borttaget."
    if removed.get("kind") == "dividend":
        tillbaka = dividend_kostnad(removed.get("shares") or 0, removed.get("price") or 0)
        data["cash"] = round(float(data.get("cash") or 0) + tillbaka, 2)
        note = f"Köpet är borttaget. {amount_text(tillbaka)} kr är tillbaka i utdelningskassan."
    elif "utdelning_del" in removed:
        del_ = float(removed.get("utdelning_del") or 0)
        pott = round(float(data.get("cash") or 0) - del_, 2)
        if pott < -0.005:
            buys.insert(index, removed)
            stock["buys"] = buys
            recalc(stock)
            raise ValueError(
                f"Vinsten är redan använd. Utdelning och vinst saknar {amount_text(-pott)} kr."
            )
        data["cash"] = pott
    save(data)
    view = stock_view(stock)
    view["cashPot"] = data["cash"]
    view["note"] = note
    return view


def parse_date(value):
    text = str(value or "").strip()
    if not text:
        return datetime.now().strftime("%Y-%m-%d")
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d/%m", "%Y%m%d"):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if fmt == "%d/%m":
            parsed = parsed.replace(year=datetime.now().year)
        return parsed.strftime("%Y-%m-%d")
    raise ValueError("Skriv datumet som 2026-09-29")


def add_cash(amount, stock_id=None, date=None):
    if not str(amount or "").strip():
        raise ValueError("Skriv in utdelningen du fick")
    value = num(amount, "Utdelning")
    if value <= 0:
        raise ValueError("Utdelningen måste vara större än noll")
    day = parse_date(date)
    data = load()
    ticker = ""
    name = ""
    if stock_id:
        stock = find(data, stock_id)
        ticker = stock["ticker"]
        name = stock.get("name") or ticker
    data["dividends"].append(
        {
            "id": uuid.uuid4().hex[:10],
            "stockId": stock_id or "",
            "ticker": ticker,
            "name": name,
            "amount": round(value, 2),
            "date": day,
        }
    )
    data["cash"] = round(float(data.get("cash") or 0) + value, 2)
    save(data)
    return data["cash"]


def delete_dividend(entry_id):
    data = load()
    removed = None
    kept = []
    for entry in data.get("dividends") or []:
        if removed is None and entry.get("id") == entry_id:
            removed = entry
        else:
            kept.append(entry)
    if removed is None:
        raise ValueError("Raden finns inte")
    data["dividends"] = kept
    data["cash"] = round(max(float(data.get("cash") or 0) - float(removed["amount"] or 0), 0), 2)
    save(data)
    return data["cash"]


def cash_history():
    data = load()
    rows = []
    for entry in data.get("dividends") or []:
        rows.append(
            {
                "id": entry.get("id") or "",
                "date": entry.get("date") or "",
                "stock": entry.get("name") or entry.get("ticker") or "Ingen särskild aktie",
                "text": "Utdelning",
                "amount": round(float(entry.get("amount") or 0), 2),
            }
        )
    for stock in data["stocks"]:
        for buy in stock.get("buys") or []:
            if buy.get("kind") != "dividend":
                continue
            shares = float(buy.get("shares") or 0)
            price = float(buy.get("price") or 0)
            net = round(shares * price, 2)
            fee = courtage(net)
            rows.append(
                {
                    "id": "",
                    "date": (buy.get("date") or "")[:10],
                    "stock": stock.get("name") or stock["ticker"],
                    "text": (
                        f"Köpte {shares:g} gratisaktier för {amount_text(price)} styck "
                        f"plus {amount_text(fee)} courtage"
                    ),
                    "amount": -round(net + fee, 2),
                }
            )
    rows.sort(key=lambda row: (row["date"], row["amount"] < 0), reverse=True)
    return rows, round(float(data.get("cash") or 0), 2)


def set_cash(amount):
    data = load()
    value = num(amount, "Belopp") if str(amount or "").strip() else 0.0
    data["cash"] = round(value, 2)
    save(data)
    return data["cash"]


def export_portfolio(path):
    data = load()
    target = Path(path)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(data["stocks"])


def import_portfolio(path):
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("Filen är inte en giltig portföljfil") from exc
    if isinstance(raw, list):
        raw = {"stocks": raw}
    if not isinstance(raw, dict) or not isinstance(raw.get("stocks"), list):
        raise ValueError("Filen ser inte ut som en sparad portfölj")
    pot = num(raw.get("cash") or 0, "Utdelningskassa")
    history = []
    for entry in raw.get("dividends") or []:
        if not isinstance(entry, dict):
            raise ValueError("En rad i utdelningshistoriken kan inte läsas")
        history.append(
            {
                "id": str(entry.get("id") or uuid.uuid4().hex[:10]),
                "stockId": str(entry.get("stockId") or ""),
                "ticker": entry.get("ticker") or "",
                "name": entry.get("name") or "",
                "amount": round(num(entry.get("amount") or 0, "Utdelning"), 2),
                "date": parse_date(entry.get("date")),
            }
        )
    stocks = []
    seen = set()
    for item in raw["stocks"]:
        if not isinstance(item, dict) or not item.get("ticker"):
            raise ValueError("Filen innehåller en post som inte är en aktie")
        stock = dict(item)
        stock_id = str(stock.get("id") or "")
        if not stock_id or stock_id in seen:
            stock_id = uuid.uuid4().hex[:10]
        seen.add(stock_id)
        stock["id"] = stock_id
        stock["name"] = stock.get("name") or stock["ticker"]
        pot += num(stock.get("cash") or 0, "Utdelningskassa")
        stock["cash"] = 0
        buys = []
        for entry in stock.get("buys") or []:
            if not isinstance(entry, dict):
                raise ValueError(f"Ett köp i {stock['ticker']} kan inte läsas")
            buys.append(
                {
                    "kind": entry.get("kind") or "own",
                    "shares": num(entry.get("shares"), "Antal"),
                    "price": num(entry.get("price") or 0, "Kurs"),
                    "date": entry.get("date") or "",
                }
            )
        stock["buys"] = buys
        recalc(stock)
        stocks.append(stock)
    save({"stocks": stocks, "cash": round(pot, 2), "dividends": history})
    return len(stocks)


def refresh(stock_id):
    data = load()
    stock = find(data, stock_id)
    quote = fetch_yahoo(stock["ticker"])
    stock.update(
        {
            "name": quote["name"],
            "currency": quote["currency"],
            "price": quote["price"],
            "annualDividend": quote["annualDividend"],
            "dividendPerPeriod": quote["dividendPerPeriod"],
            "periodsPerYear": quote["periodsPerYear"],
            "dividends": quote["dividends"],
            "updated": quote["updated"],
        }
    )
    save(data)
    return stock_view(stock)


def refresh_all():
    data = load()
    done = 0
    failed = []
    for stock in data["stocks"]:
        try:
            quote = fetch_yahoo(stock["ticker"])
        except ValueError as exc:
            failed.append(f"{stock['ticker']}: {exc}")
            continue
        stock.update(
            {
                "name": quote["name"],
                "currency": quote["currency"],
                "price": quote["price"],
                "annualDividend": quote["annualDividend"],
                "dividendPerPeriod": quote["dividendPerPeriod"],
                "periodsPerYear": quote["periodsPerYear"],
                "dividends": quote["dividends"],
                "updated": quote["updated"],
            }
        )
        done += 1
    save(data)
    return done, failed


def dividend_calendar():
    data = load()
    now = datetime.now()
    rows = []
    for stock in data["stocks"]:
        shares = float(stock.get("paidShares") or 0) + float(stock.get("freeShares") or 0)
        history = stock.get("dividends") or []
        if shares <= 0 or not history:
            continue
        _, per_period, periods = dividend_stats(history)
        periods = int(periods or 0)
        if not periods or per_period is None:
            continue
        already = set()
        amounts = {}
        for item in history:
            day = datetime.fromtimestamp(int(item["date"]))
            already.add((day.year, day.month))
        for item in history[-periods:]:
            day = datetime.fromtimestamp(int(item["date"]))
            amounts[day.month] = float(per_period)
        for offset in range(12):
            index = now.month - 1 + offset
            year = now.year + index // 12
            month = index % 12 + 1
            if month not in amounts or (year, month) in already:
                continue
            rows.append(
                {
                    "year": year,
                    "month": month,
                    "ticker": stock["ticker"],
                    "name": stock.get("name") or stock["ticker"],
                    "currency": stock.get("currency") or "kr",
                    "perShare": round(amounts[month], 4),
                    "shares": round(shares, 4),
                    "amount": round(amounts[month] * shares, 2),
                }
            )
    rows.sort(key=lambda row: (row["year"], row["month"], row["name"]))
    return rows


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}"
    print(f"Utdelning körs på {url}")
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStoppad.")


if __name__ == "__main__":
    main()
