"""Build a synthetic "world" of criminal cases with known ground truth.

Every document is later written by an LLM from a slice of this world, so for each
document we know exactly which entities and relations it mentions (gold.jsonl).
The world is built so that extraction and entity resolution have something real
to get right or wrong:

  * the same person shows up in several cases (repeat suspects, witnesses,
    pawnshop clerks, police officers who sign many papers);
  * namesakes: two different people with the same surname and initials but a
    different full name and birth date — they must NOT be merged;
  * shared phones / addresses across cases.

Stdlib only, deterministic for a given --seed.

  python world.py --cases 200 --seed 7 --out world.json
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

SURNAMES = """Абрамов Агапов Акимов Алексеев Андреев Анисимов Антонов Артемьев Афанасьев Баранов
Белов Белоусов Беляев Блинов Бобров Богданов Борисов Быков Васильев Виноградов Власов
Волков Воробьёв Гаврилов Голубев Гончаров Горбунов Гордеев Григорьев Гусев Давыдов Данилов
Демидов Денисов Дмитриев Дорофеев Евдокимов Ежов Елисеев Ершов Ефимов Жданов Жуков Зайцев
Захаров Зимин Зотов Зуев Игнатов Ильин Исаев Казаков Калинин Капустин Карпов Кириллов Киселёв
Климов Ковалёв Козлов Колесников Комаров Кондратьев Копылов Королёв Корнилов Котов Крылов
Кудрявцев Кузьмин Куликов Лаврентьев Лапин Лебедев Лихачёв Лобанов Логинов Лукин Макаров
Максимов Малышев Маслов Матвеев Медведев Мельников Миронов Митрофанов Михеев Моисеев Муравьёв
Назаров Некрасов Никитин Никифоров Новиков Носов Овчинников Орехов Осипов Павлов Панов Панфилов
Пестов Петухов Поляков Пономарёв Потапов Прохоров Рогов Родионов Романов Русаков Рыбаков Савельев
Сазонов Самойлов Сафонов Селезнёв Семёнов Сидоров Симонов Ситников Смирнов Соболев Соколов
Соловьёв Сорокин Степанов Субботин Суханов Тарасов Терентьев Тимофеев Титов Тихонов Третьяков
Трофимов Тюрин Уваров Ульянов Устинов Фадеев Фёдоров Филиппов Фомин Фролов Харитонов Хохлов
Цветков Чернов Шарапов Шестаков Широков Шубин Щербаков Юдин Яковлев Якушев Яшин""".split()

MALE = """Александр Алексей Анатолий Андрей Антон Аркадий Артём Борис Вадим Валентин Валерий
Василий Виктор Виталий Владимир Владислав Вячеслав Геннадий Георгий Глеб Григорий Даниил
Денис Дмитрий Евгений Егор Иван Игорь Илья Кирилл Константин Леонид Максим Матвей Михаил
Никита Николай Олег Павел Пётр Роман Руслан Семён Сергей Станислав Степан Тимофей Фёдор
Юрий Ярослав""".split()

FEMALE = """Алина Алла Анастасия Ангелина Анна Валентина Валерия Вера Вероника Виктория Галина
Дарья Диана Екатерина Елена Елизавета Жанна Зинаида Ирина Кристина Ксения Лариса Людмила
Маргарита Марина Мария Надежда Наталья Нина Оксана Ольга Полина Светлана Софья Тамара
Татьяна Ульяна Юлия Яна""".split()

# father's name -> (male patronymic, female patronymic)
PATRONYMIC = {
    "Александр": ("Александрович", "Александровна"), "Алексей": ("Алексеевич", "Алексеевна"),
    "Андрей": ("Андреевич", "Андреевна"), "Борис": ("Борисович", "Борисовна"),
    "Василий": ("Васильевич", "Васильевна"), "Виктор": ("Викторович", "Викторовна"),
    "Владимир": ("Владимирович", "Владимировна"), "Геннадий": ("Геннадьевич", "Геннадьевна"),
    "Григорий": ("Григорьевич", "Григорьевна"), "Дмитрий": ("Дмитриевич", "Дмитриевна"),
    "Евгений": ("Евгеньевич", "Евгеньевна"), "Иван": ("Иванович", "Ивановна"),
    "Игорь": ("Игоревич", "Игоревна"), "Константин": ("Константинович", "Константиновна"),
    "Леонид": ("Леонидович", "Леонидовна"), "Михаил": ("Михайлович", "Михайловна"),
    "Николай": ("Николаевич", "Николаевна"), "Олег": ("Олегович", "Олеговна"),
    "Павел": ("Павлович", "Павловна"), "Пётр": ("Петрович", "Петровна"),
    "Роман": ("Романович", "Романовна"), "Сергей": ("Сергеевич", "Сергеевна"),
    "Степан": ("Степанович", "Степановна"), "Юрий": ("Юрьевич", "Юрьевна"),
    "Ярослав": ("Ярославович", "Ярославовна"), "Фёдор": ("Фёдорович", "Фёдоровна"),
}

# (district/okrug, settlement, police unit short name, unit phone code)
TERRITORIES = [
    ("г.о. Подольск", "г. Подольск", "Подольск", "4967"),
    ("г.о. Мытищи", "г. Мытищи", "Мытищинское", "495"),
    ("г.о. Щёлково", "г. Щёлково", "Щёлковское", "496"),
    ("г.о. Коломна", "г. Коломна", "Коломенское", "4966"),
    ("Раменский г.о.", "г. Раменское", "Раменское", "49646"),
    ("г.о. Чехов", "г. Чехов", "Чеховское", "49672"),
    ("Ленинский г.о.", "г. Видное", "Ленинское", "495"),
    ("г.о. Серпухов", "г. Серпухов", "Серпуховское", "4967"),
    ("г.о. Балашиха", "г. Балашиха", "Балашихинское", "495"),
    ("г.о. Красногорск", "г. Красногорск", "Красногорское", "495"),
]

STREETS = """Ленина Советская Мира Гагарина Пушкина Лесная Садовая Школьная Молодёжная Центральная
Кирова Октябрьская Пролетарская Комсомольская Набережная Заводская Полевая Новая Зелёная
Луговая Парковая Строителей Чехова Толстого Некрасова Маяковского Победы Юбилейная Спортивная
Северная Южная Рабочая Первомайская Вокзальная Береговая Железнодорожная Колхозная""".split()

RANKS_POLICE = ["лейтенант полиции", "старший лейтенант полиции", "капитан полиции", "майор полиции",
                "подполковник полиции"]
POSITIONS_POLICE = ["оперуполномоченный ОУР", "участковый уполномоченный полиции",
                    "дознаватель ОД", "следователь СО", "оперативный дежурный ДЧ"]

SHOP_CHAINS = ["Пятёрочка", "Магнит", "Перекрёсток", "Дикси", "Верный", "Ашан", "Лента",
               "Спар", "Билла", "Ароматный мир"]
SHOP_ORGS = ["Агроторг", "Тандер", "Торговый дом Перекрёсток", "Дикси Юг", "Союз Святого Иоанна Воина",
             "Ашан", "Лента", "Спар Миддл Волга", "Альбион-2002", "Ароматный мир"]
PAWN_NAMES = ["Золотой Стандарт", "Ломбард Центральный", "Комиссионный 24", "Скупка-Плюс",
              "Удача", "Залог-Сервис", "Каскад", "Аврора", "Меридиан", "Северный",
              "Фортуна", "Магнат", "Престиж", "Эталон", "Капитал-Ломбард"]
BANKS = ["ПАО Сбербанк", "Банк ВТБ (ПАО)", "АО «Тинькофф Банк»", "АО «Альфа-Банк»", "ПАО «Совкомбанк»"]
CAR_MODELS = ["Лада Гранта", "Лада Веста", "Киа Рио", "Хендай Солярис", "Рено Логан", "Фольксваген Поло",
              "Шкода Октавия", "Тойота Камри", "Ниссан Альмера", "Шевроле Нива"]
PRODUCTS = [("Кофе «Жокей» 250 г", 389, 612), ("Сыр «Ламбер» 230 г", 299, 455), ("Масло сливочное «Брест-Литовск» 180 г", 189, 264),
            ("Шампунь «Head&Shoulders» 400 мл", 459, 690), ("Виски «Джемесон» 0,7 л", 1490, 2199),
            ("Коньяк «Старейшина» 0,5 л", 690, 999), ("Колбаса «Докторская» 500 г", 310, 449),
            ("Шоколад «Риттер Спорт» 100 г", 99, 159), ("Икра красная «Русское море» 95 г", 549, 799),
            ("Бритвенные кассеты «Gillette Fusion» 4 шт", 1290, 1890), ("Сёмга слабосолёная 200 г", 499, 749),
            ("Энергетик «Ред Булл» 0,473 л", 129, 189)]
STOLEN_ITEMS = [("мобильный телефон «iPhone 13»", 38000, 62000), ("мобильный телефон «Samsung Galaxy A54»", 18000, 29000),
                ("ноутбук «Lenovo IdeaPad 3»", 27000, 45000), ("велосипед «Stels Navigator 700»", 14000, 23000),
                ("женская сумка из натуральной кожи", 4500, 11000), ("золотая цепочка 585 пробы", 15000, 42000),
                ("перфоратор «Makita HR2470»", 8000, 13000), ("бензопила «Stihl MS 180»", 14000, 21000),
                ("планшет «Huawei MatePad»", 16000, 26000), ("наручные часы «Casio Edifice»", 9000, 17000)]
SUBSTANCES = ["мефедрон (4-метилметкатинон)", "гашиш", "героин (диацетилморфин)",
              "N-метилэфедрон (альфа-PVP)", "каннабис (марихуана)"]

CRIME_TYPES = {
    # key: (article, short description, outcome weights {charged, refused})
    "shoplifting": ("ч. 1 ст. 158 УК РФ", "кража товара из магазина", 0.7),
    "burglary": ("п. «а» ч. 3 ст. 158 УК РФ", "кража из жилища", 0.5),
    "car_theft": ("п. «в» ч. 2 ст. 158 УК РФ", "кража имущества из автомобиля", 0.4),
    "phone_fraud": ("ч. 2 ст. 159 УК РФ", "телефонное мошенничество", 0.4),
    "robbery": ("ч. 1 ст. 161 УК РФ", "грабёж", 0.7),
    "drugs": ("п. «б» ч. 3 ст. 228.1 УК РФ", "незаконный сбыт наркотических средств", 0.9),
    "beating": ("ст. 116.1 УК РФ", "побои", 0.3),
    "joyriding": ("ч. 1 ст. 166 УК РФ", "неправомерное завладение автомобилем без цели хищения", 0.6),
    "contract": ("ч. 1 ст. 159 УК РФ", "невыполнение обязательств по договору купли-продажи", 0.1),
}


@dataclass
class Person:
    id: str
    surname: str
    name: str
    patronymic: str
    sex: str
    birth: str  # dd.mm.yyyy
    address: str | None = None
    phone: str | None = None
    job: str | None = None  # free text, e.g. "приёмщик ООО «Каскад»"
    rank: str | None = None
    position: str | None = None
    unit: str | None = None  # Org id for police staff / employer id
    namesake_of: str | None = None

    @property
    def full(self) -> str:
        return f"{self.surname} {self.name} {self.patronymic}"

    @property
    def short(self) -> str:
        return f"{self.surname} {self.name[0]}.{self.patronymic[0]}."


@dataclass
class Org:
    id: str
    kind: str  # police | shop | pawnshop | bank | company
    name: str
    address: str | None = None
    phone: str | None = None
    head: str | None = None  # Person id


@dataclass
class Case:
    id: str
    crime: str
    article: str
    descr: str
    outcome: str  # charged | refused
    territory: str
    kusp: str
    date_event: str
    date_kusp: str
    unit: str  # police Org id
    officers: list[str]  # Person ids: [operative, investigator/dознаватель, chief]
    victim: str | None
    suspects: list[str]
    witnesses: list[str]
    place: str  # address of the event
    orgs: list[str] = field(default_factory=list)  # shops / pawnshops / banks involved
    items: list[dict] = field(default_factory=list)  # {"name","price","qty"}
    amount: int = 0
    vehicle: dict | None = None
    extra: dict = field(default_factory=dict)


class World:
    def __init__(self, seed: int):
        self.r = random.Random(seed)
        self.persons: dict[str, Person] = {}
        self.orgs: dict[str, Org] = {}
        self.cases: list[Case] = []
        self._used_phones: set[str] = set()
        self._used_names: set[tuple[str, str, str]] = set()

    # ---- primitives -------------------------------------------------------
    def phone_mobile(self) -> str:
        while True:
            p = "+79" + "".join(str(self.r.randint(0, 9)) for _ in range(9))
            if p not in self._used_phones:
                self._used_phones.add(p)
                return p

    def phone_city(self, code: str) -> str:
        n = 10 - len(code)
        while True:
            p = "+7" + code + "".join(str(self.r.randint(0, 9)) for _ in range(n))
            if p not in self._used_phones:
                self._used_phones.add(p)
                return p

    def address(self, terr: tuple, flat: bool = True) -> str:
        _, town, _, _ = terr
        a = f"Московская область, {town}, ул. {self.r.choice(STREETS)}, д. {self.r.randint(1, 140)}"
        if flat:
            a += f", кв. {self.r.randint(1, 320)}"
        return a

    def day(self, start: date, span: int) -> date:
        return start + timedelta(days=self.r.randint(0, span))

    @staticmethod
    def fmt(d: date) -> str:
        return d.strftime("%d.%m.%Y")

    def person(self, sex: str | None = None, *, age=(18, 70), surname: str | None = None,
               initials: tuple[str, str] | None = None) -> Person:
        sex = sex or self.r.choice("MMMF")
        for _ in range(1000):
            base = surname or self.r.choice(SURNAMES)
            father = self.r.choice(list(PATRONYMIC))
            if sex == "M":
                name = self.r.choice(MALE)
                sur = base
                pat = PATRONYMIC[father][0]
            else:
                name = self.r.choice(FEMALE)
                sur = female_surname(base)
                pat = PATRONYMIC[father][1]
            if initials and (name[0], pat[0]) != initials:
                continue
            key = (sur, name, pat)
            if key in self._used_names:
                continue
            self._used_names.add(key)
            break
        today = date(2025, 6, 1)
        born = today - timedelta(days=self.r.randint(age[0] * 365, age[1] * 365))
        p = Person(id=f"P{len(self.persons) + 1:04d}", surname=sur, name=name, patronymic=pat,
                   sex=sex, birth=self.fmt(born))
        self.persons[p.id] = p
        return p

    def org(self, kind: str, name: str, terr: tuple | None, *, phone_mobile=False) -> Org:
        o = Org(id=f"O{len(self.orgs) + 1:04d}", kind=kind, name=name)
        if terr:
            o.address = self.address(terr, flat=False)
            o.phone = self.phone_mobile() if phone_mobile else self.phone_city(terr[3])
        self.orgs[o.id] = o
        return o

    # ---- static population ------------------------------------------------
    def populate(self) -> None:
        r = self.r
        self.units: dict[str, list] = {}
        for terr in TERRITORIES:
            unit = self.org("police", f"УМВД России «{terr[2]}»" if terr[2] != "Подольск"
                            else "УМВД России по г.о. Подольск", terr)
            staff = []
            for i in range(6):
                p = self.person(age=(24, 50))
                p.rank = RANKS_POLICE[min(i // 2 + r.randint(0, 1), 3)]
                p.position = POSITIONS_POLICE[i % len(POSITIONS_POLICE)]
                p.unit = unit.id
                staff.append(p.id)
            chief = self.person("M", age=(40, 55))
            chief.rank, chief.position, chief.unit = "подполковник полиции", "начальник", unit.id
            unit.head = chief.id
            # 2 pawnshops + 2 shops per territory, each with a director and a clerk
            pawns, shops = [], []
            for _ in range(2):
                pw = self.org("pawnshop", f"ООО «{r.choice(PAWN_NAMES)}»", terr, phone_mobile=True)
                d = self.person(age=(30, 65)); d.job, d.unit = "генеральный директор", pw.id
                c = self.person(age=(20, 55)); c.job, c.unit = "приёмщик", pw.id
                c.phone = self.phone_mobile()
                pw.head = d.id
                pawns.append(pw.id)
            for _ in range(2):
                i = r.randrange(len(SHOP_CHAINS))
                sh = self.org("shop", f"магазин «{SHOP_CHAINS[i]}» ООО «{SHOP_ORGS[i]}»", terr)
                d = self.person(age=(25, 55)); d.job, d.unit = "директор магазина", sh.id
                g = self.person(age=(25, 60)); g.job, g.unit = "специалист по экономической безопасности", sh.id
                sh.head = d.id
                shops.append(sh.id)
            self.units[unit.id] = [terr, staff, chief.id, pawns, shops]
        for b in BANKS:
            self.org("bank", b, None)

    # ---- cases -------------------------------------------------------------
    def build_cases(self, n: int) -> None:
        r = self.r
        unit_ids = list(self.units)
        crimes = list(CRIME_TYPES)
        # pools for recurrence: repeat offenders + frequent witnesses
        repeaters: list[str] = []
        witnesses_pool: list[str] = []
        for k in range(n):
            crime = crimes[k % len(crimes)] if k < len(crimes) * 2 else r.choice(crimes)
            article, descr, p_charged = CRIME_TYPES[crime]
            uid = r.choice(unit_ids)
            terr, staff, chief, pawns, shops = self.units[uid]
            d_event = self.day(date(2016, 1, 1), 9 * 365)
            d_kusp = d_event + timedelta(days=r.choice([0, 0, 0, 1, 2]))
            c = Case(id=f"C{k + 1:04d}", crime=crime, article=article, descr=descr,
                     outcome="charged" if r.random() < p_charged else "refused",
                     territory=terr[0], kusp=f"{r.randint(100, 9999)}",
                     date_event=self.fmt(d_event), date_kusp=self.fmt(d_kusp), unit=uid,
                     officers=[r.choice(staff), r.choice(staff), chief], victim=None,
                     suspects=[], witnesses=[], place=self.address(terr))
            # suspect: 30% a repeater from earlier cases (same person, new case)
            n_susp = 2 if crime in ("burglary", "robbery", "shoplifting") and r.random() < 0.3 else 1
            for _ in range(n_susp):
                if repeaters and r.random() < 0.3:
                    sid = r.choice(repeaters)
                else:
                    s = self.person(age=(18, 55))
                    s.address = self.address(terr)
                    s.phone = self.phone_mobile()
                    sid = s.id
                    repeaters.append(sid)
                c.suspects.append(sid)
            if crime not in ("drugs",):
                v = self.person()
                v.address = self.address(terr)
                v.phone = self.phone_mobile()
                c.victim = v.id
            for _ in range(r.choice([0, 1, 1, 2])):
                if witnesses_pool and r.random() < 0.15:
                    wid = r.choice(witnesses_pool)
                else:
                    w = self.person()
                    w.address = self.address(terr)
                    w.phone = self.phone_mobile()
                    wid = w.id
                    witnesses_pool.append(wid)
                c.witnesses.append(wid)
            self._crime_details(c, terr, pawns, shops)
            self.cases.append(c)
        self._add_namesakes()

    def _crime_details(self, c: Case, terr, pawns, shops) -> None:
        r = self.r
        if c.crime == "shoplifting":
            sh = self.orgs[r.choice(shops)]
            c.orgs.append(sh.id)
            c.place = sh.address
            c.victim = None  # the shop's representative is the victim
            rep = [p for p in self.persons.values() if p.unit == sh.id and p.job != "директор магазина"][0]
            c.extra["representative"] = rep.id
            for name, lo, hi in r.sample(PRODUCTS, r.randint(2, 5)):
                qty = r.randint(1, 6)
                c.items.append({"name": name, "price": r.randint(lo, hi), "qty": qty})
            c.amount = sum(i["price"] * i["qty"] for i in c.items)
        elif c.crime in ("burglary", "robbery", "car_theft"):
            for name, lo, hi in r.sample(STOLEN_ITEMS, r.randint(1, 3)):
                c.items.append({"name": name, "price": r.randint(lo, hi), "qty": 1})
            c.amount = sum(i["price"] for i in c.items)
            c.orgs.extend(pawns)  # operatives check local pawnshops
            if c.crime == "burglary":
                c.place = self.persons[c.victim].address
            if c.crime == "car_theft":
                c.vehicle = self._vehicle(c.victim)
        elif c.crime == "joyriding":
            c.vehicle = self._vehicle(c.victim)
        elif c.crime == "phone_fraud":
            bank = r.choice([o for o in self.orgs.values() if o.kind == "bank"])
            c.orgs.append(bank.id)
            c.amount = r.randint(15, 480) * 1000 + r.choice([0, 500, 0])
            c.extra["fraud_phone"] = self.phone_mobile()
            c.extra["card"] = "".join(str(r.randint(0, 9)) for _ in range(4))
        elif c.crime == "drugs":
            c.extra["substance"] = r.choice(SUBSTANCES)
            c.extra["mass_g"] = round(r.uniform(0.4, 12.0), 2)
            c.amount = r.choice([1500, 2000, 2500, 3000, 3500, 5000])
            c.extra["buyer_alias"] = r.choice(["закупщик «Иванов»", "закупщик «Покупатель»", "закупщик «Сергей»"])
            # contacts in the dealer's phone: mostly nicknames + a few real people
            s = self.persons[c.suspects[0]]
            nicks = ["Белый", "Кот", "Брат", "Дом", "МТС", "Такси", "Сир", "Ватсап", "Север", "Синий"]
            book = []
            for _ in range(r.randint(10, 22)):
                book.append({"label": f"{r.choice(MALE)} {r.choice(nicks)}", "phone": self.phone_mobile()})
            for oth in r.sample(list(self.persons.values()), 3):
                if oth.phone and oth.id != s.id and not oth.rank:
                    book.append({"label": oth.short, "phone": oth.phone, "person": oth.id})
            r.shuffle(book)
            c.extra["phone_book"] = book
            c.extra["sim"] = s.phone
        elif c.crime == "beating":
            c.extra["injuries"] = r.choice(["ссадины лица", "гематома левого плеча",
                                            "ушиб мягких тканей головы", "кровоподтёки грудной клетки"])
        elif c.crime == "contract":
            comp = self.org("company", f"ООО «{r.choice(['Северная Дверная Компания', 'Окна-Профи', 'СтройМаркет', 'Мебель-Сити', 'ТеплоДом'])}»", terr)
            d = self.person(age=(30, 60)); d.job, d.unit = "генеральный директор", comp.id
            comp.head = d.id
            c.orgs.append(comp.id)
            c.items.append({"name": r.choice(["входная металлическая дверь", "кухонный гарнитур",
                                              "пластиковые окна", "шкаф-купе"]),
                            "price": r.randint(25, 180) * 1000, "qty": 1})
            c.amount = c.items[0]["price"]

    def _vehicle(self, owner: str | None) -> dict:
        r = self.r
        letters = "АВЕКМНОРСТУХ"
        plate = (f"{r.choice(letters)}{r.randint(100, 999)}{r.choice(letters)}{r.choice(letters)}"
                 f" {r.choice([50, 150, 750, 190, 790, 77])}")
        return {"model": r.choice(CAR_MODELS), "plate": plate, "color": r.choice(
            ["белого", "серого", "чёрного", "синего", "красного", "серебристого"]), "owner": owner}

    def _add_namesakes(self) -> None:
        """Clone ~15 suspects/victims into a namesake: same surname + initials,
        different full name, birth date, address and phone. Put them into other
        cases so the corpus contains 'Иванов А.С.' who are two different people."""
        r = self.r
        pool = [c for c in self.cases if c.suspects]
        for c in r.sample(pool, min(15, len(pool))):
            orig = self.persons[c.suspects[0]]
            twin = self.person(orig.sex, surname=_base(orig.surname, orig.sex),
                               initials=(orig.name[0], orig.patronymic[0]))
            if twin.short != orig.short:
                continue
            twin.namesake_of = orig.id
            other = r.choice([x for x in self.cases if x is not c])
            terr = next(t for t in TERRITORIES if t[0] == other.territory)
            twin.address = self.address(terr)
            twin.phone = self.phone_mobile()
            other.witnesses.append(twin.id)

    def dump(self) -> dict:
        return {"persons": {k: asdict(v) | {"full": v.full, "short": v.short} for k, v in self.persons.items()},
                "orgs": {k: asdict(v) for k, v in self.orgs.items()},
                "cases": [asdict(c) for c in self.cases]}


def female_surname(base: str) -> str:
    if base.endswith("ий"):
        return base[:-2] + "ая"
    if base.endswith(("ов", "ев", "ёв", "ин", "ын")):
        return base + "а"
    return base


def _base(surname: str, sex: str) -> str:
    if sex == "F" and surname.endswith("ая"):
        return surname[:-2] + "ий"
    if sex == "F" and surname.endswith("а"):
        return surname[:-1]
    return surname


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=int, default=200)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="world.json")
    a = ap.parse_args()
    w = World(a.seed)
    w.populate()
    w.build_cases(a.cases)
    data = w.dump()
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    rep = sum(1 for p in data["persons"].values() if sum(
        p["id"] in (c["suspects"] + c["witnesses"] + [c["victim"]]) for c in data["cases"]) > 1)
    twins = sum(1 for p in data["persons"].values() if p["namesake_of"])
    print(f"persons={len(data['persons'])} orgs={len(data['orgs'])} cases={len(data['cases'])} "
          f"recurring_case_persons={rep} namesakes={twins}")


if __name__ == "__main__":
    main()
