# -*- coding: utf-8 -*-
"""Windows-fönster för utdelningskalkylen. Kör den här filen i PyCharm."""

import threading
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, simpledialog, ttk

import utdelning_core as app

BG = "#f4f1eb"
CARD = "#fffcf8"
INK = "#1c1915"
MUTED = "#6d675f"
LINE = "#e6e0d6"
GREEN = "#1f6b45"
RED = "#a32020"
GREEN_SOFT = "#e7f3ec"
FIELD = "#ffffff"

PERIOD = {12: "månad", 4: "kvartal", 2: "halvår", 1: "år"}
MONTHS = {
    1: "Januari",
    2: "Februari",
    3: "Mars",
    4: "April",
    5: "Maj",
    6: "Juni",
    7: "Juli",
    8: "Augusti",
    9: "September",
    10: "Oktober",
    11: "November",
    12: "December",
}


def money(value, currency=""):
    if value is None:
        return "–"
    text = f"{float(value):,.2f}".replace(",", " ").replace(".", ",")
    return f"{text} {currency}".strip()


def pct(value):
    if value is None:
        return "–"
    return f"{float(value):.2f} %".replace(".", ",")


def shares_text(value):
    return f"{float(value):g}"


def _salt_text(value) -> str:
    tal = round(float(value or 0), 2)
    if abs(tal) < 0.005:
        return "0 kr"
    text = f"{abs(tal):,.2f}".replace(",", " ").replace(".", ",")
    if text.endswith(",00"):
        text = text[:-3]
    if tal > 0:
        return f"+{text} kr"
    return f"−{text} kr"


def plus_minus(value, currency) -> str:
    tal = round(float(value or 0), 2)
    if abs(tal) < 0.005:
        return money(0, currency)
    return ("+" if tal > 0 else "−") + money(abs(tal), currency)


def _farg(value) -> str:
    tal = float(value or 0)
    if tal > 0.005:
        return GREEN
    if tal < -0.005:
        return RED
    return INK


