# -*- coding: utf-8 -*-
"""Aktiehandel utan utdelning. Sök, köp och sälj, med plus eller minus mot insatsen."""

import contextvars
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

import utdelning_core as app

BG = "#f4f1eb"
CARD = "#fffcf8"
INK = "#1c1915"
MUTED = "#6d675f"
LINE = "#e6e0d6"
GREEN = "#1f6b45"
RED = "#9a3b32"
GREEN_SOFT = "#e7f3ec"
FIELD = "#ffffff"


def money(value, currency=""):
    if value is None:
        return "–"
    text = f"{float(value):,.2f}".replace(",", " ").replace(".", ",")
    return f"{text} {currency}".strip()


def signed_pct(value):
    if value is None:
        return "–"
    return f"{float(value):+.2f} %".replace(".", ",")


def shares_text(value):
    return f"{float(value):g}"


def plus_mot_insats(stock):
    """Procent och kronor mot grundinsatsen. None i procent när insatsen är noll."""
    base = float(stock.get("grundbelopp") or 0)
    value = float(stock.get("marketValue") or 0)
    kronor = value - base
    if base <= 0:
        return None, kronor
    return round(kronor / base * 100, 2), kronor


class AktieHandelApp(tk.Frame):
    def __init__(self, parent, loader, saver):
        super().__init__(parent, bg=BG)
        self.selected_id = None
        self.hits = []
        self.chosen = None
        self.stocks = {}
        self._search_job = None
        self._kontanter = 0.0
        self._satt_kontanter = None
        self._storage_token = app.push_storage(loader, saver)
        self._style()
        self._build()
        self.reload()

    def destroy(self):
        token = getattr(self, "_storage_token", None)
        if token is not None:
            self._storage_token = None
            app.pop_storage(token)
        super().destroy()

    def _thread(self, work):
        ctx = contextvars.copy_context()
        threading.Thread(target=lambda: ctx.run(work), daemon=True).start()

    def _style(self):
        style = ttk.Style(self)
        style.configure(
            "Handel.Treeview",
            background=CARD,
            fieldbackground=CARD,
            foreground=INK,
            rowheight=34,
            borderwidth=0,
            font=("Segoe UI", 10),
        )
        style.configure(
            "Handel.Treeview.Heading",
            background="#efeae2",
            foreground=INK,
            font=("Segoe UI", 10, "bold"),
            relief="flat",
        )
        style.map("Handel.Treeview", background=[("selected", GREEN_SOFT)], foreground=[("selected", INK)])
        style.layout("Handel.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

    def _build(self):
        outer = tk.Frame(self, bg=BG, padx=16, pady=14)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=3)
        outer.columnconfigure(1, weight=4, minsize=460)
        outer.rowconfigure(2, weight=1)

        total = self._card(outer)
        total.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        total_inner = tk.Frame(total, bg=CARD, padx=14, pady=10)
        total_inner.pack(fill="x")
        tk.Label(total_inner, text="Hela innehavet", bg=CARD, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w")
        self.total_label = tk.Label(
            total_inner, text="Inga aktier ännu", bg=CARD, fg=INK,
            font=("Segoe UI", 14, "bold"), anchor="w", justify="left",
        )
        self.total_label.pack(anchor="w", fill="x")
        self.total_label.bind("<Configure>", lambda e: self.total_label.configure(wraplength=max(240, e.width - 8)))

        top_buttons = tk.Frame(total_inner, bg=CARD)
        top_buttons.pack(anchor="w", fill="x", pady=(10, 0))
        self.refresh_all_btn = self._button(top_buttons, "Uppdatera alla", self.refresh_all)
        self.refresh_all_btn.pack(side="right")

        kontant_row = tk.Frame(total_inner, bg=CARD)
        kontant_row.pack(anchor="w", fill="x", pady=(8, 0))
        tk.Label(kontant_row, text="Kontantkassa", bg=CARD, fg=MUTED, font=("Segoe UI", 9)).pack(side="left")
        self.kontant_label = tk.Label(kontant_row, text="0 kr", bg=CARD, fg=INK, font=("Segoe UI", 14, "bold"))
        self.kontant_label.pack(side="left", padx=(8, 12))
        self._button(kontant_row, "Rätta", self._ratta_kontanter).pack(side="left")
        self._button(kontant_row, "Insättning", self._gor_insattning).pack(side="left", padx=(8, 0))
        tk.Label(
            kontant_row,
            text="Pengar som inte sitter i aktier. Ingår i kontots värde. Rätta så det stämmer från början.",
            bg=CARD, fg=MUTED, font=("Segoe UI", 9),
        ).pack(side="left", padx=(12, 0))

        add = self._card(outer)
        add.grid(row=1, column=0, sticky="ew", padx=(0, 12), pady=(0, 10))
        inner = tk.Frame(add, bg=CARD, padx=12, pady=10)
        inner.pack(fill="x")
        tk.Label(inner, text="Sök aktie", bg=CARD, fg=INK, font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w")
        self.query = self._entry(inner, 28)
        self.query.grid(row=1, column=0, sticky="we", padx=(0, 8))
        self.query.bind("<KeyRelease>", self.on_search_type)
        self.query.bind("<Return>", lambda _e: self.search_now())
        self.search_btn = self._button(inner, "Sök", self.search_now, primary=True)
        self.search_btn.grid(row=1, column=1, sticky="w")
        self.results = tk.Listbox(
            inner, height=3, bg=FIELD, fg=INK, font=("Segoe UI", 10), relief="flat",
            highlightthickness=1, highlightbackground=LINE, selectbackground=GREEN_SOFT,
            selectforeground=INK, activestyle="none",
        )
        self.results.grid(row=2, column=0, columnspan=2, sticky="we", pady=(6, 0))
        self.results.grid_remove()
        self.results.bind("<<ListboxSelect>>", self.pick_hit)
        self.chosen_label = tk.Label(inner, text="Ingen aktie vald", bg=CARD, fg=MUTED, font=("Segoe UI", 10), anchor="w")
        self.chosen_label.grid(row=3, column=0, columnspan=2, sticky="we", pady=(6, 6))
        fields = tk.Frame(inner, bg=CARD)
        fields.grid(row=4, column=0, columnspan=2, sticky="w")
        count_box = tk.Frame(fields, bg=CARD)
        count_box.pack(side="left", padx=(0, 16))
        tk.Label(count_box, text="Antal aktier", bg=CARD, fg=INK, font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.shares = self._entry(count_box, 12)
        self.shares.pack(anchor="w", pady=(3, 0))
        price_box = tk.Frame(fields, bg=CARD)
        price_box.pack(side="left", padx=(0, 16))
        tk.Label(price_box, text="Köpkurs per aktie", bg=CARD, fg=INK, font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.price = self._entry(price_box, 14)
        self.price.pack(anchor="w", pady=(3, 0))
        self.add_btn = self._button(fields, "Lägg till", self.add_stock, primary=True)
        self.add_btn.pack(side="left", anchor="s")
        self.status = tk.Label(
            inner,
            text="Tom köpkurs använder dagens kurs. Courtage 0,25 %, minst 1 kr, ingår i det du betalat.",
            bg=CARD, fg=MUTED, font=("Segoe UI", 9), anchor="w", justify="left",
        )
        self.status.grid(row=5, column=0, columnspan=2, sticky="we", pady=(6, 0))
        inner.columnconfigure(0, weight=1)

        left = self._card(outer)
        left.grid(row=2, column=0, sticky="nsew", padx=(0, 12))
        left_inner = tk.Frame(left, bg=CARD, padx=8, pady=8)
        left_inner.pack(fill="both", expand=True)
        columns = ("ticker", "name", "shares", "base", "plus")
        self.tree = ttk.Treeview(
            left_inner, columns=columns, show="headings", selectmode="browse", style="Handel.Treeview",
        )
        headings = (
            ("ticker", "Ticker", 72, False),
            ("name", "Namn", 90, True),
            ("shares", "Antal", 52, False),
            ("base", "Betalat", 96, False),
            ("plus", "+/−", 78, False),
        )
        for key, title, width, stretch in headings:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=width, stretch=stretch, anchor="w" if key in ("ticker", "name") else "e")
        y_scroll = ttk.Scrollbar(left_inner, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=y_scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        self.insatt_label = tk.Label(
            left_inner, text="", bg=CARD, fg=MUTED, font=("Segoe UI", 9), anchor="w", justify="left",
        )
        self.insatt_label.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.insatt_label.bind("<Configure>", lambda e: self.insatt_label.configure(wraplength=max(180, e.width - 8)))
        self.insatt_label.grid_remove()
        left_inner.rowconfigure(0, weight=1)
        left_inner.columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        right = self._card(outer)
        right.grid(row=1, column=1, rowspan=2, sticky="nsew")
        canvas = tk.Canvas(right, bg=CARD, highlightthickness=0, bd=0)
        side_scroll = ttk.Scrollbar(right, orient="vertical", command=canvas.yview)
        side = tk.Frame(canvas, bg=CARD, padx=16, pady=16)
        side.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        window_id = canvas.create_window((0, 0), window=side, anchor="nw")
        canvas.configure(yscrollcommand=side_scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        side_scroll.pack(side="right", fill="y")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window_id, width=e.width))
        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", lambda ev: canvas.yview_scroll(int(-ev.delta / 120), "units")))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

        name_row = tk.Frame(side, bg=CARD)
        name_row.pack(fill="x")
        self.name_label = tk.Label(
            name_row, text="Inga aktier ännu", bg=CARD, fg=INK,
            font=("Segoe UI", 18, "bold"), anchor="w", justify="left",
        )
        self.name_label.pack(side="left", fill="x", expand=True)
        self._button(name_row, "Ta bort hela aktien", self.remove).pack(side="right", anchor="n")
        knapp_rad = tk.Frame(side, bg=CARD)
        knapp_rad.pack(anchor="w", pady=(8, 0))
        self._button(knapp_rad, "Uppdatera börskurs", self.refresh_price).pack(side="left")
        self._button(knapp_rad, "Fråga ChatGPT", self.frage_chatgpt).pack(side="left", padx=(8, 0))
        self.meta_label = tk.Label(
            side, text="Sök fram den du vill ha och lägg till den.",
            bg=CARD, fg=MUTED, font=("Segoe UI", 11), anchor="w", justify="left",
        )
        self.meta_label.pack(anchor="w", fill="x", pady=(2, 10))
        self.name_label.bind("<Configure>", lambda e: self.name_label.configure(wraplength=max(200, e.width - 8)))
        self.meta_label.bind("<Configure>", lambda e: self.meta_label.configure(wraplength=max(200, e.width - 8)))

        metrics = tk.Frame(side, bg=CARD)
        metrics.pack(fill="x", pady=(0, 8))
        self.plus_value = self._metric(metrics, "Plus eller minus")
        self.result_value = self._metric(metrics, "Mot det du betalat")
        self.plus_value.master.pack(side="left", fill="both", expand=True, padx=(0, 8))
        self.result_value.master.pack(side="left", fill="both", expand=True)

        self.facts = tk.Label(side, text="", bg=CARD, fg=INK, font=("Segoe UI", 11), anchor="w", justify="left")
        self.facts.pack(anchor="w", fill="x", pady=(4, 0))
        self.facts.bind("<Configure>", lambda e: self.facts.configure(wraplength=max(200, e.width - 8)))

        self._section(side, "Köp fler")
        paid_row = tk.Frame(side, bg=CARD)
        paid_row.pack(anchor="w", fill="x", pady=(6, 4))
        paid_count, self.paid_shares = self._labeled(paid_row, "Antal aktier", 12)
        paid_count.pack(side="left", padx=(0, 12))
        paid_price, self.paid_price = self._labeled(paid_row, "Köpkurs per aktie", 12)
        paid_price.pack(side="left")
        self._button(side, "Köp", lambda: self.buy(), primary=True).pack(anchor="w", pady=(6, 0))
        tk.Label(
            side, text="Courtage 0,25 %, minst 1 kr, dras från kontantkassan och ingår i det du betalat.",
            bg=CARD, fg=MUTED, font=("Segoe UI", 9), anchor="w",
        ).pack(anchor="w", pady=(4, 0))

        self._section(side, "Sälj")
        sell_row = tk.Frame(side, bg=CARD)
        sell_row.pack(anchor="w", fill="x", pady=(6, 4))
        sell_count, self.sell_shares = self._labeled(sell_row, "Antal aktier", 12)
        sell_count.pack(side="left", padx=(0, 12))
        sell_price, self.sell_price = self._labeled(sell_row, "Försäljningskurs", 12)
        sell_price.pack(side="left")
        self._button(side, "Sälj", lambda: self.sell(), primary=True).pack(anchor="w", pady=(6, 0))
        tk.Label(
            side, text="Courtage dras från det du får. Resten läggs i kontantkassan.",
            bg=CARD, fg=MUTED, font=("Segoe UI", 9), anchor="w",
        ).pack(anchor="w", pady=(4, 0))

        self._section(side, "Dina köp och sälj")
        tk.Label(
            side, text="Ändra antal eller kurs och spara, eller ta bort raden.",
            bg=CARD, fg=MUTED, font=("Segoe UI", 9), anchor="w", justify="left",
        ).pack(anchor="w", fill="x")
        self.history = tk.Frame(side, bg=CARD)
        self.history.pack(anchor="w", fill="x", pady=(8, 8))

    def _metric(self, parent, caption):
        box = tk.Frame(parent, bg="#f6f3ed", padx=14, pady=12, highlightbackground=LINE, highlightthickness=1)
        tk.Label(box, text=caption, bg="#f6f3ed", fg=MUTED, font=("Segoe UI", 9), anchor="w").pack(anchor="w")
        value = tk.Label(box, text="–", bg="#f6f3ed", fg=INK, font=("Segoe UI", 26, "bold"), anchor="w")
        value.pack(anchor="w", pady=(4, 0))
        return value

    def _card(self, parent):
        return tk.Frame(parent, bg=CARD, highlightbackground=LINE, highlightthickness=1)

    def _labeled(self, parent, title, width):
        box = tk.Frame(parent, bg=CARD)
        tk.Label(box, text=title, bg=CARD, fg=INK, font=("Segoe UI", 10, "bold"), anchor="w").pack(anchor="w")
        entry = self._entry(box, width)
        entry.pack(anchor="w", fill="x", pady=(4, 0))
        return box, entry

    def _entry(self, parent, width):
        return tk.Entry(
            parent, width=width, bg=FIELD, fg=INK, relief="flat", highlightthickness=1,
            highlightbackground=LINE, highlightcolor=GREEN, font=("Segoe UI", 12), insertbackground=INK,
        )

    def _button(self, parent, text, command, primary=False):
        return tk.Button(
            parent, text=text, command=command,
            bg=GREEN if primary else CARD, fg="#ffffff" if primary else INK,
            activebackground="#185538" if primary else "#f3efe8",
            activeforeground="#ffffff" if primary else INK,
            relief="flat", bd=0, padx=12, pady=8,
            font=("Segoe UI", 10, "bold" if primary else "normal"),
            cursor="hand2", highlightthickness=1, highlightbackground=GREEN if primary else LINE,
        )

    def _section(self, parent, text):
        tk.Label(parent, text=text, bg=CARD, fg=INK, font=("Segoe UI", 12, "bold"), anchor="w").pack(
            anchor="w", fill="x", pady=(18, 4),
        )

    def set_status(self, text):
        self.status.configure(text=text)

    def koppla_insattning(self, callback) -> None:
        self._on_insattning = callback

    def _gor_insattning(self) -> None:
        callback = getattr(self, "_on_insattning", None)
        if callback:
            callback()

    def visa_insatt(self, belopp) -> None:
        kronor = f"{int(round(float(belopp or 0))):,}".replace(",", " ")
        self.insatt_label.configure(
            text=(
                f"Insatt sedan start  {kronor} kr\n"
                "Summan av överföringar och insättningar här. Den räknas inte en gång till. Kontantkassan ovan ingår i värdet."
            )
        )
        self.insatt_label.grid()

    def visa_kontanter(self, belopp, on_satt) -> None:
        self._kontanter = round(float(belopp or 0), 2)
        self._satt_kontanter = on_satt
        self._rita_kontanter()

    def _rita_kontanter(self) -> None:
        self.kontant_label.configure(text=f"{app.amount_text(self._kontanter)} kr")

    def _ratta_kontanter(self) -> None:
        text = simpledialog.askstring(
            "Kontantkassa",
            "Hur mycket ligger i kontantkassan just nu?\n"
            "Sätt det som stämmer från början. Nya köp, överföringar och insättningar räknas sedan härifrån.",
            initialvalue=app.amount_text(self._kontanter),
            parent=self,
        )
        if text is None:
            return
        try:
            belopp = float(str(text).replace(" ", "").replace("\u00a0", "").replace(",", "."))
        except ValueError:
            messagebox.showerror("Aktier", "Skriv ett belopp, till exempel 5000.")
            return
        self._kontanter = round(belopp, 2)
        if self._satt_kontanter:
            self._satt_kontanter(self._kontanter)
        self._rita_kontanter()

    def _andra_aktie_kontanter(self, stock, delta) -> bool:
        if not app._ar_kronor((stock or {}).get("currency")):
            return True
        return self._andra_kontanter(delta)

    def _andra_kontanter(self, delta) -> bool:
        if not self._satt_kontanter:
            return True
        nytt = round(self._kontanter + float(delta), 2)
        if nytt < -0.005:
            messagebox.showerror(
                "Aktier",
                f"Kontantkassan har {app.amount_text(self._kontanter)} kr. "
                "Det räcker inte. Rätta kassan så den stämmer, eller för över pengar först.",
            )
            return False
        self._kontanter = nytt
        self._satt_kontanter(self._kontanter)
        self._rita_kontanter()
        return True

    def on_search_type(self, _event):
        if self._search_job:
            self.after_cancel(self._search_job)
        self._search_job = self.after(350, self.search_now)

    def search_now(self):
        self._search_job = None
        query = self.query.get().strip()
        if len(query) < 2:
            self.results.delete(0, "end")
            self.results.grid_remove()
            self.hits = []
            return
        self.set_status(f"Söker efter {query}...")

        def work():
            try:
                hits = app.search_yahoo(query)
            except Exception as exc:
                self.after(0, lambda: self._search_done([], str(exc), query))
                return
            self.after(0, lambda: self._search_done(hits, None, query))

        self._thread(work)

    def _search_done(self, hits, error, query):
        if self.query.get().strip() != query:
            return
        if error:
            self.set_status("")
            messagebox.showerror("Aktier", error)
            return
        self.hits = hits
        self.results.delete(0, "end")
        for hit in hits:
            place = f"   {hit['exchange']}" if hit["exchange"] else ""
            self.results.insert("end", f"{hit['name']}    {hit['symbol']}{place}")
        if hits:
            self.results.grid()
            self.set_status(f"{len(hits)} träffar. Klicka på den aktie du vill ha.")
        else:
            self.results.grid_remove()
            self.set_status("Inga aktier matchade sökningen.")

    def pick_hit(self, _event):
        selected = self.results.curselection()
        if not selected:
            return
        self.chosen = self.hits[selected[0]]
        place = f", {self.chosen['exchange']}" if self.chosen["exchange"] else ""
        self.chosen_label.configure(
            text=f"Vald aktie: {self.chosen['name']} ({self.chosen['symbol']}{place})",
            fg=INK,
        )

    def reload(self, select_id=None, note=None):
        data = app.load()
        for stock in data["stocks"]:
            app.recalc(stock)
        app.save(data)
        stocks = [app.stock_view(stock) for stock in data["stocks"]]
        self._show_total(stocks)
        self.stocks = {stock["id"]: stock for stock in stocks}
        self.tree.delete(*self.tree.get_children())
        for stock in stocks:
            procent, _kronor = plus_mot_insats(stock)
            self.tree.insert(
                "",
                "end",
                iid=stock["id"],
                values=(
                    stock["ticker"],
                    stock["name"],
                    shares_text(stock["totalShares"]),
                    money(stock["grundbelopp"], stock["currency"]),
                    signed_pct(procent),
                ),
            )
        target = select_id or self.selected_id
        if note and target in self.stocks:
            self.stocks[target]["note"] = note
        if target in self.stocks:
            self.tree.selection_set(target)
            self.tree.see(target)
            self.show(self.stocks[target])
        elif stocks:
            self.tree.selection_set(stocks[0]["id"])
            self.show(stocks[0])
        else:
            self.selected_id = None
            self.name_label.configure(text="Inga aktier ännu")
            self.meta_label.configure(text="Sök fram den du vill ha och lägg till den.")
            self.plus_value.configure(text="–", fg=INK)
            self.result_value.configure(text="–", fg=INK)
            self.facts.configure(text="")
            self._clear_history()

    def _show_total(self, stocks):
        if not stocks:
            self.total_label.configure(text="Inga aktier ännu")
            return
        groups = {}
        for stock in stocks:
            currency = stock.get("currency") or "kr"
            bucket = groups.setdefault(currency, {"value": 0.0, "base": 0.0})
            bucket["value"] += float(stock.get("marketValue") or 0)
            bucket["base"] += float(stock.get("grundbelopp") or 0)
        lines = []
        for currency, bucket in groups.items():
            procent = (bucket["value"] - bucket["base"]) / bucket["base"] * 100 if bucket["base"] else None
            lines.append(
                f"Börsvärde {money(bucket['value'], currency)}    "
                f"Betalat {money(bucket['base'], currency)}    "
                f"{signed_pct(procent)}"
            )
        self.total_label.configure(text="\n".join(lines))

    def current(self):
        if not self.selected_id or self.selected_id not in self.stocks:
            messagebox.showinfo("Aktier", "Välj en aktie i listan först.")
            return None
        return self.stocks[self.selected_id]

    def frage_chatgpt(self):
        stock = self.current()
        if not stock:
            return
        app.oppna_chatgpt(stock, med_utdelning=False)

    def on_select(self, _event):
        selected = self.tree.selection()
        if not selected:
            return
        stock = self.stocks.get(selected[0])
        if stock:
            self.show(stock)

    def _farg(self, value):
        if value is None:
            return INK
        return RED if value < 0 else GREEN

    def show(self, stock):
        self.selected_id = stock["id"]
        procent, kronor = plus_mot_insats(stock)
        self.name_label.configure(text=stock["name"])
        self.meta_label.configure(
            text=f"{stock['ticker']}   ·   börskurs {money(stock['price'], stock['currency'])}"
        )
        self.plus_value.configure(text=signed_pct(procent), fg=self._farg(procent))
        self.result_value.configure(text=money(kronor, stock["currency"]), fg=self._farg(kronor))
        facts = [
            f"Antal aktier  {shares_text(stock['totalShares'])}",
            f"Betalat  {money(stock['grundbelopp'], stock['currency'])}",
            f"Snittkurs  {money(stock['avgPaidPrice'], stock['currency'])}",
            f"Börsvärde  {money(stock['marketValue'], stock['currency'])}",
        ]
        if stock.get("note"):
            facts.append(stock["note"])
        self.facts.configure(text="\n".join(facts))
        self._fill_history(stock)

    def _clear_history(self):
        for child in self.history.winfo_children():
            child.destroy()

    def _fill_history(self, stock):
        self._clear_history()
        buys = stock.get("buys") or []
        if not buys:
            tk.Label(self.history, text="Inga köp ännu.", bg=CARD, fg=MUTED, font=("Segoe UI", 10)).pack(anchor="w")
            return
        for index, buy in enumerate(buys):
            self._buy_row(index, buy)

    def _buy_row(self, index, buy):
        row = tk.Frame(self.history, bg="#f6f3ed", padx=10, pady=8, highlightbackground=LINE, highlightthickness=1)
        row.pack(fill="x", pady=4)
        kind = "Såld" if str(buy.get("kind", "")).startswith("sell") else "Köpt"
        tk.Label(row, text=kind, anchor="w", bg="#f6f3ed", fg=INK, font=("Segoe UI", 10, "bold")).pack(anchor="w")
        fields = tk.Frame(row, bg="#f6f3ed")
        fields.pack(anchor="w", fill="x", pady=(6, 6))
        count_box = tk.Frame(fields, bg="#f6f3ed")
        count_box.pack(side="left", padx=(0, 12))
        tk.Label(count_box, text="Antal aktier", bg="#f6f3ed", fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w")
        count = self._entry(count_box, 10)
        count.insert(0, shares_text(buy["shares"]))
        count.pack(anchor="w", pady=(2, 0))
        price_box = tk.Frame(fields, bg="#f6f3ed")
        price_box.pack(side="left")
        price_label = "Försäljningskurs" if str(buy.get("kind", "")).startswith("sell") else "Köpkurs per aktie"
        tk.Label(price_box, text=price_label, bg="#f6f3ed", fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w")
        price = self._entry(price_box, 10)
        price.insert(0, shares_text(buy.get("price") or 0))
        price.pack(anchor="w", pady=(2, 0))
        buttons = tk.Frame(row, bg="#f6f3ed")
        buttons.pack(anchor="w")
        self._button(buttons, "Spara", lambda i=index, c=count, p=price: self.save_buy(i, c, p), primary=True).pack(side="left")
        self._button(buttons, "Ta bort", lambda i=index: self.delete_buy_row(i)).pack(side="left", padx=(8, 0))

    def save_buy(self, index, count, price):
        stock = self.current()
        if not stock:
            return
        buy = (stock.get("buys") or [])[index]
        old_delta = app.kassa_delta(buy.get("kind"), buy.get("shares") or 0, buy.get("price") or 0)
        try:
            new_delta = app.kassa_delta(
                buy.get("kind"),
                app.num(count.get(), "Antal"),
                app.num(price.get(), "Kurs"),
            )
        except Exception as exc:
            messagebox.showerror("Aktier", str(exc))
            return
        skillnad = round(new_delta - old_delta, 2)
        if skillnad and not self._andra_aktie_kontanter(stock, skillnad):
            return
        try:
            updated = app.update_buy(stock["id"], index, count.get(), price.get())
        except Exception as exc:
            if skillnad:
                self._andra_aktie_kontanter(stock, -skillnad)
            messagebox.showerror("Aktier", str(exc))
            return
        self.set_status("Raden är ändrad.")
        self.reload(updated["id"], updated.get("note"))

    def delete_buy_row(self, index):
        stock = self.current()
        if not stock:
            return
        buy = (stock.get("buys") or [])[index]
        if not messagebox.askyesno("Aktier", f"Ta bort {shares_text(buy['shares'])} aktier?"):
            return
        tillbaka = -app.kassa_delta(buy.get("kind"), buy.get("shares") or 0, buy.get("price") or 0)
        if tillbaka and not self._andra_aktie_kontanter(stock, tillbaka):
            return
        try:
            updated = app.delete_buy(stock["id"], index)
        except Exception as exc:
            if tillbaka:
                self._andra_aktie_kontanter(stock, -tillbaka)
            messagebox.showerror("Aktier", str(exc))
            return
        self.set_status("Raden är borttagen.")
        self.reload(updated["id"], updated.get("note"))

    def add_stock(self):
        if not self.chosen:
            messagebox.showinfo("Aktier", "Sök fram aktien och klicka på den i listan.")
            return
        ticker = self.chosen["symbol"]
        shares = self.shares.get().strip()
        price = self.price.get().strip()
        self.add_btn.configure(state="disabled")
        self.set_status(f"Hämtar {ticker} från Yahoo...")

        def work():
            try:
                stock = app.add_stock({"ticker": ticker, "shares": shares, "price": price})
            except Exception as exc:
                self.after(0, lambda: self._add_done(None, str(exc)))
                return
            self.after(0, lambda: self._add_done(stock, None))

        self._thread(work)

    def _add_done(self, stock, error):
        self.add_btn.configure(state="normal")
        if error:
            self.set_status("")
            messagebox.showerror("Aktier", error)
            return
        buy = (stock.get("buys") or [None])[-1]
        if buy and buy.get("kind") == "own" and buy.get("price"):
            delta = app.kassa_delta("own", buy["shares"], buy["price"])
            if not self._andra_aktie_kontanter(stock, delta):
                data = app.load()
                data["stocks"] = [s for s in data["stocks"] if s.get("id") != stock["id"]]
                app.save(data)
                self.reload()
                return
        self.shares.delete(0, "end")
        self.price.delete(0, "end")
        self.set_status(f"{stock['name']} är tillagd.")
        self.reload(stock["id"])

    def buy(self):
        stock = self.current()
        if not stock:
            return
        shares = self.paid_shares.get()
        price = self.paid_price.get()
        reserverat = None
        if str(price or "").strip():
            try:
                reserverat = app.kassa_delta("own", app.num(shares, "Antal"), app.num(price, "Köpkurs"))
            except Exception as exc:
                messagebox.showerror("Aktier", str(exc))
                return
            if not self._andra_aktie_kontanter(stock, reserverat):
                return
        try:
            updated = app.buy(stock["id"], {"kind": "own", "shares": shares, "price": price})
        except Exception as exc:
            if reserverat:
                self._andra_aktie_kontanter(stock, -reserverat)
            messagebox.showerror("Aktier", str(exc))
            return
        self.paid_shares.delete(0, "end")
        self.paid_price.delete(0, "end")
        self.set_status(updated.get("note") or "Köpet är lagt till.")
        self.reload(updated["id"], updated.get("note"))

    def sell(self):
        stock = self.current()
        if not stock:
            return
        try:
            tillagg = app.kassa_delta(
                "sell_own",
                app.num(self.sell_shares.get(), "Antal"),
                app.num(self.sell_price.get(), "Försäljningskurs"),
            )
        except Exception as exc:
            messagebox.showerror("Aktier", str(exc))
            return
        try:
            updated = app.sell(
                stock["id"],
                {"kind": "paid", "shares": self.sell_shares.get(), "price": self.sell_price.get()},
            )
        except Exception as exc:
            messagebox.showerror("Aktier", str(exc))
            return
        if tillagg:
            self._andra_aktie_kontanter(stock, tillagg)
        self.sell_shares.delete(0, "end")
        self.sell_price.delete(0, "end")
        self.set_status(updated.get("note") or "Aktien är såld.")
        self.reload(updated["id"], updated.get("note"))

    def refresh_price(self):
        stock = self.current()
        if not stock:
            return
        self.set_status(f"Uppdaterar {stock['ticker']}...")

        def work():
            try:
                updated = app.refresh(stock["id"])
            except Exception as exc:
                self.after(0, lambda: self._refresh_done(None, str(exc)))
                return
            updated["note"] = "Börskursen är uppdaterad från Yahoo."
            self.after(0, lambda: self._refresh_done(updated, None))

        self._thread(work)

    def _refresh_done(self, stock, error):
        if error:
            self.set_status("")
            messagebox.showerror("Aktier", error)
            return
        self.set_status(f"Börskursen för {stock['ticker']} är uppdaterad.")
        self.reload(stock["id"], stock.get("note"))

    def refresh_all(self):
        self.refresh_all_btn.configure(state="disabled")
        self.set_status("Uppdaterar kurserna...")

        def work():
            try:
                done, failed = app.refresh_all()
            except Exception as exc:
                self.after(0, lambda: self._refresh_all_done(0, [str(exc)]))
                return
            self.after(0, lambda: self._refresh_all_done(done, failed))

        self._thread(work)

    def _refresh_all_done(self, done, failed):
        self.refresh_all_btn.configure(state="normal")
        self.set_status(f"Uppdaterade {done} aktier.")
        self.reload()
        if failed:
            messagebox.showwarning("Aktier", "Kunde inte uppdatera:\n" + "\n".join(failed))

    def remove(self):
        stock = self.current()
        if not stock:
            return
        if not messagebox.askyesno("Aktier", f"Ta bort hela {stock['name']}? Det du betalat för kvarvarande aktier läggs tillbaka i kassan."):
            return
        tillbaka = round(float(stock.get("grundbelopp") or 0), 2)
        if tillbaka and not self._andra_aktie_kontanter(stock, tillbaka):
            return
        data = app.load()
        data["stocks"] = [item for item in data["stocks"] if item["id"] != stock["id"]]
        app.save(data)
        self.selected_id = None
        self.set_status(f"{stock['name']} är borttagen.")
        self.reload()
