from QuantLib import (
    AUDCurrency,
    CADCurrency,
    CHFCurrency,
    DKKCurrency,
    EURCurrency,
    GBPCurrency,
    JPYCurrency,
    NOKCurrency,
    NZDCurrency,
    SEKCurrency,
    USDCurrency,
)

# Dictionary mapping ISO currency codes to QuantLib Currency instances
CURRENCIES: dict[str, object] = {
    "USD": USDCurrency(),
    "EUR": EURCurrency(),
    "GBP": GBPCurrency(),
    "JPY": JPYCurrency(),
    "CHF": CHFCurrency(),
    "CAD": CADCurrency(),
    "SEK": SEKCurrency(),  # Swedish krona
    "NOK": NOKCurrency(),  # Norwegian krone
    "DKK": DKKCurrency(),  # Danish krone
    "AUD": AUDCurrency(),
    "NZD": NZDCurrency(),
}