class UtdelningApp(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.selected_id = None
        self.hits = []
        self.chosen = None
        self._search_job = None
        self._kontanter = 0.0
        self._satt_kontanter = None
        self._style()
        self._build()
        self.reload()

    def _style(self):
        style = ttk.Style(self)
        style.configure(
            "Aktie.Treeview",
            background=CARD,
            fieldbackground=CARD,
            foreground=INK,
            rowheight=34,
            borderwidth=0,
            font=("Segoe UI", 10),
        )
        style.configure(
            "Aktie.Treeview.Heading",
            background="#efeae2",
            foreground=INK,
            font=("Segoe UI", 10, "bold"),
            relief="flat",
        )
        style.map("Aktie.Treeview", background=[("selected", GREEN_SOFT)], foreground=[("selected", INK)])
        style.layout("Aktie.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        style.configure("Aktie.TCombobox", padding=4)

    def _build(self):
        outer = tk.Frame(self, bg=BG, padx=10, pady=8)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=3)
        outer.columnconfigure(1, weight=4, minsize=440)
        outer.rowconfigure(1, weight=1)

        total = self._card(outer)
        total.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        total_inner = tk.Frame(total, bg=CARD, padx=12, pady=8)
        total_inner.pack(fill="x")

        head = tk.Frame(total_inner, bg=CARD)
        head.pack(fill="x")
        tk.Label(head, text="Hela innehavet", bg=CARD, fg=MUTED, font=("Segoe UI", 9)).pack(side="left")
        actions = tk.Frame(head, bg=CARD)
        actions.pack(side="right")
        self.refresh_all_btn = self._button(actions, "Uppdatera alla", self.refresh_all, compact=True)
        self.refresh_all_btn.pack(side="left")
        self._button(actions, "Spara till fil", self.save_file, compact=True).pack(side="left", padx=(6, 0))
        self._button(actions, "Ladda från fil", self.load_file, compact=True).pack(side="left", padx=(6, 0))

        self.total_rad = tk.Frame(total_inner, bg=CARD)
        self.total_rad.pack(anchor="w", fill="x", pady=(2, 0))
        self._visa_total_tom()

        left_col = tk.Frame(outer, bg=BG)
        left_col.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        left_col.columnconfigure(0, weight=1)
        left_col.rowconfigure(1, weight=1)

        add = self._card(left_col)
        add.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        inner = tk.Frame(add, bg=CARD, padx=10, pady=6)
        inner.pack(fill="x")

        tk.Label(inner, text="Sök aktie", bg=CARD, fg=INK, font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w")
        self.query = self._entry(inner, 28, compact=True)
        self.query.grid(row=1, column=0, sticky="we", padx=(0, 8), pady=(2, 0))
        self.query.bind("<KeyRelease>", self.on_search_type)
        self.query.bind("<Return>", lambda _e: self.search_now())
        self.search_btn = self._button(inner, "Sök", self.search_now, primary=True, compact=True)
        self.search_btn.grid(row=1, column=1, sticky="w", pady=(2, 0))

        self.results = tk.Listbox(
            inner,
            height=3,
            bg=FIELD,
            fg=INK,
            font=("Segoe UI", 10),
            relief="flat",
            highlightthickness=1,
            highlightbackground=LINE,
            selectbackground=GREEN_SOFT,
            selectforeground=INK,
            activestyle="none",
        )
        self.results.grid(row=2, column=0, columnspan=2, sticky="we", pady=(6, 0))
        self.results.grid_remove()
        self.results.bind("<<ListboxSelect>>", self.pick_hit)

        self.chosen_label = tk.Label(inner, text="Ingen aktie vald", bg=CARD, fg=MUTED, font=("Segoe UI", 9), anchor="w")
        self.chosen_label.grid(row=3, column=0, columnspan=2, sticky="we", pady=(3, 2))

        fields = tk.Frame(inner, bg=CARD)
        fields.grid(row=4, column=0, columnspan=2, sticky="w")
        count_box = tk.Frame(fields, bg=CARD)
        count_box.pack(side="left", padx=(0, 12))
        tk.Label(count_box, text="Antal aktier", bg=CARD, fg=INK, font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.shares = self._entry(count_box, 12, compact=True)
        self.shares.pack(anchor="w", pady=(2, 0))
        price_box = tk.Frame(fields, bg=CARD)
        price_box.pack(side="left", padx=(0, 12))
        tk.Label(price_box, text="Köpkurs per aktie", bg=CARD, fg=INK, font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.price = self._entry(price_box, 14, compact=True)
        self.price.pack(anchor="w", pady=(2, 0))
        self.add_btn = self._button(fields, "Lägg till", self.add_stock, primary=True, compact=True)
        self.add_btn.pack(side="left", anchor="s")
        self.status = tk.Label(inner, text="Tom köpkurs använder dagens kurs. Courtage 0,25 %, minst 1 kr, läggs på grundinsatsen.", bg=CARD, fg=MUTED, font=("Segoe UI", 9), anchor="w", justify="left")
        self.status.grid(row=5, column=0, columnspan=2, sticky="we", pady=(3, 0))
        inner.columnconfigure(0, weight=1)

        left = self._card(left_col)
        left.grid(row=1, column=0, sticky="nsew", pady=(0, 6))
        left_inner = tk.Frame(left, bg=CARD, padx=8, pady=6)
        left_inner.pack(fill="both", expand=True)
        columns = ("ticker", "name", "shares", "base", "yoc", "salt")
        self.tree = ttk.Treeview(
            left_inner, columns=columns, show="headings", selectmode="browse", style="Aktie.Treeview",
        )
        headings = (
            ("ticker", "Ticker", 72, False),
            ("name", "Namn", 90, True),
            ("shares", "Antal", 52, False),
            ("base", "Grundbelopp", 96, False),
            ("yoc", "På insatsen", 78, False),
            ("salt", "Sålt", 96, False),
        )
        for key, title, width, stretch in headings:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=width, stretch=stretch, anchor="w" if key in ("ticker", "name") else "e")
        y_scroll = ttk.Scrollbar(left_inner, orient="vertical", command=self.tree.yview)
        self.tree.tag_configure("vinst", foreground=GREEN)
        self.tree.tag_configure("forlust", foreground=RED)
        self.tree.configure(yscrollcommand=y_scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        self.insatt_label = tk.Label(
            left_inner, text="", bg=CARD, fg=MUTED, font=("Segoe UI", 9),
            anchor="w", justify="left",
        )
        self.insatt_label.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self.insatt_label.bind(
            "<Configure>",
            lambda e: self.insatt_label.configure(wraplength=max(180, e.width - 8)),
        )
        self.insatt_label.grid_remove()
        left_inner.rowconfigure(0, weight=1)
        left_inner.columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        kassa_kort = self._card(left_col)
        kassa_kort.grid(row=2, column=0, sticky="ew")
        kassa_inner = tk.Frame(kassa_kort, bg=CARD, padx=8, pady=6)
        kassa_inner.pack(fill="x")
        kassor = tk.Frame(kassa_inner, bg=CARD)
        kassor.pack(fill="x")
        kassor.columnconfigure(0, weight=1, uniform="kassa")
        kassor.columnconfigure(1, weight=1, uniform="kassa")
        self._kassa_ruta(
            kassor, 0,
            "Utdelning och vinst",
            "Utdelning och vinst från sålda aktier läggs hit. Gratisaktier dras härifrån. Ingår i kontots värde.",
            GREEN,
            (("Historik", self.show_history), ("Utdelningskalender", self.show_calendar)),
            "cash_label",
            compact=True,
        )
        self._kassa_ruta(
            kassor, 1,
            "Kontantkassa",
            "Pengar utanför aktierna. Ingår i kontots värde.",
            INK,
            (("Rätta", self._ratta_kontanter), ("Insättning", self._gor_insattning)),
            "kontant_label",
            compact=True,
        )

        tk.Frame(kassa_inner, bg=LINE, height=1).pack(fill="x", pady=(6, 6))
        form = tk.Frame(kassa_inner, bg=CARD)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        tk.Label(form, text="Ny utdelning", bg=CARD, fg=INK, font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w")
        self.cash = self._entry(form, 8, compact=True)
        self.cash.grid(row=0, column=1, sticky="w", padx=(8, 6))
        self.cash.bind("<Return>", lambda _e: self.add_cash())
        tk.Label(form, text="datum", bg=CARD, fg=MUTED, font=("Segoe UI", 9)).grid(row=0, column=2, sticky="w")
        self.cash_date = self._entry(form, 11, compact=True)
        self.cash_date.grid(row=0, column=3, sticky="w", padx=(6, 6))
        self.cash_date.bind("<Return>", lambda _e: self.add_cash())
        self._button(form, "Lägg till", self.add_cash, primary=True, compact=True).grid(row=0, column=4, sticky="w")
        tk.Label(form, text="från", bg=CARD, fg=MUTED, font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.cash_source = ttk.Combobox(
            form, state="readonly", width=22, font=("Segoe UI", 9), style="Aktie.TCombobox",
        )
        self.cash_source.grid(row=1, column=1, columnspan=3, sticky="ew", padx=(8, 6), pady=(4, 0))
        self._button(form, "Rätta saldo", self.save_cash, compact=True).grid(row=1, column=4, sticky="w", pady=(4, 0))
        self.sources = {}
        self._reset_date()

        right = self._card(outer)
        right.grid(row=1, column=1, sticky="nsew")
        canvas = tk.Canvas(right, bg=CARD, highlightthickness=0, bd=0)
        side_scroll = ttk.Scrollbar(right, orient="vertical", command=canvas.yview)
        side = tk.Frame(canvas, bg=CARD, padx=12, pady=8)
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
        self.name_label = tk.Label(name_row, text="Inga aktier ännu", bg=CARD, fg=INK, font=("Segoe UI", 16, "bold"), anchor="w", justify="left")
        self.name_label.pack(side="left", fill="x", expand=True)
        self._button(name_row, "Ta bort hela aktien", self.remove, compact=True).pack(side="right", anchor="n")
        knapp_rad = tk.Frame(side, bg=CARD)
        knapp_rad.pack(anchor="w", pady=(4, 0))
        self._button(knapp_rad, "Uppdatera börskurs", self.refresh_price, compact=True).pack(side="left")
        self._button(knapp_rad, "Fråga ChatGPT", self.frage_chatgpt, compact=True).pack(side="left", padx=(8, 0))
        self.meta_label = tk.Label(side, text="Sök fram den du vill ha och lägg till den.", bg=CARD, fg=MUTED, font=("Segoe UI", 10), anchor="w", justify="left")
        self.meta_label.pack(anchor="w", fill="x", pady=(2, 4))
        self.name_label.bind("<Configure>", lambda e: self.name_label.configure(wraplength=max(200, e.width - 8)))
        self.meta_label.bind("<Configure>", lambda e: self.meta_label.configure(wraplength=max(200, e.width - 8)))

        metrics = tk.Frame(side, bg=CARD)
        metrics.pack(fill="x", pady=(0, 4))
        self.cost_value = self._metric(metrics, "Avkastning på investerat kapital", GREEN)
        self.market_value = self._metric(metrics, "Direktavkastning på kursen", INK)
        self.cost_value.master.pack(side="left", fill="both", expand=True, padx=(0, 8))
        self.market_value.master.pack(side="left", fill="both", expand=True)

        self.facts = tk.Label(side, text="", bg=CARD, fg=INK, font=("Segoe UI", 10), anchor="w", justify="left")
        self.facts.pack(anchor="w", fill="x", pady=(2, 0))
        self.facts.bind("<Configure>", lambda e: self.facts.configure(wraplength=max(200, e.width - 8)))

        self._section(side, "Köp gratisaktier för utdelningen")
        tk.Label(side, text="De höjer inte grundbeloppet. Kostnad plus courtage dras från utdelningskassan.", bg=CARD, fg=MUTED, font=("Segoe UI", 9), anchor="w").pack(anchor="w")
        free_row = tk.Frame(side, bg=CARD)
        free_row.pack(anchor="w", fill="x", pady=(2, 2))
        free_count, self.free_shares = self._labeled(free_row, "Antal aktier", "", 12)
        free_count.pack(side="left", padx=(0, 12))
        free_price, self.free_price = self._labeled(free_row, "Kurs per aktie", "", 12)
        free_price.pack(side="left")
        self._button(side, "Lägg till gratis", lambda: self.buy("dividend"), primary=True, compact=True).pack(anchor="w", pady=(2, 0))
        tk.Label(side, text="Tom kurs använder dagens börskurs.", bg=CARD, fg=MUTED, font=("Segoe UI", 9), anchor="w").pack(anchor="w", pady=(1, 0))

        self._section(side, "Lägg till aktier du betalar för")
        paid_row = tk.Frame(side, bg=CARD)
        paid_row.pack(anchor="w", fill="x", pady=(2, 2))
        paid_count, self.paid_shares = self._labeled(paid_row, "Antal aktier", "", 12)
        paid_count.pack(side="left", padx=(0, 12))
        paid_price, self.paid_price = self._labeled(paid_row, "Köpkurs per aktie", "", 12)
        paid_price.pack(side="left")
        self._button(side, "Lägg till betalda", lambda: self.buy("own"), primary=True, compact=True).pack(anchor="w", pady=(2, 0))
        tk.Label(side, text="Courtage 0,25 %, minst 1 kr, räknas in i grundinsatsen.", bg=CARD, fg=MUTED, font=("Segoe UI", 9), anchor="w").pack(anchor="w", pady=(1, 0))

        self._section(side, "Sälj aktier")
        sell_row = tk.Frame(side, bg=CARD)
        sell_row.pack(anchor="w", fill="x", pady=(2, 2))
        sell_count, self.sell_shares = self._labeled(sell_row, "Antal aktier", "", 12)
        sell_count.pack(side="left", padx=(0, 12))
        sell_price, self.sell_price = self._labeled(sell_row, "Försäljningskurs", "", 12)
        sell_price.pack(side="left")
        sell_buttons = tk.Frame(side, bg=CARD)
        sell_buttons.pack(anchor="w", pady=(2, 0))
        self._button(sell_buttons, "Sälj betalda", lambda: self.sell("paid"), compact=True).pack(side="left")
        self._button(sell_buttons, "Sälj gratis", lambda: self.sell("free"), compact=True).pack(side="left", padx=(8, 0))
        self.trans_btn = self._button(side, "Transaktioner", self.show_transactions, compact=True)
        self.trans_btn.pack(anchor="w", pady=(8, 0))
        self._trans_window = None
        self.history = None

    def _reset_date(self):
        self.cash_date.delete(0, "end")
        self.cash_date.insert(0, datetime.now().strftime("%Y-%m-%d"))

    def _fill_sources(self, stocks):
        blank = "Ingen särskild aktie"
        self.sources = {blank: ""}
        for stock in stocks:
            self.sources[f"{stock['name']} ({stock['ticker']})"] = stock["id"]
        self.cash_source.configure(values=list(self.sources))
        if self.cash_source.get() not in self.sources:
            self.cash_source.set(blank)

    def _metric(self, parent, caption, color):
        box = tk.Frame(parent, bg="#f6f3ed", padx=10, pady=6, highlightbackground=LINE, highlightthickness=1)
        tk.Label(box, text=caption, bg="#f6f3ed", fg=MUTED, font=("Segoe UI", 9), anchor="w").pack(anchor="w")
        value = tk.Label(box, text="–", bg="#f6f3ed", fg=color, font=("Segoe UI", 22, "bold"), anchor="w")
        value.pack(anchor="w", pady=(1, 0))
        return value

    def _card(self, parent):
        return tk.Frame(parent, bg=CARD, highlightbackground=LINE, highlightthickness=1)

    def _kassa_ruta(self, parent, column, title, hint, color, buttons, label_name, compact=False):
        box = tk.Frame(
            parent, bg="#f6f3ed",
            padx=8 if compact else 12,
            pady=4 if compact else 10,
            highlightbackground=LINE, highlightthickness=1,
        )
        box.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 6, 0))
        tk.Label(box, text=title, bg="#f6f3ed", fg=MUTED, font=("Segoe UI", 8 if compact else 9)).pack(anchor="w")
        label = tk.Label(box, text="0 kr", bg="#f6f3ed", fg=color, font=("Segoe UI", 13 if compact else 16, "bold"))
        label.pack(anchor="w", pady=(0, 0))
        setattr(self, label_name, label)
        hint_label = tk.Label(
            box, text=hint, bg="#f6f3ed", fg=MUTED,
            font=("Segoe UI", 8 if compact else 9),
            anchor="w", justify="left", wraplength=220 if compact else 420,
        )
        hint_label.pack(anchor="w", fill="x")
        if compact:
            box.bind(
                "<Configure>",
                lambda e, lab=hint_label: lab.configure(wraplength=max(80, e.width - 24)),
            )
        row = tk.Frame(box, bg="#f6f3ed")
        row.pack(anchor="w", pady=(4 if compact else 8, 0))
        for index, (text, command) in enumerate(buttons):
            self._button(row, text, command, compact=compact).pack(side="left", padx=(0 if index == 0 else 6, 0))

    def _labeled(self, parent, title, hint, width):
        box = tk.Frame(parent, bg=CARD)
        tk.Label(box, text=title, bg=CARD, fg=INK, font=("Segoe UI", 9, "bold"), anchor="w").pack(anchor="w")
        if hint:
            tk.Label(box, text=hint, bg=CARD, fg=MUTED, font=("Segoe UI", 9), anchor="w", justify="left").pack(anchor="w")
        entry = self._entry(box, width)
        entry.pack(anchor="w", fill="x", pady=(2, 0))
        return box, entry

    def _entry(self, parent, width, compact=False):
        return tk.Entry(
            parent,
            width=width,
            bg=FIELD,
            fg=INK,
            relief="flat",
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=GREEN,
            font=("Segoe UI", 10 if compact else 12),
            insertbackground=INK,
        )

    def _button(self, parent, text, command, primary=False, compact=False):
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=GREEN if primary else CARD,
            fg="#ffffff" if primary else INK,
            activebackground="#185538" if primary else "#f3efe8",
            activeforeground="#ffffff" if primary else INK,
            relief="flat",
            bd=0,
            padx=10 if compact else 12,
            pady=3 if compact else 8,
            font=("Segoe UI", 9 if compact else 10, "bold" if primary else "normal"),
            cursor="hand2",
            highlightthickness=1,
            highlightbackground=GREEN if primary else LINE,
        )

    def _section(self, parent, text):
        tk.Label(parent, text=text, bg=CARD, fg=INK, font=("Segoe UI", 11, "bold"), anchor="w").pack(anchor="w", fill="x", pady=(8, 1))

    def set_status(self, text):
        self.status.configure(text=text)

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

        threading.Thread(target=work, daemon=True).start()

    def _search_done(self, hits, error, query):
        if self.query.get().strip() != query:
            return
        if error:
            self.set_status("")
            messagebox.showerror("Utdelning", error)
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

    def koppla_insattning(self, callback) -> None:
        self._on_insattning = callback

    def _gor_insattning(self) -> None:
        callback = getattr(self, "_on_insattning", None)
        if callback:
            callback()

    def visa_insatt(self, belopp) -> None:
        """Visar överföringar hit sedan programmet började. Summan räknas inte en gång till."""
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
            messagebox.showerror("Utdelning", "Skriv ett belopp, till exempel 5000.")
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
                "Utdelning",
                f"Kontantkassan har {app.amount_text(self._kontanter)} kr. "
                "Det räcker inte. Rätta kassan så den stämmer, eller för över pengar först.",
            )
            return False
        self._kontanter = nytt
        self._satt_kontanter(self._kontanter)
        self._rita_kontanter()
        return True

    def reload(self, select_id=None, note=None):
        data = app.load()
        for stock in data["stocks"]:
            app.recalc(stock)
        app.save(data)
        self.cash_label.configure(text=money(data.get("cash") or 0, "kr"))
        stocks = [app.stock_view(stock) for stock in data["stocks"]]
        self._fill_sources(stocks)
        self._show_total(stocks)
        self.stocks = {stock["id"]: stock for stock in stocks}
        self.tree.delete(*self.tree.get_children())
        for stock in stocks:
            resultat = float(stock.get("realiserat") or 0)
            if resultat > 0.005:
                tagg = ("vinst",)
            elif resultat < -0.005:
                tagg = ("forlust",)
            else:
                tagg = ()
            self.tree.insert(
                "",
                "end",
                iid=stock["id"],
                tags=tagg,
                values=(
                    stock["ticker"],
                    stock["name"],
                    shares_text(stock["totalShares"]),
                    money(stock["grundbelopp"], stock["currency"]),
                    pct(stock["yieldOnCost"]),
                    _salt_text(resultat),
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
            self.cost_value.configure(text="–")
            self.market_value.configure(text="–")
            self.facts.configure(text="")
            self._clear_history()

    def _visa_total_tom(self):
        for barn in self.total_rad.winfo_children():
            barn.destroy()
        tk.Label(
            self.total_rad, text="Inga aktier ännu", bg=CARD, fg=INK,
            font=("Segoe UI", 12, "bold"), anchor="w",
        ).pack(side="left")

    def _show_total(self, stocks):
        for barn in self.total_rad.winfo_children():
            barn.destroy()
        if not stocks:
            self._visa_total_tom()
            return
        groups = {}
        for stock in stocks:
            currency = stock.get("currency") or "kr"
            bucket = groups.setdefault(currency, {"value": 0.0, "base": 0.0, "income": 0.0, "salt": 0.0})
            bucket["value"] += float(stock.get("marketValue") or 0)
            bucket["base"] += float(stock.get("grundbelopp") or 0)
            bucket["income"] += float(stock.get("annualIncome") or 0)
            bucket["salt"] += float(stock.get("realiserat") or 0)
        font = ("Segoe UI", 12, "bold")
        for currency, bucket in groups.items():
            rad = tk.Frame(self.total_rad, bg=CARD)
            rad.pack(anchor="w", fill="x")
            yoc = bucket["income"] / bucket["base"] * 100 if bucket["base"] else None
            delar = (
                f"Börsvärde {money(bucket['value'], currency)}",
                f"Grundinsats {money(bucket['base'], currency)}",
                f"Utdelning/år {money(bucket['income'], currency)}",
                f"På insatsen {pct(yoc)}",
            )
            for text in delar:
                tk.Label(rad, text=text, bg=CARD, fg=INK, font=font).pack(side="left", padx=(0, 10))
            rad2 = tk.Frame(self.total_rad, bg=CARD)
            rad2.pack(anchor="w", fill="x", pady=(2, 0))
            nu = bucket["value"] - bucket["base"]
            tk.Label(
                rad2, text=f"Plus/minus nu {self._utveckling(bucket['value'], bucket['base'], currency)}",
                bg=CARD, fg=_farg(nu), font=font,
            ).pack(side="left", padx=(0, 16))
            tk.Label(
                rad2, text=f"Resultat sålda {plus_minus(bucket['salt'], currency)}",
                bg=CARD, fg=_farg(bucket["salt"]), font=font,
            ).pack(side="left")

    def _utveckling(self, varde: float, grund: float, currency: str) -> str:
        """Börsvärde mot grundinsatsen i kronor och procent. Gratisaktier har ingen grundinsats och räknas som plus."""
        kr = plus_minus(varde - grund, currency)
        if grund <= 0:
            return f"{kr} (bara gratisaktier)" if varde > 0 else kr
        tal = (varde - grund) / grund * 100
        tecken = "+" if tal > 0.005 else ("−" if tal < -0.005 else "")
        return f"{kr} ({tecken}{abs(tal):.2f} %)".replace(".", ",")

    def current(self):
        if not self.selected_id or self.selected_id not in self.stocks:
            messagebox.showinfo("Utdelning", "Välj en aktie i listan först.")
            return None
        return self.stocks[self.selected_id]

    def on_select(self, _event):
        selected = self.tree.selection()
        if not selected:
            return
        stock = self.stocks.get(selected[0])
        if stock:
            self.show(stock)

    def show(self, stock):
        self.selected_id = stock["id"]
        every = PERIOD.get(stock["periodsPerYear"], "period")
        self.name_label.configure(text=stock["name"])
        self.meta_label.configure(
            text=f"{stock['ticker']}   ·   börskurs {money(stock['price'], stock['currency'])}   ·   utdelning {money(stock['dividendPerPeriod'], stock['currency'])} per {every}"
        )
        self.cost_value.configure(text=pct(stock["yieldOnCost"]))
        self.market_value.configure(text=pct(stock["marketYield"]))
        facts = [
            f"Betalda aktier  {shares_text(stock['paidShares'])}",
            f"Gratisaktier  {shares_text(stock['freeShares'])}",
            f"Grundinsats  {money(stock['grundbelopp'], stock['currency'])}",
            f"Snittkurs betalda  {money(stock['avgPaidPrice'], stock['currency'])}",
            f"Snittkurs med gratisaktier  {money(stock['avgAllPrice'], stock['currency'])}",
            f"Börsvärde  {money(stock['marketValue'], stock['currency'])}",
            f"Värde gratisaktier  {money(float(stock['freeShares'] or 0) * float(stock['price'] or 0), stock['currency'])}",
            f"Plus/minus nu  {self._utveckling(float(stock['marketValue'] or 0), float(stock['grundbelopp'] or 0), stock['currency'])}",
            f"Resultat sålda  {plus_minus(stock.get('realiserat'), stock['currency'])}",
            f"Utdelning per år  {money(stock['annualIncome'], stock['currency'])}",
        ]
        if stock.get("note"):
            facts.append(stock["note"])
        self.facts.configure(text="\n".join(facts))
        antal = len(stock.get("buys") or [])
        self.trans_btn.configure(text=f"Transaktioner ({antal})" if antal else "Transaktioner")
        self._fill_history(stock)

    def _trans_oppen(self) -> bool:
        return self._trans_window is not None and self._trans_window.winfo_exists()

    def show_transactions(self):
        stock = self.current()
        if not stock:
            return
        if self._trans_oppen():
            self._trans_window.lift()
            self._fill_history(stock)
            return
        window = tk.Toplevel(self)
        window.title("Transaktioner")
        window.configure(bg=BG)
        window.geometry("640x520")
        window.minsize(520, 360)
        window.transient(self.winfo_toplevel())
        self._trans_window = window

        ram = tk.Frame(window, bg=BG, padx=14, pady=12)
        ram.pack(fill="both", expand=True)
        self._trans_rubrik = tk.Label(ram, text="", bg=BG, fg=INK, font=("Segoe UI", 13, "bold"), anchor="w")
        self._trans_rubrik.pack(anchor="w")
        tk.Label(
            ram,
            text="Betalda, gratis och sålda. Ändra antal eller kurs och spara, eller ta bort raden.",
            bg=BG, fg=MUTED, font=("Segoe UI", 9), anchor="w",
        ).pack(anchor="w", pady=(2, 8))

        yta = tk.Frame(ram, bg=BG)
        yta.pack(fill="both", expand=True)
        canvas = tk.Canvas(yta, bg=BG, highlightthickness=0, bd=0)
        scroll = ttk.Scrollbar(yta, orient="vertical", command=canvas.yview)
        lista = tk.Frame(canvas, bg=BG)
        lista.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        win_id = canvas.create_window((0, 0), window=lista, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win_id, width=e.width))
        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", lambda ev: canvas.yview_scroll(int(-ev.delta / 120), "units")))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))
        self.history = lista

        def stang():
            canvas.unbind_all("<MouseWheel>")
            window.destroy()
            self._trans_window = None
            self.history = None

        window.protocol("WM_DELETE_WINDOW", stang)
        self._button(ram, "Stäng", stang, compact=True).pack(anchor="w", pady=(8, 0))
        self._fill_history(stock)

    def _clear_history(self):
        if self.history is None or not self.history.winfo_exists():
            return
        for child in self.history.winfo_children():
            child.destroy()

    def _fill_history(self, stock):
        if not self._trans_oppen():
            return
        self._trans_rubrik.configure(text=stock.get("name") or "Transaktioner")
        self._clear_history()
        buys = stock.get("buys") or []
        if not buys:
            tk.Label(self.history, text="Inga transaktioner ännu.", bg=BG, fg=MUTED, font=("Segoe UI", 10)).pack(anchor="w")
            return
        for index, buy in enumerate(buys):
            self._buy_row(index, buy)

    def _buy_row(self, index, buy):
        row = tk.Frame(self.history, bg="#f6f3ed", padx=10, pady=6, highlightbackground=LINE, highlightthickness=1)
        row.pack(fill="x", pady=(0, 6))
        kind = {
            "own": "Betald",
            "dividend": "Gratis",
            "sell_own": "Såld, betald",
            "sell_free": "Såld, gratis",
        }.get(buy.get("kind"), "Köp")
        tk.Label(row, text=kind, anchor="w", bg="#f6f3ed", fg=INK, font=("Segoe UI", 10, "bold")).pack(anchor="w")
        fields = tk.Frame(row, bg="#f6f3ed")
        fields.pack(anchor="w", fill="x", pady=(4, 4))
        count_box = tk.Frame(fields, bg="#f6f3ed")
        count_box.pack(side="left", padx=(0, 12))
        tk.Label(count_box, text="Antal aktier", bg="#f6f3ed", fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w")
        count = self._entry(count_box, 10, compact=True)
        count.insert(0, shares_text(buy["shares"]))
        count.pack(anchor="w", pady=(2, 0))
        price = None
        if buy.get("kind") in ("own", "sell_own", "sell_free", "dividend"):
            price_box = tk.Frame(fields, bg="#f6f3ed")
            price_box.pack(side="left")
            price_label = "Försäljningskurs" if str(buy.get("kind")).startswith("sell") else "Kurs per aktie"
            tk.Label(price_box, text=price_label, bg="#f6f3ed", fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w")
            price = self._entry(price_box, 10, compact=True)
            price.insert(0, shares_text(buy.get("price") or 0))
            price.pack(anchor="w", pady=(2, 0))
        buttons = tk.Frame(row, bg="#f6f3ed")
        buttons.pack(anchor="w")
        self._button(buttons, "Spara", lambda i=index, c=count, p=price: self.save_buy(i, c, p), primary=True, compact=True).pack(side="left")
        self._button(buttons, "Ta bort", lambda i=index: self.delete_buy_row(i), compact=True).pack(side="left", padx=(8, 0))

    def save_buy(self, index, count, price):
        stock = self.current()
        if not stock:
            return
        buy = (stock.get("buys") or [])[index]
        if "utdelning_del" in buy:
            try:
                updated = app.update_buy(stock["id"], index, count.get(), "" if price is None else price.get())
            except Exception as exc:
                messagebox.showerror("Utdelning", str(exc))
                return
            diff = float(updated.get("kontantDiff") or 0)
            if diff:
                self._andra_aktie_kontanter(stock, diff)
            self.set_status(updated.get("note") or "Köpet är ändrat.")
            self.reload(updated["id"], updated.get("note"))
            return
        old_delta = 0.0
        new_delta = 0.0
        if buy.get("kind") in ("own", "sell_own", "sell_free"):
            try:
                old_delta = app.kassa_delta(buy.get("kind"), buy.get("shares") or 0, buy.get("price") or 0)
                new_delta = app.kassa_delta(
                    buy.get("kind"),
                    app.num(count.get(), "Antal"),
                    app.num(price.get() if price is not None else 0, "Kurs"),
                )
            except Exception as exc:
                messagebox.showerror("Utdelning", str(exc))
                return
        skillnad = round(new_delta - old_delta, 2)
        if skillnad and not self._andra_aktie_kontanter(stock, skillnad):
            return
        try:
            updated = app.update_buy(stock["id"], index, count.get(), "" if price is None else price.get())
        except Exception as exc:
            if skillnad:
                self._andra_aktie_kontanter(stock, -skillnad)
            messagebox.showerror("Utdelning", str(exc))
            return
        self.set_status(updated.get("note") or "Köpet är ändrat.")
        self.reload(updated["id"], updated.get("note"))

    def delete_buy_row(self, index):
        stock = self.current()
        if not stock:
            return
        buy = (stock.get("buys") or [])[index]
        slag = {
            "own": "betalda",
            "dividend": "gratis",
            "sell_own": "sålda betalda",
            "sell_free": "sålda gratis",
        }.get(buy.get("kind"), "")
        if not messagebox.askyesno("Utdelning", f"Ta bort {shares_text(buy['shares'])} {slag} aktier?"):
            return
        if "utdelning_del" in buy:
            netto = app.forsaljning_netto(buy.get("kind"), buy.get("shares") or 0, buy.get("price") or 0)
            tillbaka = -round(netto - float(buy.get("utdelning_del") or 0), 2)
        else:
            tillbaka = -app.kassa_delta(buy.get("kind"), buy.get("shares") or 0, buy.get("price") or 0)
        if tillbaka and not self._andra_aktie_kontanter(stock, tillbaka):
            return
        try:
            updated = app.delete_buy(stock["id"], index)
        except Exception as exc:
            if tillbaka:
                self._andra_aktie_kontanter(stock, -tillbaka)
            messagebox.showerror("Utdelning", str(exc))
            return
        self.set_status(updated.get("note") or "Köpet är borttaget.")
        self.reload(updated["id"], updated.get("note"))

    def frage_chatgpt(self):
        stock = self.current()
        if not stock:
            return
        app.oppna_chatgpt(stock, med_utdelning=True)

    def add_stock(self):
        if not self.chosen:
            messagebox.showinfo("Utdelning", "Sök fram aktien och klicka på den i listan.")
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

        threading.Thread(target=work, daemon=True).start()

    def _add_done(self, stock, error):
        self.add_btn.configure(state="normal")
        if error:
            self.set_status("")
            messagebox.showerror("Utdelning", error)
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

    def buy(self, kind):
        stock = self.current()
        if not stock:
            return
        shares = self.free_shares.get() if kind == "dividend" else self.paid_shares.get()
        price = self.free_price.get() if kind == "dividend" else self.paid_price.get()
        reserverat = None
        if kind == "own" and str(price or "").strip():
            try:
                reserverat = app.kassa_delta(
                    "own",
                    app.num(shares, "Antal"),
                    app.num(price, "Köpkurs"),
                )
            except Exception as exc:
                messagebox.showerror("Utdelning", str(exc))
                return
            if not self._andra_aktie_kontanter(stock, reserverat):
                return
        try:
            updated = app.buy(stock["id"], {"kind": kind, "shares": shares, "price": price})
        except Exception as exc:
            if reserverat:
                self._andra_aktie_kontanter(stock, -reserverat)
            messagebox.showerror("Utdelning", str(exc))
            return
        if kind == "own" and reserverat is None:
            data = app.load()
            sparad = next((s for s in data["stocks"] if s.get("id") == stock["id"]), None)
            last = (sparad.get("buys") or [None])[-1] if sparad else None
            if last and last.get("kind") == "own":
                delta = app.kassa_delta("own", last["shares"], last.get("price") or 0)
                if not self._andra_aktie_kontanter(stock, delta):
                    app.delete_buy(stock["id"], len(sparad["buys"]) - 1)
                    self.reload(stock["id"])
                    return
        if kind == "dividend":
            self.free_shares.delete(0, "end")
            self.free_price.delete(0, "end")
        else:
            self.paid_shares.delete(0, "end")
            self.paid_price.delete(0, "end")
            updated.setdefault("note", "De betalda aktierna höjde grundinsatsen, inklusive courtage.")
        if updated.get("note"):
            self.set_status(updated["note"])
        self.reload(updated["id"], updated.get("note"))

    def sell(self, kind):
        stock = self.current()
        if not stock:
            return
        try:
            updated = app.sell(
                stock["id"],
                {"kind": kind, "shares": self.sell_shares.get(), "price": self.sell_price.get()},
                till_utdelning=True,
            )
        except Exception as exc:
            messagebox.showerror("Utdelning", str(exc))
            return
        kontant_del = float(updated.get("kontantDel") or 0)
        if kontant_del:
            self._andra_aktie_kontanter(stock, kontant_del)
        self.sell_shares.delete(0, "end")
        self.sell_price.delete(0, "end")
        if updated.get("note"):
            self.set_status(updated["note"])
        self.reload(updated["id"], updated.get("note"))

    def add_cash(self):
        source = self.sources.get(self.cash_source.get(), "")
        try:
            pot = app.add_cash(self.cash.get(), source, self.cash_date.get())
        except Exception as exc:
            messagebox.showerror("Utdelning", str(exc))
            return
        self.cash.delete(0, "end")
        self._reset_date()
        self.set_status(f"Utdelningskassan är nu {money(pot, 'kr')}.")
        self.reload()

    def save_cash(self):
        typed = self.cash.get().strip()
        if not typed and not messagebox.askyesno("Utdelning", "Nolla utdelningskassan?"):
            return
        try:
            pot = app.set_cash(typed)
        except Exception as exc:
            messagebox.showerror("Utdelning", str(exc))
            return
        self.cash.delete(0, "end")
        if pot:
            self.set_status(f"Utdelningskassan är rättad till {money(pot, 'kr')}.")
        else:
            self.set_status("Utdelningskassan är nollad.")
        self.reload()

    def show_history(self):
        window = tk.Toplevel(self)
        window.title("Utdelningskassan")
        window.configure(bg=BG)
        window.geometry("720x480")
        window.minsize(560, 360)
        window.transient(self)

        frame = tk.Frame(window, bg=BG, padx=14, pady=12)
        frame.pack(fill="both", expand=True)
        summary = tk.Label(frame, text="", bg=BG, fg=INK, font=("Segoe UI", 12, "bold"), anchor="w")
        summary.pack(anchor="w", pady=(0, 8))

        table_box = tk.Frame(frame, bg=BG)
        table_box.pack(fill="both", expand=True)
        columns = ("date", "stock", "text", "amount")
        table = ttk.Treeview(
            table_box, columns=columns, show="headings", selectmode="browse", style="Aktie.Treeview",
        )
        for key, title, width, anchor in (
            ("date", "Datum", 90, "w"),
            ("stock", "Aktie", 180, "w"),
            ("text", "Händelse", 250, "w"),
            ("amount", "Belopp", 100, "e"),
        ):
            table.heading(key, text=title)
            table.column(key, width=width, minwidth=width, anchor=anchor, stretch=key == "text")
        scroll = ttk.Scrollbar(table_box, orient="vertical", command=table.yview)
        table.configure(yscrollcommand=scroll.set)
        table.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        table_box.rowconfigure(0, weight=1)
        table_box.columnconfigure(0, weight=1)
        table.tag_configure("in", foreground=GREEN)
        table.tag_configure("out", foreground=MUTED)

        buttons = tk.Frame(frame, bg=BG)
        buttons.pack(anchor="w", pady=(10, 0))

        def fill():
            rows, pot = app.cash_history()
            table.delete(*table.get_children())
            for index, row in enumerate(rows):
                table.insert(
                    "",
                    "end",
                    iid=row["id"] or f"rad{index}",
                    values=(row["date"], row["stock"], row["text"], money(row["amount"], "kr")),
                    tags=("in" if row["amount"] >= 0 else "out",),
                )
            received = sum(row["amount"] for row in rows if row["amount"] > 0)
            spent = -sum(row["amount"] for row in rows if row["amount"] < 0)
            summary.configure(
                text=f"Kassa {money(pot, 'kr')}    Fått {money(received, 'kr')}    "
                f"Köpt för {money(spent, 'kr')}"
            )

        def remove():
            selected = table.selection()
            if not selected:
                messagebox.showinfo("Utdelning", "Markera en utdelning i listan.", parent=window)
                return
            entry_id = selected[0]
            if entry_id.startswith("rad"):
                messagebox.showinfo(
                    "Utdelning",
                    "Den raden är ett gratisköp. Ändra eller ta bort det under Dina köp på aktien.",
                    parent=window,
                )
                return
            if not messagebox.askyesno(
                "Utdelning",
                "Ta bort utdelningen? Beloppet dras från kassan.",
                parent=window,
            ):
                return
            try:
                app.delete_dividend(entry_id)
            except Exception as exc:
                messagebox.showerror("Utdelning", str(exc), parent=window)
                return
            fill()
            self.reload()

        self._button(buttons, "Ta bort utdelning", remove).pack(side="left")
        self._button(buttons, "Stäng", window.destroy).pack(side="left", padx=(8, 0))
        fill()

    def show_calendar(self):
        rows = app.dividend_calendar()
        window = tk.Toplevel(self)
        window.title("Utdelningskalender")
        window.configure(bg=BG)
        window.geometry("680x520")
        window.minsize(560, 380)
        window.transient(self)

        frame = tk.Frame(window, bg=BG, padx=14, pady=12)
        frame.pack(fill="both", expand=True)
        total = sum(row["amount"] for row in rows)
        months = len({(row["year"], row["month"]) for row in rows})
        headline = "Ingen känd utdelning framåt" if not rows else (
            f"Nästa 12 månader {money(total, 'kr')}    "
            f"snitt {money(total / 12, 'kr')} per månad"
        )
        tk.Label(frame, text=headline, bg=BG, fg=INK, font=("Segoe UI", 12, "bold"), anchor="w").pack(anchor="w")
        tk.Label(
            frame,
            text="Bygger på Yahoos utbetalningar och ditt antal aktier idag. Månader som redan betalats visas inte.",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 9),
            anchor="w",
            justify="left",
        ).pack(anchor="w", pady=(2, 8))

        table_box = tk.Frame(frame, bg=BG)
        table_box.pack(fill="both", expand=True)
        table = ttk.Treeview(
            table_box, columns=("per", "shares", "amount"), show="tree headings", style="Aktie.Treeview",
        )
        table.heading("#0", text="Månad och aktie")
        table.heading("per", text="Per aktie")
        table.heading("shares", text="Antal")
        table.heading("amount", text="Belopp")
        table.column("#0", width=270, minwidth=200, stretch=True)
        table.column("per", width=90, minwidth=90, anchor="e", stretch=False)
        table.column("shares", width=70, minwidth=70, anchor="e", stretch=False)
        table.column("amount", width=110, minwidth=110, anchor="e", stretch=False)
        scroll = ttk.Scrollbar(table_box, orient="vertical", command=table.yview)
        table.configure(yscrollcommand=scroll.set)
        table.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        table_box.rowconfigure(0, weight=1)
        table_box.columnconfigure(0, weight=1)
        table.tag_configure("month", font=("Segoe UI", 10, "bold"))

        current = None
        parent = ""
        for row in rows:
            key = (row["year"], row["month"])
            if key != current:
                current = key
                month_sum = sum(item["amount"] for item in rows if (item["year"], item["month"]) == key)
                parent = table.insert(
                    "",
                    "end",
                    text=f"{MONTHS[row['month']]} {row['year']}",
                    values=("", "", money(month_sum, "kr")),
                    open=True,
                    tags=("month",),
                )
            table.insert(
                parent,
                "end",
                text=f"   {row['name']}",
                values=(
                    money(row["perShare"], row["currency"]),
                    shares_text(row["shares"]),
                    money(row["amount"], row["currency"]),
                ),
            )

        bottom = tk.Frame(frame, bg=BG)
        bottom.pack(anchor="w", pady=(10, 0))
        if rows:
            tk.Label(
                bottom,
                text=f"{months} månader med utdelning",
                bg=BG,
                fg=MUTED,
                font=("Segoe UI", 9),
            ).pack(side="left", padx=(0, 12))
        self._button(bottom, "Stäng", window.destroy).pack(side="left")

    def refresh_all(self):
        if not self.stocks:
            messagebox.showinfo("Utdelning", "Du har inga aktier att uppdatera.")
            return
        self.refresh_all_btn.configure(state="disabled")
        self.set_status("Uppdaterar alla kurser från Yahoo...")

        def work():
            try:
                done, failed = app.refresh_all()
            except Exception as exc:
                self.after(0, lambda: self._refresh_all_done(0, [str(exc)]))
                return
            self.after(0, lambda: self._refresh_all_done(done, failed))

        threading.Thread(target=work, daemon=True).start()

    def _refresh_all_done(self, done, failed):
        self.refresh_all_btn.configure(state="normal")
        self.set_status(f"Uppdaterade {done} aktier.")
        self.reload()
        if failed:
            messagebox.showwarning("Utdelning", "Kunde inte uppdatera:\n" + "\n".join(failed))

    def save_file(self):
        path = filedialog.asksaveasfilename(
            title="Spara portföljen",
            defaultextension=".json",
            initialfile="utdelning-portfolj.json",
            filetypes=[("Portföljfil", "*.json"), ("Alla filer", "*.*")],
        )
        if not path:
            return
        try:
            count = app.export_portfolio(path)
        except Exception as exc:
            messagebox.showerror("Utdelning", str(exc))
            return
        self.set_status(f"Sparade {count} aktier till filen.")

    def load_file(self):
        path = filedialog.askopenfilename(
            title="Ladda en sparad portfölj",
            filetypes=[("Portföljfil", "*.json"), ("Alla filer", "*.*")],
        )
        if not path:
            return
        if not messagebox.askyesno(
            "Utdelning",
            "Filen ersätter hela din nuvarande portfölj. Vill du fortsätta?",
        ):
            return
        try:
            count = app.import_portfolio(path)
        except Exception as exc:
            messagebox.showerror("Utdelning", str(exc))
            return
        self.selected_id = None
        self.set_status(f"Läste in {count} aktier från filen.")
        self.reload()

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

        threading.Thread(target=work, daemon=True).start()

    def _refresh_done(self, stock, error):
        if error:
            self.set_status("")
            messagebox.showerror("Utdelning", error)
            return
        self.set_status(f"Börskursen för {stock['ticker']} är uppdaterad.")
        self.reload(stock["id"], stock.get("note"))

    def remove(self):
        stock = self.current()
        if not stock:
            return
        if not messagebox.askyesno("Utdelning", f"Ta bort hela {stock['name']}?"):
            return
        data = app.load()
        data["stocks"] = [item for item in data["stocks"] if item["id"] != stock["id"]]
        app.save(data)
        self.selected_id = None
        self.set_status(f"{stock['name']} är borttagen.")
        self.reload()


if __name__ == "__main__":
    root = tk.Tk()
    root.title("Utdelning")
    root.geometry("1295x720")
    root.minsize(1040, 640)
    UtdelningApp(root).pack(fill="both", expand=True)
    root.mainloop()
