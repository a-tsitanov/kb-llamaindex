"""gen-v2: a corpus where crimes and corruption are linked only implicitly.

No single document says "X is connected to Y". Every hidden link is a join across
documents written by different bodies (police, bank, tax register, land
register, traffic police, mobile operator, municipality): the same phone, home
address, bank card, INN, plate number, IMEI or item serial number shows up in
two unrelated papers. The KB has to find the chain through the graph.

Schemes (each built several times on different territories):

  kickback    official chairs the procurement commission; the winner is founded
              by his relative (link: relative's address in ЕГРЮЛ = official's
              home address in a police paper); money goes on to shell firms.
  cover       police operative refuses every complaint about a drug dealer;
              his mobile is in the dealer's seized phone book under a nickname,
              billing shows calls before checks, the car he drives belongs to
              the dealer's sister.
  fence       operative reports "stolen goods not received" by a pawnshop;
              a later search finds the items there (serial numbers match);
              the operative drives the pawnshop director's car.
  bribe       investigator refuses complaints against an entrepreneur; the
              entrepreneur's card pays monthly to a card that the bank says
              belongs to the investigator's mother.
  shell       nominee director (a hostel lodger caught drunk) heads several
              firms with one address and one phone; kickback / bribe money
              lands there.
  inspection  housing inspector finds "no violations" at a developer's site;
              his daughter gets a flat in that building far below market.
  fraudring   phone frauds in different districts: different numbers, one
              handset (same IMEI in billing), drop cards owned by lodgers of
              the nominee's hostel.

Plus background noise: ordinary criminal cases from gen-v1's world (world.py)
and honest procurements / inspections / company extracts, so that the signal
is not "every procurement is corrupt".

Stdlib only, deterministic for a given --seed.

  python world2.py --seed 21 --docs 1000 --out plan.json

Output plan.json: {"docs": [...], "links": [...]} — every doc carries its fact
lines (prompt) and gold (entities + relations); every link carries the chain
of facts and the doc ids each step comes from.
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import date, timedelta

import gen as g1
import world as w1
from world import BANKS, CAR_MODELS, PATRONYMIC, STOLEN_ITEMS, TERRITORIES, female_surname

ADMIN_POSITIONS = {
    "deputy": "заместитель главы городского округа",
    "zhkh": "начальник управления жилищно-коммунального хозяйства",
    "build": "начальник управления строительства и дорожного хозяйства",
    "procure": "начальник отдела муниципальных закупок",
    "econ": "заместитель начальника финансово-экономического управления",
}
PROCUREMENTS = [
    ("ремонт асфальтобетонного покрытия автомобильных дорог общего пользования", 18, 96),
    ("благоустройство дворовых территорий", 9, 54),
    ("капитальный ремонт кровли муниципального общеобразовательного учреждения", 6, 31),
    ("поставка уличных светодиодных светильников", 3, 17),
    ("содержание и уборка общественных территорий в зимний период", 12, 70),
    ("устройство детских игровых площадок", 4, 22),
    ("ремонт сетей наружного освещения", 5, 28),
    ("поставка и монтаж малых архитектурных форм", 2, 11),
]
COMPANY_NAMES = """СтройИнвест ДорСервис Магистраль ГородСтрой ТехноПарк АльфаСтрой Регион-Проект
ЭкоСити СветоТехника ПромРесурс Вектор Монолит Гарант-Строй Перспектива Стандарт-М БлагоСтрой
РемДорСтрой Импульс ТриумфСтрой Озон-Сервис Партнёр Каскад-Строй ИнжТехСервис Альянс-М
Северный Ветер Восход Континент Меркурий Капитель Горизонт""".split()
SHELL_NAMES = """Консалт-Групп ТоргЛайн Финанс-Эксперт Бизнес-Решения ОптимаТрейд ПрофКонсалт Деловой Мир
Аудит-Стандарт ИнвестПлюс СнабСбыт Логистик-М Маркет-Сервис""".split()
DEVELOPERS = ["Специализированный застройщик «Новые Горизонты»", "Специализированный застройщик «Квартал-Девелопмент»",
              "Специализированный застройщик «ЖилСтрой-Инвест»", "Специализированный застройщик «Солнечный Город»"]
NICKS = ["Серый работа", "Кум", "Друг мент", "Начальник", "Сосед Серёга", "Васёк ОУР", "Мент", "Крыша"]
HOSTEL = "общежитие"


def d(x: date) -> str:
    return x.strftime("%d.%m.%Y")


class Facts:
    """Fact lines for the prompt + gold entities/relations of one document."""

    def __init__(self, w: World2):
        self.w = w
        self.lines: list[str] = []
        self.ents: dict[str, dict] = {}
        self.rels: set[tuple[str, str, str]] = set()

    def ent(self, key, typ, name, **kw):
        self.ents.setdefault(key, {"key": key, "type": typ, "name": name, **kw})
        return key

    def rel(self, a, r, b):
        self.rels.add((a, r, b))

    def pkey(self, pid):
        p = self.w.persons[pid]
        return self.ent(pid, "Person", p.full, short=p.short, surname=p.surname, world_id=pid)

    def person(self, pid, role, *, birth=False, address=False, phone=False, inn=False, job=False):
        p = self.w.persons[pid]
        k = self.pkey(pid)
        s = f"- {role}: {p.full}"
        if birth:
            self.rel(k, "BIRTH_DATE", self.ent(f"{pid}:birth", "Date", p.birth))
            s += f", {p.birth} г.р."
        if address and p.address:
            self.rel(k, "ADDRESS", self.ent(f"addr:{p.address}", "Address", p.address))
            s += f", зарегистрирован(а) по адресу: {p.address}"
        if phone and p.phone:
            self.rel(k, "PHONE", self.ent(f"tel:{p.phone}", "Phone", p.phone))
            s += f", тел. {p.phone}"
        if inn and pid in self.w.pinn:
            self.rel(k, "INN", self.ent(f"inn:{self.w.pinn[pid]}", "Inn", self.w.pinn[pid]))
            s += f", ИНН {self.w.pinn[pid]}"
        if job:
            if p.rank and p.unit:
                self.rel(k, "WORKS_AT", self.org(p.unit))
                s += f", {p.position} {self.w.orgs[p.unit].name}, {p.rank}"
            elif p.job and p.unit:
                self.rel(k, "WORKS_AT", self.org(p.unit))
                s += f", {p.job} {self.w.orgs[p.unit].name}"
        self.lines.append(s)
        return k

    def org(self, oid, role=None, *, inn=False, ogrn=False, address=False, phone=False):
        o = self.w.orgs[oid]
        k = self.ent(oid, "Organization", o.name, world_id=oid)
        if role is None:
            return k
        x = self.w.ox.get(oid, {})
        s = f"- {role}: {o.name}"
        if inn and x.get("inn"):
            self.rel(k, "INN", self.ent(f"inn:{x['inn']}", "Inn", x["inn"]))
            s += f", ИНН {x['inn']}"
        if ogrn and x.get("ogrn"):
            s += f", ОГРН {x['ogrn']}"
        if address and o.address:
            self.rel(k, "ADDRESS", self.ent(f"addr:{o.address}", "Address", o.address))
            s += f", адрес: {o.address}"
        if phone and o.phone:
            self.rel(k, "PHONE", self.ent(f"tel:{o.phone}", "Phone", o.phone))
            s += f", тел. {o.phone}"
        self.lines.append(s)
        return k

    def card(self, num, owner=None):
        k = self.ent(f"card:{num}", "BankCard", num)
        if owner:
            self.rel(owner, "OWNS", k)
        return k

    def car(self, car, owner=None):
        k = self.ent(f"car:{car['plate']}", "Vehicle", f"{car['model']} {car['plate']}", plate=car["plate"])
        if owner:
            self.rel(owner, "OWNS", k)
        return k

    def amount(self, v):
        return self.ent(f"amt:{v}", "Amount", str(v), value=v)

    def date(self, x: str):
        return self.ent(f"date:{x}", "Date", x)

    def docref(self, label):
        return self.ent(f"doc:{label}", "Document", label)

    def line(self, s):
        self.lines.append(s)

    def gold(self):
        keys = set(self.ents)
        return {"entities": list(self.ents.values()),
                "relations": sorted([list(r) for r in self.rels if r[0] in keys and r[2] in keys])}


# document types: (title for the prompt, target chars, police style sample keyword or None)
DOC_TYPES = {
    "kusp": ("Рапорт оперативного дежурного / протокол принятия устного заявления о преступлении (КУСП)", 2300, "kusp"),
    "expl_victim": ("Объяснение заявителя, полученное сотрудником полиции", 3200, "expl_victim"),
    "expl_witness": ("Объяснение очевидца (свидетеля), полученное сотрудником полиции", 2400, "expl_witness"),
    "refusal": ("Постановление об отказе в возбуждении уголовного дела", 4200, "refusal"),
    "interrogation": ("Протокол допроса подозреваемого", 4500, "interrogation"),
    "indictment": ("Обвинительное заключение по уголовному делу", 6500, "indictment"),
    "pawn_report": ("Рапорт оперуполномоченного о проверке ломбардов и скупок на предмет сдачи похищенного имущества",
                    2800, "pawn_report"),
    "phone_book": ("Сведения о контактах, записанных в изъятом мобильном телефоне (протокол осмотра предмета)", 3500,
                   "phone_book"),
    "search": ("Протокол обыска (выемки) в помещении организации", 4000, "interrogation"),
    "characteristic": ("Служебная характеристика на сотрудника (для аттестационной комиссии)", 1800, None),
    "dtp": ("Определение об отказе в возбуждении дела об административном правонарушении по факту ДТП", 2500, None),
    "gibdd": ("Ответ ГИБДД на запрос: карточка учёта транспортного средства (ФИС ГИБДД-М)", 1400, None),
    "billing": ("Ответ оператора сотовой связи на запрос: детализация соединений абонентского номера", 3000, None),
    "bank_statement": ("Ответ банка на запрос: выписка о движении денежных средств по счёту", 3000, None),
    "bank_owner": ("Ответ банка на запрос о владельце банковской карты", 1400, None),
    "egrul": ("Выписка из ЕГРЮЛ (сведения о юридическом лице), приложенная к материалу проверки", 2400, None),
    "egrn": ("Выписка из ЕГРН о переходе прав на объект недвижимости, полученная по запросу", 2000, None),
    "protocol": ("Протокол подведения итогов электронного аукциона (муниципальная закупка)", 3400, None),
    "contract": ("Муниципальный контракт (преамбула, предмет, цена, реквизиты и подписи сторон)", 3000, None),
    "inspection": ("Акт проверки Главного управления Московской области «Государственная жилищная инспекция»",
                   3000, None),
    "complaint": ("Обращение гражданина в прокуратуру городского округа", 2400, None),
}


class World2(w1.World):
    def __init__(self, seed: int):
        super().__init__(seed)
        self.ox: dict[str, dict] = {}   # org extras: inn, ogrn, founders, director, reg
        self.pinn: dict[str, str] = {}
        self.docs: list[dict] = []
        self.links: list[dict] = []
        self._uniq: set[str] = set()

    # ---- unique identifiers ----------------------------------------------
    def _u(self, make):
        while True:
            v = make()
            if v not in self._uniq:
                self._uniq.add(v)
                return v

    def digits(self, n, first="123456789"):
        r = self.r
        return r.choice(first) + "".join(str(r.randint(0, 9)) for _ in range(n - 1))

    def inn_org(self):
        return self._u(lambda: "50" + self.digits(8, "0123456789"))

    def inn_person(self):
        return self._u(lambda: "50" + self.digits(10, "0123456789"))

    def ogrn(self):
        return self._u(lambda: "1" + self.r.choice(["15", "17", "19", "20", "21"]) + "50" + self.digits(9, "0123456789"))

    def card(self):
        return self._u(lambda: self.r.choice(["2202", "4276", "5536", "2200"]) + self.digits(12, "0123456789"))

    def imei(self):
        return self._u(lambda: "35" + self.digits(13, "0123456789"))

    def serial(self):
        return self._u(lambda: self.r.choice(["SN", "R5", "C02", "F17"]) + self.digits(9, "0123456789"))

    def plate(self):
        L = "АВЕКМНОРСТУХ"
        return self._u(lambda: f"{self.r.choice(L)}{self.r.randint(100, 999)}{self.r.choice(L)}{self.r.choice(L)} "
                               f"{self.r.choice([50, 150, 750, 190, 790])}")

    def car(self, owner):
        r = self.r
        return {"model": r.choice(CAR_MODELS), "plate": self.plate(), "owner": owner,
                "color": r.choice(["белого", "серого", "чёрного", "синего", "серебристого"]),
                "year": r.randint(2015, 2024)}

    def when(self, y0=2022, span=3 * 365):
        return date(y0, 1, 10) + timedelta(days=self.r.randint(0, span))

    # ---- people ------------------------------------------------------------
    def civ(self, terr, sex=None, age=(22, 65), surname=None, address=None):
        p = self.person(sex, age=age, surname=surname)
        p.address = address or self.address(terr)
        p.phone = self.phone_mobile()
        self.pinn[p.id] = self.inn_person()
        return p

    def named_father(self, p):
        """Make sure p.name has a patronymic form (for children)."""
        if p.name not in PATRONYMIC:
            p.name = self.r.choice(list(PATRONYMIC))

    def kin(self, p, kind, terr):
        """Relative of p. Returns (person, how the link is visible)."""
        base = w1._base(p.surname, p.sex)
        if kind == "wife":
            k = self.civ(terr, "F", age=(28, 58), surname=base, address=p.address)
        elif kind == "son":
            self.named_father(p)
            k = self.civ(terr, "M", age=(20, 32), surname=base, address=p.address)
            k.patronymic = PATRONYMIC[p.name][0]
        elif kind == "daughter":
            self.named_father(p)
            k = self.civ(terr, "F", age=(20, 32), surname=base)
            k.patronymic = PATRONYMIC[p.name][1]
        elif kind == "mother":
            k = self.civ(terr, "F", age=(58, 78), surname=base)
        elif kind == "mother_in_law":  # other surname, lives with the family
            k = self.civ(terr, "F", age=(58, 78), address=p.address)
        elif kind == "sister":
            k = self.civ(terr, "F", age=(25, 55), surname=base, address=p.address)
            father = next((f for f, (m, w) in PATRONYMIC.items() if p.patronymic in (m, w)), None)
            if father:
                k.patronymic = PATRONYMIC[father][1]
        else:
            raise ValueError(kind)
        return k

    # ---- orgs --------------------------------------------------------------
    def company(self, terr, name, *, director=None, founders=(), address=None, phone=None, kind="company"):
        o = self.org(kind, name, terr, phone_mobile=True)
        if address:
            o.address = address
        if phone:
            o.phone = phone
        o.head = director
        reg = self.when(2016, 6 * 365)
        self.ox[o.id] = {"inn": self.inn_org(), "ogrn": self.ogrn(), "director": director,
                         "founders": list(founders), "reg": d(reg), "okved": ""}
        if director:
            self.persons[director].job, self.persons[director].unit = "генеральный директор", o.id
        return o

    def populate2(self):
        """Municipal administrations + housing inspection on top of gen-v1 population."""
        self.admins = {}
        for terr in TERRITORIES:
            a = self.org("admin", f"Администрация {terr[0]} Московской области", terr)
            self.ox[a.id] = {"inn": self.inn_org(), "ogrn": self.ogrn()}
            staff = {}
            head = self.civ(terr, "M", age=(42, 62))
            head.job, head.unit = "глава городского округа", a.id
            a.head = head.id
            for key, pos in ADMIN_POSITIONS.items():
                p = self.civ(terr, age=(35, 60))
                p.job, p.unit = pos, a.id
                staff[key] = p.id
            self.admins[terr[0]] = (a.id, staff)
        self.gji = self.org("inspection", "Главное управление Московской области «Государственная жилищная инспекция "
                                          "Московской области»", TERRITORIES[0])
        self.ox[self.gji.id] = {"inn": self.inn_org(), "ogrn": self.ogrn()}
        self.inspectors = []
        for _ in range(8):
            p = self.civ(TERRITORIES[0], "M", age=(35, 58))
            self.named_father(p)
            p.job, p.unit = "главный инспектор территориального отдела", self.gji.id
            self.inspectors.append(p.id)
        self.contractors = {}
        names = self.r.sample(COMPANY_NAMES, len(COMPANY_NAMES))
        for i, terr in enumerate(TERRITORIES):
            cs = []
            for j in range(3):
                dr = self.civ(terr, age=(30, 62))
                fo = self.civ(terr, age=(30, 65))
                c = self.company(terr, f"ООО «{names[(i * 3 + j) % len(names)]}»", director=dr.id,
                                 founders=[(fo.id, 100)])
                cs.append(c.id)
            self.contractors[terr[0]] = cs
        self.banks = [o.id for o in self.orgs.values() if o.kind == "bank"]

    # ---- documents ---------------------------------------------------------
    POLICE = {"kusp", "expl_victim", "expl_witness", "refusal", "interrogation", "indictment", "pawn_report",
              "phone_book", "search", "characteristic"}
    REQUESTED = {"gibdd", "billing", "bank_statement", "bank_owner", "egrn", "egrul"}

    def context(self, typ) -> list[str]:
        """Who wrote the paper / who asked for it, so the model keeps it in the right district."""
        terr = self.cur
        unit = self.orgs[self.unit_of(terr)[0]].name
        if typ in self.POLICE:
            return [f"- подразделение: {unit}, {terr[1]} (Московская область)"]
        if typ in self.REQUESTED:
            return [f"- документ подготовлен по запросу {unit} в рамках материала проверки"]
        if typ == "dtp":
            return [f"- составил: инспектор ДПС ОГИБДД {unit} (по должности, без фамилии), {terr[1]}"]
        if typ in ("protocol", "contract"):
            return [f"- место: {terr[1]}, Московская область"]
        if typ == "complaint":
            return [f"- адресат: прокуратура {terr[0]} Московской области"]
        if typ == "inspection":
            return [f"- территориальный отдел инспекции: {terr[1]}"]
        return []

    def doc(self, typ, when: date, f: Facts, scheme: str, inst: str, note: str = "") -> int:
        self.docs.append({"type": typ, "date": d(when), "scheme": scheme, "instance": inst,
                          "facts": "\n".join([f"- дата документа: {d(when)}"] + self.context(typ) + f.lines),
                          "note": note, **f.gold()})
        return len(self.docs) - 1

    def F(self):
        return Facts(self)

    def unit_of(self, terr):
        for uid, (t, staff, chief, pawns, shops) in self.units.items():
            if t == terr:
                return uid, staff, chief, pawns, shops
        raise KeyError(terr)

    def officer(self, terr, position_word):
        uid, staff, chief, _, _ = self.unit_of(terr)
        cands = [s for s in staff if position_word in self.persons[s].position]
        male = [s for s in (cands or staff) if self.persons[s].sex == "M"]
        return self.r.choice(male or cands or staff), chief

    def link(self, scheme, inst, question, answer, chain, ends, official=()):
        """`ends` must never meet in one document, except in `official` doc types (an operative
        checking a pawnshop, an inspector at a developer — contact that is part of the job)."""
        self.links.append({"scheme": scheme, "instance": inst, "question": question, "answer": answer,
                           "chain": chain, "ends": ends, "official": list(official)})

    def bank_of(self):
        return self.r.choice(self.banks)

    # ======================================================================
    # schemes
    # ======================================================================
    def kickback(self, inst, terr, shells):
        r = self.r
        self.cur = terr
        aid, staff = self.admins[terr[0]]
        off = self.persons[staff[r.choice(["deputy", "zhkh", "build"])]]
        kind = r.choice(["wife", "son", "mother_in_law"])
        rel = self.kin(off, kind, terr)
        nominee = self.civ(terr, "M", age=(24, 60))
        firm = self.company(terr, f"ООО «{r.choice(COMPANY_NAMES)}-{r.randint(1, 9)}»", director=nominee.id,
                            founders=[(rel.id, 100)])
        honest = r.sample(self.contractors[terr[0]], 2)
        docs = []

        # 1. official's home address surfaces in an unrelated police paper (his car broken into)
        t0 = self.when(2022, 300)
        car = self.car(off.id)
        f = self.F()
        f.person(off.id, "заявитель", birth=True, address=True, phone=True, job=True)
        f.car(car, off.id)
        f.line(f"- происшествие: из припаркованного у дома автомобиля {car['model']} г.р.з. {car['plate']} похищен "
               f"видеорегистратор, ущерб {r.randint(4, 9)} 500 руб.")
        docs.append(self.doc("kusp", t0, f, "kickback", inst))

        # 2. ЕГРЮЛ of the firm: founder = relative with home address = official's address
        f = self.F()
        fk = f.org(firm.id, "юридическое лицо", inn=True, ogrn=True, address=True, phone=True)
        f.line(f"- дата регистрации: {self.ox[firm.id]['reg']}; основной вид деятельности 42.11 "
               f"«Строительство автомобильных дорог и автомагистралей»; уставный капитал 10 000 руб.")
        rk = f.person(rel.id, "единственный учредитель (100% доли)", inn=True, address=True)
        nk = f.person(nominee.id, "генеральный директор", inn=True)
        f.rel(rk, "FOUNDER_OF", fk)
        f.rel(nk, "DIRECTOR_OF", fk)
        docs.append(self.doc("egrul", self.when(2023, 500), f, "kickback", inst,
                             "Только сведения реестра, без оценок."))

        # 3. auctions: official chairs the commission, the firm wins
        contracts = []
        for n in range(r.randint(2, 3)):
            subj, lo, hi = r.choice(PROCUREMENTS)
            price = r.randint(lo, hi) * 1_000_000 + r.randint(0, 99) * 1000
            win = int(price * r.uniform(0.95, 0.995))
            num = f"0148300{r.randint(10000, 99999)}{t0.year % 100 + 1 + n}000{r.randint(100, 999)}"
            when = self.when(2023, 600)
            f = self.F()
            ak = f.org(aid, "заказчик", inn=True)
            f.docref(f"извещение № {num}")
            f.line(f"- закупка: извещение № {num}, предмет: {subj}, НМЦК {price} руб.")
            ck = f.person(off.id, "председатель единой комиссии", job=True)
            f.rel(ck, "CHAIRED", f.docref(f"извещение № {num}"))
            others = r.sample([s for k_, s in staff.items() if s != off.id], 2)
            for s in others:
                f.person(s, "член комиссии", job=True)
            f.org(firm.id, "участник № 1 (победитель)", inn=True)
            f.line(f"- предложение победителя: {win} руб. (снижение {round(100 - win / price * 100, 1)}%)")
            for h in honest:
                f.org(h, "участник (заявка отклонена по формальным основаниям)", inn=True)
            f.rel(fk, "WON", f.docref(f"извещение № {num}"))
            f.amount(win)
            docs.append(self.doc("protocol", when, f, "kickback", inst))
            f = self.F()
            ak = f.org(aid, "заказчик", inn=True, address=True)
            f.person(self.orgs[aid].head, "от заказчика подписал", job=True)
            fk = f.org(firm.id, "подрядчик", inn=True, ogrn=True, address=True)
            f.person(nominee.id, "от подрядчика подписал генеральный директор")
            f.docref(f"муниципальный контракт № {num}")
            f.line(f"- муниципальный контракт № {num}, предмет: {subj}, цена {win} руб., срок выполнения работ "
                   f"до {d(when + timedelta(days=r.randint(60, 200)))}")
            f.amount(win)
            f.rel(ak, "CONTRACT_WITH", fk)
            docs.append(self.doc("contract", when + timedelta(days=12), f, "kickback", inst))
            contracts.append((num, win, when))

        # 4. bank: the firm pays shells "for consulting" and the relative's card
        f = self.F()
        bank = self.bank_of()
        f.org(bank, "банк", inn=False)
        fk = f.org(firm.id, "владелец счёта", inn=True)
        acct = "40702810" + self.digits(12, "0123456789")
        f.line(f"- расчётный счёт № {acct}")
        rows = []
        for num, win, when in contracts:
            rows.append(f"{d(when + timedelta(days=40))}: поступление {win // 2} руб. от {self.orgs[aid].name} "
                        f"(ИНН {self.ox[aid]['inn']}), аванс по контракту № {num}")
            for sh in shells:
                v = r.randint(3, 9) * 100_000 + r.randint(0, 9) * 10_000
                rows.append(f"{d(when + timedelta(days=r.randint(41, 55)))}: списание {v} руб. в пользу "
                            f"{self.orgs[sh].name} (ИНН {self.ox[sh]['inn']}), «оплата по договору оказания "
                            f"консультационных услуг»")
                f.rel(fk, "PAID", f.org(sh))
                f.ent(f"inn:{self.ox[sh]['inn']}", "Inn", self.ox[sh]["inn"])
        rcard = self.card()
        v = r.randint(4, 12) * 50_000
        rows.append(f"{d(contracts[-1][2] + timedelta(days=60))}: списание {v} руб. на карту № {rcard} "
                    f"(получатель {rel.name} {rel.patronymic} {rel.surname[0]}.), «возврат займа»")
        f.rel(fk, "PAID", f.card(rcard))
        f.ent(f"inn:{self.ox[aid]['inn']}", "Inn", self.ox[aid]["inn"])
        f.line("- операции по счёту:\n    " + "\n    ".join(rows))
        docs.append(self.doc("bank_statement", self.when(2025, 200), f, "kickback", inst,
                             "Только выписка, без выводов о характере операций."))

        # 5. a losing bidder complains (names the firm and the contract, not the official's family)
        f = self.F()
        h = self.orgs[honest[0]]
        f.person(h.head, "заявитель, генеральный директор", phone=True, job=True)
        f.org(aid, "администрация")
        f.org(firm.id, "победитель")
        f.line(f"- суть: заявка {h.name} на закупку № {contracts[0][0]} отклонена по надуманному основанию, "
               f"победителем стала фирма, зарегистрированная незадолго до торгов и не имеющая техники и "
               f"работников; просит провести проверку")
        f.docref(f"извещение № {contracts[0][0]}")
        docs.append(self.doc("complaint", contracts[0][2] + timedelta(days=20), f, "kickback", inst,
                             "Заявитель не знает, кто стоит за фирмой-победителем, и никого не называет."))

        ok, rk, fk = off.id, rel.id, firm.id
        self.link("kickback", inst,
                  f"Есть ли конфликт интересов у сотрудников {self.orgs[aid].name} при проведении закупок?",
                  f"{off.full} ({off.job}) возглавлял комиссию, которая отдала контракты {firm.name}; единственный "
                  f"учредитель фирмы {rel.full} зарегистрирован(а) по тому же адресу, что и {off.short} "
                  f"({off.address}); деньги по контрактам ушли в фирмы-однодневки и на карту {rel.short}.",
                  [[ok, "ADDRESS", f"addr:{off.address}", [docs[0]]],
                   [rk, "ADDRESS", f"addr:{off.address}", [docs[1]]],
                   [rk, "FOUNDER_OF", fk, [docs[1]]],
                   [ok, "CHAIRED", "протоколы аукционов", [x for x in docs if self.docs[x]["type"] == "protocol"]],
                   [fk, "PAID", "фирмы-однодневки", [docs[-2]]]],
                  [ok, rk])
        return fk, nominee.id

    def cover(self, inst, terr, terr2):
        r = self.r
        self.cur = terr
        oper, chief = self.officer(terr, "оперуполномоченный")
        op = self.persons[oper]
        op.phone = op.phone or self.phone_mobile()
        op.address = op.address or self.address(terr)
        dealer = self.civ(terr, "M", age=(22, 45))
        sister = self.kin(dealer, "sister", terr)
        car = self.car(sister.id)
        docs = []
        # 1. neighbours complain, operative refuses (twice)
        for k in range(2):
            t = self.when(2022, 600)
            nb = self.civ(terr)
            f = self.F()
            f.person(nb.id, "заявитель", birth=True, address=True, phone=True)
            f.person(dealer.id, "лицо, на которое указывает заявитель", address=True)
            f.line("- суть: в подъезде и у дома постоянно собираются посторонние молодые люди, заявитель "
                   "подозревает, что сосед торгует наркотиками")
            docs.append(self.doc("kusp", t, f, "cover", inst))
            f = self.F()
            f.person(oper, "материал проверки рассмотрел", job=True)
            f.person(chief, "начальник подразделения (утверждает)", job=True)
            f.person(nb.id, "заявитель")
            f.person(dealer.id, "лицо, в отношении которого проводилась проверка", birth=True, address=True)
            f.line("- результат: в ходе ОРМ «Наблюдение» факты сбыта не подтвердились; отказать в возбуждении "
                   "уголовного дела по п. 1 ч. 1 ст. 24 УПК РФ за отсутствием события преступления")
            docs.append(self.doc("refusal", t + timedelta(days=r.randint(10, 28)), f, "cover", inst))
        # 2. the operative's own mobile is in his service characteristic
        f = self.F()
        f.person(oper, "аттестуемый", birth=True, phone=True, job=True)
        f.person(chief, "характеристику подписал", job=True)
        f.line("- служит в органах внутренних дел с 2014 года; к дисциплинарной ответственности не привлекался; "
               "раскрыл ряд преступлений имущественного характера")
        docs.append(self.doc("characteristic", self.when(2023, 300), f, "cover", inst,
                             "Укажи номер мобильного телефона сотрудника в разделе контактных данных."))
        # 3. he crashes in his sister-in-crime's car: driver = operative, owner = dealer's sister
        t = self.when(2023, 500)
        other = self.civ(terr)
        ocar = self.car(other.id)
        f = self.F()
        f.person(oper, "водитель автомобиля № 1", birth=True)
        f.car(car)
        f.line(f"- автомобиль № 1: {car['model']} {car['color']} цвета, г.р.з. {car['plate']}; водитель НЕ "
               f"является собственником, управлял по доверенности (собственник в документе не указан)")
        f.person(other.id, "водитель и собственник автомобиля № 2", birth=True, address=True)
        f.car(ocar, other.id)
        f.line(f"- автомобиль № 2: {ocar['model']}, г.р.з. {ocar['plate']}; столкновение при перестроении на "
               f"ул. {r.choice(w1.STREETS)}, пострадавших нет")
        f.rel(oper, "DROVE", f"car:{car['plate']}")
        docs.append(self.doc("dtp", t, f, "cover", inst, "Не указывай собственника автомобиля № 1."))
        f = self.F()
        f.person(sister.id, "собственник", birth=True, address=True)
        f.car(car, sister.id)
        f.line(f"- транспортное средство: {car['model']}, {car['year']} г.в., цвет {car['color']}, "
               f"г.р.з. {car['plate']}, VIN X{self.digits(16, '0123456789')}")
        docs.append(self.doc("gibdd", t + timedelta(days=9), f, "cover", inst))
        # 4. a neighbouring district buys from the dealer and seizes his phone
        uid2, staff2, chief2, _, _ = self.unit_of(terr2)
        op2 = r.choice(staff2)
        self.cur = terr2
        t = self.when(2024, 400)
        f = self.F()
        f.person(op2, "протокол составил", job=True)
        f.person(dealer.id, "владелец изъятого телефона", birth=True)
        f.line(f"- в телефоне установлена SIM-карта с абонентским номером {dealer.phone}")
        f.rel(dealer.id, "PHONE", f.ent(f"tel:{dealer.phone}", "Phone", dealer.phone))
        book = [(f"{r.choice(w1.MALE)} {r.choice(['Белый', 'Такси', 'Брат', 'Опт', 'Шиномонтаж', 'Север'])}",
                 self.phone_mobile()) for _ in range(r.randint(12, 20))]
        book.append((r.choice(NICKS), op.phone))
        book.append(("Сеструха", sister.phone))
        r.shuffle(book)
        for _, ph in book:
            f.ent(f"tel:{ph}", "Phone", ph)
        f.line("- записная книжка телефона (подпись контакта — номер):\n    "
               + "\n    ".join(f"«{lbl}» — {ph}" for lbl, ph in book))
        docs.append(self.doc("phone_book", t, f, "cover", inst,
                             "Перечисли все контакты как есть, без комментариев о том, кому принадлежат номера."))
        self.cur = terr
        # 5. billing of the dealer's number: calls with the operative's mobile before the checks
        f = self.F()
        f.line(f"- абонентский номер {dealer.phone}, период {d(t - timedelta(days=700))} — {d(t)}")
        f.ent(f"tel:{dealer.phone}", "Phone", dealer.phone)
        f.ent(f"tel:{op.phone}", "Phone", op.phone)
        f.rel(f"tel:{dealer.phone}", "CALLED", f"tel:{op.phone}")
        rows = []
        for x in docs[1:4:2]:  # a day or two before each refusal
            dd = date(*reversed([int(v) for v in self.docs[x]["date"].split(".")])) - timedelta(days=r.randint(1, 2))
            rows.append(f"{d(dd)}: исходящий вызов на {op.phone}, {r.randint(40, 180)} сек.")
        for _ in range(6):
            ph = r.choice(book)[1]
            rows.append(f"{d(self.when(2023, 500))}: входящий вызов с {ph}, {r.randint(10, 300)} сек.")
            f.ent(f"tel:{ph}", "Phone", ph)
        r.shuffle(rows)
        f.line("- соединения (выборка):\n    " + "\n    ".join(rows))
        docs.append(self.doc("billing", t + timedelta(days=30), f, "cover", inst,
                             "Оператор связи не знает, кому принадлежат номера собеседников, — их не называй."))
        # 6. charged in the neighbouring district
        f = self.F()
        f.person(self.officer(terr2, "следователь")[0], "следователь", job=True)
        f.person(dealer.id, "обвиняемый", birth=True, address=True, phone=True)
        f.line(f"- обвинение: п. «б» ч. 3 ст. 228.1 УК РФ, сбыт мефедрона массой {round(r.uniform(1, 9), 2)} г "
               f"закупщику под контролем {self.orgs[uid2].name}")
        docs.append(self.doc("indictment", t + timedelta(days=90), f, "cover", inst,
                             "Обвиняемый отрицает знакомство с сотрудниками полиции."))
        self.link("cover", inst,
                  f"Почему проверки по жалобам на торговлю наркотиками (фигурант — {dealer.full}) в "
                  f"{self.orgs[self.unit_of(terr)[0]].name} заканчивались отказом?",
                  f"Отказы выносил оперуполномоченный {op.full}; его мобильный {op.phone} (из служебной "
                  f"характеристики) записан в телефоне {dealer.short} как «{[l for l, p in book if p == op.phone][0]}», "
                  f"биллинг показывает звонки за день-два до каждого отказа; {op.short} ездит на машине {car['plate']}, "
                  f"оформленной на сестру {dealer.short} — {sister.full}.",
                  [[oper, "PHONE", f"tel:{op.phone}", [docs[4]]],
                   [f"tel:{dealer.phone}", "CONTACT", f"tel:{op.phone}", [docs[7], docs[8]]],
                   [oper, "DROVE", f"car:{car['plate']}", [docs[5]]],
                   [sister.id, "OWNS", f"car:{car['plate']}", [docs[6]]],
                   [sister.id, "ADDRESS", f"addr:{dealer.address}", [docs[6]]],
                   [oper, "SIGNED", "отказы", [docs[1], docs[3]]]],
                  [oper, sister.id])

    def fence(self, inst, terr, terr2):
        r = self.r
        self.cur = terr
        uid, staff, chief, pawns, _ = self.unit_of(terr)
        oper, _ = self.officer(terr, "оперуполномоченный")
        op = self.persons[oper]
        pawn = self.orgs[r.choice(pawns)]
        director = pawn.head
        car = self.car(director)
        docs, found = [], []
        for k in range(r.randint(3, 4)):
            t = self.when(2022, 700)
            v = self.civ(terr)
            name, lo, hi = r.choice(STOLEN_ITEMS)
            sn = self.serial()
            item = f"{name}, серийный номер {sn}"
            found.append((item, sn, v.id))
            f = self.F()
            f.person(v.id, "потерпевший", birth=True, address=True, phone=True)
            f.ent(f"item:{sn}", "Item", item, serial=sn)
            f.line(f"- похищено из квартиры: {item}, стоимостью {r.randint(lo, hi)} руб.; документы на вещь "
                   f"(коробка, чек) сохранились")
            docs.append(self.doc("expl_victim", t, f, "fence", inst))
            f = self.F()
            f.person(oper, "рапорт составил", job=True)
            f.org(pawn.id, "проверена организация", address=True)
            f.ent(f"item:{sn}", "Item", item, serial=sn)
            f.line(f"- проверено наличие: {item}; результат: указанное имущество в ломбард не сдавалось, "
                   f"в базе приёмки не значится")
            f.rel(oper, "CHECKED", pawn.id)
            docs.append(self.doc("pawn_report", t + timedelta(days=r.randint(3, 12)), f, "fence", inst))
        # a car accident: operative drives the pawnshop director's car
        t = self.when(2023, 500)
        f = self.F()
        f.person(oper, "водитель автомобиля", birth=True)
        f.car(car)
        f.line(f"- автомобиль: {car['model']} {car['color']} цвета, г.р.з. {car['plate']}, наезд на бордюр при "
               f"гололёде, повреждено переднее правое колесо; пострадавших нет; водитель НЕ является "
               f"собственником, управлял по доверенности (собственник в документе не указан)")
        f.rel(oper, "DROVE", f"car:{car['plate']}")
        docs.append(self.doc("dtp", t, f, "fence", inst, "Не указывай собственника автомобиля."))
        f = self.F()
        f.person(director, "собственник", birth=True, address=True)
        f.car(car, director)
        f.line(f"- транспортное средство: {car['model']}, {car['year']} г.в., г.р.з. {car['plate']}")
        docs.append(self.doc("gibdd", t + timedelta(days=5), f, "fence", inst))
        # a search by economic-crimes unit of the neighbouring district finds the items
        uid2, staff2, _, _, _ = self.unit_of(terr2)
        self.cur = terr2
        f = self.F()
        f.person(staff2[0], "обыск провёл", job=True)
        f.org(pawn.id, "место обыска", address=True)
        f.person(director, "присутствовал генеральный директор")
        for item, sn, _ in found[: max(2, len(found) - 1)]:
            f.ent(f"item:{sn}", "Item", item, serial=sn)
            f.rel(pawn.id, "HELD", f"item:{sn}")
        f.line("- изъято в подсобном помещении, без квитанций о приёмке: "
               + "; ".join(i for i, _, _ in found[: max(2, len(found) - 1)]))
        docs.append(self.doc("search", self.when(2024, 400), f, "fence", inst,
                             "Это обыск по другому делу (сбыт контрафакта); о кражах в документе не говорится."))
        self.link("fence", inst,
                  f"Связаны ли кражи, по которым {op.short} проверял {pawn.name}, с этим ломбардом?",
                  f"Вещи с серийными номерами из заявлений потерпевших найдены при обыске в {pawn.name}, хотя "
                  f"{op.full} писал, что их туда не сдавали; {op.short} ездит на автомобиле {car['plate']} "
                  f"генерального директора ломбарда {self.persons[director].full}.",
                  [[f"item:{found[0][1]}", "STOLEN_FROM", found[0][2], [docs[0]]],
                   [oper, "CHECKED", pawn.id, [x for x in docs if self.docs[x]["type"] == "pawn_report"]],
                   [pawn.id, "HELD", f"item:{found[0][1]}", [docs[-1]]],
                   [oper, "DROVE", f"car:{car['plate']}", [docs[-3]]],
                   [director, "OWNS", f"car:{car['plate']}", [docs[-2]]]],
                  [oper, director], official=["pawn_report"])

    def bribe(self, inst, terr, shells):
        r = self.r
        self.cur = terr
        inv, chief = self.officer(terr, "следователь")
        iv = self.persons[inv]
        iv.address = iv.address or self.address(terr)
        iv.phone = iv.phone or self.phone_mobile()
        mother = self.kin(iv, "mother", terr)
        boss = self.civ(terr, "M", age=(35, 60))
        firm = self.company(terr, f"ООО «{r.choice(['Окна-Профи', 'ТеплоДом', 'Мебель-Сити', 'ДомСтрой-М', 'Кровля-Сервис'])}»",
                            director=boss.id, founders=[(boss.id, 100)])
        bcard, mcard = self.card(), self.card()
        docs = []
        for k in range(3):
            t = self.when(2022, 650)
            v = self.civ(terr)
            f = self.F()
            f.person(v.id, "заявитель", birth=True, address=True, phone=True)
            f.org(firm.id, "организация", inn=True, address=True)
            f.person(boss.id, "генеральный директор организации")
            amt = r.randint(8, 60) * 10_000
            f.amount(amt)
            f.line(f"- суть: заключил договор на {r.choice(['изготовление кухни', 'установку окон', 'ремонт кровли', 'строительство бани'])}, "
                   f"внёс предоплату {amt} руб., работы не выполнены, деньги не возвращены")
            docs.append(self.doc("expl_victim", t, f, "bribe", inst))
            f = self.F()
            f.person(inv, "постановление вынес", job=True)
            f.person(v.id, "заявитель")
            f.person(boss.id, "лицо, в отношении которого проводилась проверка", birth=True)
            f.org(firm.id, "организация", inn=True)
            f.line("- результат: усматриваются гражданско-правовые отношения; отказать в возбуждении уголовного "
                   "дела по ч. 1 ст. 159 УК РФ на основании п. 2 ч. 1 ст. 24 УПК РФ")
            f.rel(inv, "SIGNED_REFUSAL", boss.id)
            docs.append(self.doc("refusal", t + timedelta(days=r.randint(20, 30)), f, "bribe", inst))
        # investigator's address (and so the family flat) shows up in his characteristic
        f = self.F()
        f.person(inv, "аттестуемый", birth=True, address=True, phone=True, job=True)
        f.person(chief, "характеристику подписал", job=True)
        f.line("- имеет высокий процент направления дел в суд; женат, имеет двоих детей")
        docs.append(self.doc("characteristic", self.when(2023, 300), f, "bribe", inst,
                             "Укажи адрес регистрации и мобильный телефон сотрудника."))
        # bank statement of the entrepreneur's personal card
        f = self.F()
        bank = self.bank_of()
        f.org(bank, "банк")
        bk = f.person(boss.id, "держатель карты", birth=True)
        f.card(bcard, bk)
        f.line(f"- карта № {bcard}")
        rows = []
        for k in range(r.randint(4, 6)):
            v = r.choice([30_000, 40_000, 50_000, 75_000, 100_000])
            rows.append(f"{d(self.when(2022, 700))}: перевод {v} руб. на карту № {mcard} "
                        f"(получатель {mother.name} {mother.patronymic} {mother.surname[0]}.)")
        f.rel(f"card:{bcard}", "PAID", f.card(mcard))
        for sh in shells[:1]:
            rows.append(f"{d(self.when(2023, 400))}: поступление {r.randint(2, 6) * 100_000} руб. от "
                        f"{self.orgs[sh].name} (ИНН {self.ox[sh]['inn']}), «выдача займа»")
            f.org(sh)
            f.ent(f"inn:{self.ox[sh]['inn']}", "Inn", self.ox[sh]["inn"])
        r.shuffle(rows)
        f.line("- операции (выборка):\n    " + "\n    ".join(rows))
        docs.append(self.doc("bank_statement", self.when(2025, 150), f, "bribe", inst,
                             "Только выписка, без выводов."))
        # the bank says whose card that is
        f = self.F()
        f.org(self.bank_of(), "банк")
        mk = f.person(mother.id, "владелец карты", birth=True, address=True, phone=True)
        f.card(mcard, mk)
        f.line(f"- карта № {mcard} выпущена {d(self.when(2019, 900))}, привязана к счёту 40817810{self.digits(12, '0123456789')}")
        docs.append(self.doc("bank_owner", self.when(2025, 200), f, "bribe", inst))
        # mother's flat registration = investigator's address? No: link via surname + patronymic logic is weak,
        # so the mother lists her son's phone as the contact in a fraud complaint.
        f = self.F()
        f.person(mother.id, "заявитель", birth=True, address=True)
        f.line(f"- для связи заявитель указала номер сына: {iv.phone}")
        f.ent(f"tel:{iv.phone}", "Phone", iv.phone)
        f.line("- суть: неизвестный по телефону представился сотрудником поликлиники и предложил бесплатное "
               "обследование, заявитель вовремя прервала разговор, денег не переводила")
        docs.append(self.doc("kusp", self.when(2023, 500), f, "bribe", inst,
                             "Не называй сына по имени — только номер для связи."))
        self.link("bribe", inst,
                  f"Почему по жалобам на {firm.name} ({boss.short}) раз за разом отказывали в возбуждении дела?",
                  f"Все отказы вынес следователь {iv.full}; с карты {boss.short} регулярно шли переводы на карту "
                  f"{mcard}, которая по ответу банка принадлежит {mother.full}; в её заявлении контактный номер "
                  f"сына — {iv.phone}, это мобильный {iv.short} из служебной характеристики.",
                  [[inv, "SIGNED_REFUSAL", boss.id, [x for x in docs if self.docs[x]["type"] == "refusal"]],
                   [f"card:{bcard}", "PAID", f"card:{mcard}", [docs[-3]]],
                   [mother.id, "OWNS", f"card:{mcard}", [docs[-2]]],
                   [mother.id, "CONTACT", f"tel:{iv.phone}", [docs[-1]]],
                   [inv, "PHONE", f"tel:{iv.phone}", [docs[-4]]]],
                  [boss.id, mother.id])
        return firm.id

    def shell(self, inst, terr):
        r = self.r
        self.cur = terr
        hostel = f"Московская область, {terr[1]}, ул. {r.choice(w1.STREETS)}, д. {r.randint(1, 60)}, {HOSTEL}, комн. {r.randint(1, 90)}"
        nominee = self.civ(terr, "M", age=(30, 60), address=hostel)
        office = self.address(terr, flat=False) + f", пом. {r.randint(1, 30)}"
        phone = self.phone_city(terr[3])
        firms = []
        for k in range(r.randint(3, 4)):
            name = f"ООО «{r.choice(SHELL_NAMES)}{'' if k == 0 else '-' + str(k + 1)}»"
            firms.append(self.company(terr, name, director=nominee.id, founders=[(nominee.id, 100)],
                                      address=office, phone=phone).id)
        docs = []
        for fid in firms:
            f = self.F()
            fk = f.org(fid, "юридическое лицо", inn=True, ogrn=True, address=True, phone=True)
            f.line(f"- дата регистрации: {self.ox[fid]['reg']}; основной вид деятельности 70.22 «Консультирование "
                   f"по вопросам коммерческой деятельности и управления»; уставный капитал 10 000 руб.; "
                   f"среднесписочная численность работников: 1")
            nk = f.person(nominee.id, "генеральный директор и единственный учредитель", inn=True)
            f.rel(nk, "DIRECTOR_OF", fk)
            docs.append(self.doc("egrul", self.when(2023, 600), f, "shell", inst))
        # the nominee is picked up drunk
        f = self.F()
        f.person(nominee.id, "доставленный", birth=True, address=True)
        f.line("- обстоятельства: находился в состоянии алкогольного опьянения у магазина, нарушал общественный "
               "порядок; пояснил, что постоянной работы не имеет, подрабатывает грузчиком, «бумаги на фирмы "
               "подписывал за деньги, что за фирмы — не знает»; составлен протокол по ст. 20.21 КоАП РФ")
        docs.append(self.doc("kusp", self.when(2024, 300), f, "shell", inst,
                             "Названия фирм доставленный не помнит и не называет."))
        self.link("shell", inst,
                  f"Кто реально руководит {self.orgs[firms[0]].name}?",
                  f"Все {len(firms)} фирмы с одним адресом {office} и телефоном {phone} записаны на "
                  f"{nominee.full}, который живёт в общежитии и по объяснению в полиции подписывал бумаги за "
                  f"деньги, — номинальный директор.",
                  [[nominee.id, "DIRECTOR_OF", fid, [docs[i]]] for i, fid in enumerate(firms)]
                  + [[nominee.id, "ADDRESS", f"addr:{hostel}", [docs[-1]]]],
                  [firms[0], f"addr:{hostel}"])
        return firms, nominee.id, hostel

    def inspection(self, inst, terr):
        r = self.r
        self.cur = terr
        insp = self.persons[self.inspectors[int(inst.split("-")[-1]) % len(self.inspectors)]]
        insp.address = insp.address or self.address(terr)
        dau = self.kin(insp, "daughter", terr)
        boss = self.civ(terr, "M")
        dev = self.company(terr, f"ООО «{r.choice(DEVELOPERS)}»", director=boss.id, founders=[(boss.id, 100)])
        site = self.address(terr, flat=False)
        docs = []
        for k in range(2):
            t = self.when(2022, 600)
            res = self.civ(terr)
            f = self.F()
            f.person(res.id, "заявитель", address=True, phone=True)
            f.org(dev.id, "застройщик", inn=True)
            f.line(f"- суть: жилой дом по адресу {site}: {r.choice(['трещины в несущих стенах', 'протечки кровли', 'не работает пожарная сигнализация', 'подвал затапливает'])}; "
                   f"застройщик на претензии не отвечает")
            f.ent(f"addr:{site}", "Address", site)
            docs.append(self.doc("complaint", t, f, "inspection", inst))
            f = self.F()
            f.person(insp.id, "проверку провёл", job=True)
            f.org(dev.id, "проверяемое лицо", inn=True, address=True)
            f.person(boss.id, "присутствовал генеральный директор")
            f.ent(f"addr:{site}", "Address", site)
            f.line(f"- объект: многоквартирный дом {site}; результат: нарушений обязательных требований не выявлено")
            f.rel(insp.id, "INSPECTED", dev.id)
            docs.append(self.doc("inspection", t + timedelta(days=r.randint(15, 30)), f, "inspection", inst))
        flat = f"{site}, кв. {r.randint(10, 300)}"
        f = self.F()
        dk = f.person(dau.id, "правообладатель", birth=True, inn=True)
        f.org(dev.id, "прежний правообладатель", inn=True)
        f.ent(f"addr:{flat}", "Address", flat)
        price = r.randint(9, 25) * 100_000
        f.line(f"- объект: квартира {r.randint(55, 110)} кв. м по адресу {flat}; основание: договор участия в "
               f"долевом строительстве, цена {price} руб. (кадастровая стоимость {price * r.randint(5, 9)} руб.)")
        f.rel(dk, "OWNS", f"addr:{flat}")
        docs.append(self.doc("egrn", self.when(2024, 300), f, "inspection", inst))
        # the inspector's name & address surface in a theft report; the daughter's birth + patronymic match him
        f = self.F()
        f.person(insp.id, "заявитель", birth=True, address=True, phone=True, job=True)
        f.person(dau.id, "дочь заявителя, присутствовала при осмотре", birth=True)
        f.line("- суть: с балкона похищены два велосипеда, ущерб 38 000 руб.")
        docs.append(self.doc("kusp", self.when(2023, 400), f, "inspection", inst))
        self.link("inspection", inst,
                  f"Объективны ли проверки ГЖИ по объектам {dev.name}?",
                  f"Акты «нарушений не выявлено» подписал {insp.full}; его дочь {dau.full} (в заявлении о краже "
                  f"велосипедов) получила квартиру в проверяемом доме по цене в разы ниже кадастровой.",
                  [[insp.id, "INSPECTED", dev.id, [x for x in docs if self.docs[x]["type"] == "inspection"]],
                   [dau.id, "OWNS", f"addr:{flat}", [docs[-2]]],
                   [insp.id, "RELATIVE", dau.id, [docs[-1]]]],
                  [insp.id, dev.id], official=["inspection"])

    def fraudring(self, inst, terrs, hostel, n_drops=3):
        r = self.r
        handset = self.imei()
        drops = []
        for k in range(n_drops):
            p = self.civ(terrs[0], age=(19, 35), address=hostel.rsplit(",", 1)[0] + f", комн. {r.randint(1, 90)}")
            drops.append((p.id, self.card()))
        docs, phones = [], []
        for k, terr in enumerate(terrs):
            self.cur = terr
            uid, staff, _, _, _ = self.unit_of(terr)
            fraud_phone = self.phone_mobile()
            phones.append(fraud_phone)
            drop, dcard = drops[k % len(drops)]
            v = self.civ(terr, age=(60, 85))
            amt = r.randint(8, 40) * 10_000
            t = self.when(2024, 400)
            f = self.F()
            f.person(v.id, "потерпевший", birth=True, address=True, phone=True)
            f.ent(f"tel:{fraud_phone}", "Phone", fraud_phone)
            f.card(dcard)
            f.amount(amt)
            f.line(f"- суть: позвонили с номера {fraud_phone}, представились сотрудником {r.choice(['службы безопасности банка', 'Центробанка', 'полиции'])}, "
                   f"убедили перевести {amt} руб. «на безопасный счёт» — на карту № {dcard}")
            docs.append(self.doc("expl_victim", t, f, "fraudring", inst))
            f = self.F()
            f.ent(f"tel:{fraud_phone}", "Phone", fraud_phone)
            f.ent(f"imei:{handset}", "Device", handset)
            f.rel(f"tel:{fraud_phone}", "USED_IN", f"imei:{handset}")
            f.line(f"- абонентский номер {fraud_phone}, SIM-карта оформлена на иностранного гражданина, "
                   f"паспортные данные недостоверны")
            f.line(f"- в период активности номер работал в абонентском устройстве IMEI {handset}; "
                   f"базовая станция: {terr[1]}, ул. {r.choice(w1.STREETS)}")
            f.line(f"- {d(t)}: исходящий вызов на {v.phone}, {r.randint(600, 2400)} сек.")
            f.ent(f"tel:{v.phone}", "Phone", v.phone)
            docs.append(self.doc("billing", t + timedelta(days=40), f, "fraudring", inst,
                                 "Только данные оператора; других номеров с этим IMEI не упоминай."))
        self.cur = terrs[0]
        for drop, dcard in drops:
            f = self.F()
            f.org(self.bank_of(), "банк")
            dk = f.person(drop, "владелец карты", birth=True, address=True, phone=True)
            f.card(dcard, dk)
            f.line(f"- карта № {dcard}; за период поступили переводы от физических лиц на общую сумму "
                   f"{r.randint(4, 30) * 100_000} руб., средства сразу сняты наличными в банкоматах")
            docs.append(self.doc("bank_owner", self.when(2025, 100), f, "fraudring", inst))
        self.link("fraudring", inst,
                  "Связаны ли между собой телефонные мошенничества в разных городах округа?",
                  f"Номера {', '.join(phones)} работали в одном телефоне IMEI {handset}; деньги шли на карты "
                  f"жильцов одного общежития ({hostel.rsplit(',', 1)[0]}), где живёт и номинальный директор фирм-"
                  f"однодневок.",
                  [[f"tel:{p}", "USED_IN", f"imei:{handset}", [docs[2 * i + 1]]] for i, p in enumerate(phones)]
                  + [[drop, "ADDRESS", "общежитие", [docs[len(phones) * 2 + i]]] for i, (drop, _) in enumerate(drops)],
                  [f"tel:{phones[0]}", f"tel:{phones[-1]}"])

    # ---- honest noise -------------------------------------------------------
    def honest_procurement(self, terr):
        r = self.r
        self.cur = terr
        aid, staff = self.admins[terr[0]]
        win, *rest = r.sample(self.contractors[terr[0]], 3)
        subj, lo, hi = r.choice(PROCUREMENTS)
        price = r.randint(lo, hi) * 1_000_000
        bid = int(price * r.uniform(0.7, 0.9))
        num = f"0148300{r.randint(10000, 99999)}2{r.randint(3, 5)}000{r.randint(100, 999)}"
        when = self.when(2022, 900)
        f = self.F()
        f.org(aid, "заказчик", inn=True)
        f.person(staff["procure"], "председатель единой комиссии", job=True)
        f.person(staff["econ"], "член комиссии", job=True)
        f.line(f"- закупка: извещение № {num}, предмет: {subj}, НМЦК {price} руб.")
        f.org(win, "победитель", inn=True)
        f.line(f"- предложение победителя: {bid} руб.")
        for o in rest:
            f.org(o, "участник", inn=True)
        f.docref(f"извещение № {num}")
        f.amount(bid)
        self.doc("protocol", when, f, "noise", "proc")
        f = self.F()
        f.org(aid, "заказчик", inn=True, address=True)
        f.person(self.orgs[aid].head, "от заказчика подписал", job=True)
        f.org(win, "подрядчик", inn=True, ogrn=True, address=True)
        f.person(self.orgs[win].head, "от подрядчика подписал генеральный директор")
        f.line(f"- муниципальный контракт № {num}, предмет: {subj}, цена {bid} руб.")
        f.amount(bid)
        self.doc("contract", when + timedelta(days=12), f, "noise", "proc")

    def honest_egrul(self, terr):
        self.cur = terr
        oid = self.r.choice(self.contractors[terr[0]])
        x = self.ox[oid]
        f = self.F()
        fk = f.org(oid, "юридическое лицо", inn=True, ogrn=True, address=True, phone=True)
        f.line(f"- дата регистрации: {x['reg']}; основной вид деятельности 43.99 «Работы строительные "
               f"специализированные прочие»; среднесписочная численность работников: {self.r.randint(15, 140)}")
        f.rel(f.person(x["director"], "генеральный директор", inn=True), "DIRECTOR_OF", fk)
        f.rel(f.person(x["founders"][0][0], "учредитель (100% доли)", inn=True), "FOUNDER_OF", fk)
        self.doc("egrul", self.when(2023, 600), f, "noise", "egrul")

    def honest_inspection(self, terr):
        r = self.r
        self.cur = terr
        insp = r.choice(self.inspectors)
        boss = self.civ(terr, "M")
        dev = self.company(terr, f"ООО «Управляющая компания «{r.choice(COMPANY_NAMES)}»", director=boss.id,
                           founders=[(boss.id, 100)])
        site = self.address(terr, flat=False)
        f = self.F()
        f.person(insp, "проверку провёл", job=True)
        f.org(dev.id, "проверяемое лицо", inn=True, address=True)
        f.ent(f"addr:{site}", "Address", site)
        bad = r.random() < 0.6
        f.line(f"- объект: многоквартирный дом {site}; результат: "
               + ("выявлены нарушения (ненадлежащее содержание кровли и подвала), выдано предписание, "
                  "составлен протокол по ч. 1 ст. 7.22 КоАП РФ" if bad else "нарушений не выявлено"))
        self.doc("inspection", self.when(2022, 900), f, "noise", "insp")

    def background(self, n_cases):
        """Ordinary criminal cases, written exactly like gen-v1."""
        start = len(self.cases)
        self.build_cases(n_cases)
        wd = self.dump()
        planner = g1.Planner(wd, 99)
        for c in wd["cases"][start:]:
            for pd in planner._case_docs(c):
                facts, gold = g1.build_facts(pd, wd)
                self.docs.append({"type": pd["type"], "date": c["date_kusp"], "scheme": "noise",
                                  "instance": c["id"], "facts": facts, "note": "", **gold})

    # ---- assemble --------------------------------------------------------------
    def build(self, n_docs: int):
        r = self.r
        self.populate()
        self.populate2()
        T = TERRITORIES
        shell_info = [self.shell(f"S{i + 1}", T[i * 5]) for i in range(2)]
        shells = [s[0] for s in shell_info]
        for i in range(8):
            self.kickback(f"K{i + 1}", T[(i * 3 + 1) % len(T)], r.sample(shells[i % 2], 2))
        for i in range(6):
            self.cover(f"C{i + 1}", T[(i * 2) % len(T)], T[(i * 2 + 3) % len(T)])
        for i in range(5):
            self.fence(f"F{i + 1}", T[(i * 3 + 2) % len(T)], T[(i * 3 + 6) % len(T)])
        for i in range(6):
            self.bribe(f"B{i + 1}", T[(i * 2 + 1) % len(T)], shells[(i + 1) % 2])
        for i in range(5):
            self.inspection(f"I-{i + 1}", T[(i * 2 + 4) % len(T)])
        for i in range(4):
            self.fraudring(f"R{i + 1}", [T[(i + k * 3) % len(T)] for k in range(4)], shell_info[i % 2][2])
        n_signal = len(self.docs)
        for k in range(40):
            self.honest_procurement(T[k % len(T)])
        for k in range(20):
            self.honest_egrul(T[k % len(T)])
        for k in range(20):
            self.honest_inspection(T[k % len(T)])
        while len(self.docs) < n_docs:
            self.background(5)
        self.docs = self.docs[:n_docs] if len(self.docs) > n_docs else self.docs
        # shuffle doc ids so schemes are spread through the corpus
        order = list(range(len(self.docs)))
        r.shuffle(order)
        idmap = {old: f"K{new + 1:05d}" for new, old in enumerate(order)}
        for i, dd in enumerate(self.docs):
            dd["doc_id"] = idmap[i]
        for lk in self.links:
            for step in lk["chain"]:
                step[3] = [idmap[x] for x in step[3] if x in idmap]
        self.docs.sort(key=lambda x: x["doc_id"])
        return n_signal


def check_hidden(plan: dict) -> list[str]:
    """A link is hidden only if no single document holds both of its ends."""
    bad = []
    for lk in plan["links"]:
        a, b = lk["ends"]
        for dd in plan["docs"]:
            if dd["type"] in lk.get("official", ()):
                continue
            keys = {e["key"] for e in dd["entities"]}
            if a in keys and b in keys:
                bad.append(f"{lk['scheme']}/{lk['instance']}: {a} + {b} together in {dd['doc_id']} ({dd['type']})")
    return bad


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=21)
    ap.add_argument("--docs", type=int, default=1000)
    ap.add_argument("--out", default="plan.json")
    a = ap.parse_args()
    w = World2(a.seed)
    n_signal = w.build(a.docs)
    plan = {"docs": w.docs, "links": w.links,
            "persons": {k: v for k, v in w.dump()["persons"].items()}, "orgs_extra": w.ox}
    bad = check_hidden(plan)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, ensure_ascii=False, indent=1)
    by: dict[str, int] = {}
    for dd in w.docs:
        by[dd["scheme"]] = by.get(dd["scheme"], 0) + 1
    types: dict[str, int] = {}
    for dd in w.docs:
        types[dd["type"]] = types.get(dd["type"], 0) + 1
    print(f"docs={len(w.docs)} signal={n_signal} links={len(w.links)} by_scheme={by}")
    print(f"types={types}")
    print(f"hidden-check: {len(bad)} violations")
    for x in bad[:20]:
        print("  ", x)


if __name__ == "__main__":
    main()
