"""The currencies a gift's price may be given in (lists plan D3).

The active ISO 4217 codes of circulating currencies, as of 2026: fund codes
(BOV, CHE, CLF...), precious metals (XAU...), special drawing rights (XDR) and
the testing codes (XTS, XXX) are left out, since no gift is priced in them.
Withdrawn codes are left out too (HRK since 2023, BGN since 2026, ANG replaced
by XCG, SLL by SLE, ZWL by ZWG). A code added here later is a plain change; a
code removed would refuse edits of gifts already priced in it.
"""

CURRENCIES = frozenset(
    """
    AED AFN ALL AMD AOA ARS AUD AWG AZN BAM BBD BDT BHD BIF BMD BND BOB BRL BSD
    BTN BWP BYN BZD CAD CDF CHF CLP CNY COP CRC CUP CVE CZK DJF DKK DOP DZD EGP
    ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF GTQ GYD HKD HNL HTG HUF IDR ILS
    INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT LAK LBP LKR
    LRD LSL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MYR MZN NAD NGN
    NIO NOK NPR NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD RUB RWF SAR SBD
    SCR SDG SEK SGD SHP SLE SOS SRD SSP STN SVC SYP SZL THB TJS TMT TND TOP TRY
    TTD TWD TZS UAH UGX USD UYU UZS VED VES VND VUV WST XAF XCD XCG XOF XPF YER
    ZAR ZMW ZWG
    """.split()
)
