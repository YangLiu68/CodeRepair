# Converted prices off by one minor unit for some currency pairs

Our Kuwait storefront shows prices converted from our JPY price list. For many products the KWD
price is 1 fils higher than the price in finance's spreadsheet. Example: ¥100 shows as
KD 0.203; the spreadsheet says KD 0.202 (rates 152.37 JPY per USD and 0.3071 KWD per USD).
USD → KWD and JPY → USD conversions always match the spreadsheet.

I suspect we round half-up and finance uses banker's rounding.

`tests/test_fx.py::test_cross_conversion_rounds_only_once` fails.
