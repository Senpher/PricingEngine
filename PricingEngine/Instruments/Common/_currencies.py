from QuantLib import Currency

CURRENCIES = {c().code(): c() for c in Currency.__subclasses__()}
