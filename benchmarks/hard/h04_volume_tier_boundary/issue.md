# API usage invoices too low for customers who land exactly on a tier limit

Billing ops noticed a handful of Developer-plan invoices that are lower than the price list.
All of them belong to customers whose monthly API usage was exactly on a tier limit (10,000 or
50,000 calls).

Example: cus_8812 made exactly 10,000 API calls in March. The price list says up to 10,000 calls
cost $0.002 each, so we expected $20.00 for March usage on the April invoice. The invoice line
reads "API calls (10,000 in 2027-03-01..2027-04-01)" and charges $15.00.

Our guess is that the last usage events of the month are dropped: this customer's last calls
were at 23:59 UTC on March 31, and we had a timezone problem with usage last year. Could someone
look at how usage is assigned to billing periods? Customers at 9,999 or 10,001 calls look right.
