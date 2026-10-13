# Economic pilot simulation

This offline model asks whether declared offers can meet declared needs under
prices, capacity, delivery lead times, payment delays and credit limits. It
creates a separate analysis state and never submits orders to the live ledger.
Its automatic signatures use deterministic **simulation-only** keys, not real
owner keys or consent. Posted payments are checked with the same mutual-credit
transition rules used by the project.

## Start with a reproducible synthetic example

From the project root, with Python 3.12 and the network dependency installed:

```text
python -B -m economy example --participants 30 --days 30 --out economy/results/example_30
python -B -m economy run --input economy/results/example_30 --out economy/results/baseline_30 --seed 42 --replications 5
python -B -m economy compare --input economy/results/example_30 --out economy/results/comparison_30 --seed 42 --replications 10
```

Use new directories. `compare` evaluates baseline, tight credit, capacity
reduction, severe shortage, longer payment delay, an exogenous price shock and settlement default.
Each run is bounded by days, rows, orders, matching checks and output bytes.
The default output quota is 10 MB; inputs are limited to 2 MB. No neural
training, new dependency or persistent corpus is required.

The generated example is labelled `synthetic_example`. Its prices, probabilities
and capacities are invented test inputs; results cannot establish real-world
viability. Repeated seeds show sensitivity in this model, not a statistical
confidence interval for the real community.

`capacity_shortage` leaves one quarter of declared total supply and at most one
booking per offer/day; `severe_shortage` leaves one tenth. If the original offers
contain large spare capacity, even the first reduction may still fulfill all
requests. That is evidence about the example's assumptions, not proof that a
real network is resistant to shortages.

## Prepare a small field pilot

Choose an initial group, for example 20–50 willing participants over 30–60 days.
Agree in advance on units, prices, consent, data visibility, credit limits,
delivery confirmation, payment timing and dispute handling. Identify real
offers and requests rather than inferring them from wallet balances.

Collect only the pseudonymous fields needed for analysis. Keep the private
mapping to people outside the input dataset and agree on retention and access.
The input label `field_observations` is a declaration by the collector, not a
verification by the program. Public Git should contain code and synthetic
examples, not these field records.

First run historical observations without modifying quotes or capacities.
Compare simulated matching with completed exchanges, actual delivery dates
and actual payment dates. Adjust modelling assumptions transparently. Use
later observations as a separate validation period; do not call data used
to tune the model an independent validation sample.

## Input directory

Create empty tables for the observations, choosing the collectively agreed
debt limit rather than copying synthetic quotes:

```text
python -B -m economy template --days 30 --total-debt-limit 50000 --out economy/results/field_pilot
```

The number 50000 is an illustrative parameter, not a recommended universal limit.
Populate the empty tables before running; the blank template is deliberately
rejected as a simulation input. The directory contains `settings.json` and
four CSV files. CSV headers must match the schema exactly. Numeric fields use
integers, and prices use quanta.

### settings.json

| Field | Meaning |
|---|---|
| `version` | Input format, currently 1 |
| `data_origin` | `synthetic_example`, `hypothetical` or `field_observations` |
| `days` | Observation/simulation window, 1–180; day 0 is the start |
| `initial_allocation_quanta` | Optional simulated quota per participant |
| `total_debt_limit_quanta` | Collective limit including the reserve debit |
| `max_orders` | Computational order limit, at most 10,000 |
| `max_match_checks` | Computational matching limit, at most 1,000,000 |
| `notes` | Short methodological note without personal information |

A positive initial quota creates the corresponding reserve debit. It is not
backed by goods merely because it appears in this model. A real primary
allocation requires its accepted collective commitment and resources.

### participants.csv

```csv
participant_id,debt_limit_quanta,credit_limit_quanta
p001,1000,3000
p002,1000,3000
```

Limits are agreed inputs, not an AI score. The simulation supports up to 1000
participants. Participants start at zero, or receive the explicit initial
allocation; arbitrary positive opening balances are not imported.

### offers.csv

```csv
offer_id,seller_id,resource_id,unit,quantity_total,quantity_per_day,price_quanta,available_day,expires_day,delivery_delay_days,payment_delay_days,delivery_success_bps,settlement_success_bps
o001,p001,repair,repair_30min,10,2,500,0,29,1,2,10000,10000
```

`quantity_total` is the total available stock/capacity in the window;
`quantity_per_day` bounds bookings on a day. Define the unit precisely, such
as a 30-minute repair, one food basket or one tool-day. One resource ID must
have one unit throughout the dataset.

Success fields are probabilities in basis points: 10000 = 100%, 9500 = 95%.
Estimate them from observed outcomes when available, or explicitly describe
them as scenario assumptions. Do not assign moral or creditworthiness labels
to people. Offer prices are declared fixed quotes; the price-shock scenario
changes future quotes by 25% halfway through the window, not existing contracts.

If several offers use the same worker, tool or input, divide the declared
capacities so they do not promise the same capacity several times. The current
model does not solve a full shared-labour, material-input or spatial scheduling
problem. Multiple time-window offer rows can represent changing observations.
Quotes and buyer price ceilings are strictly positive in this first model.
Free donations, volunteering without a credit transfer and conversion of a
service into a cash price are not simulated. Record free activities separately
rather than assigning them an invented paid quote.

### needs.csv

```csv
need_id,buyer_id,resource_id,unit,quantity,max_unit_price_quanta,earliest_day,deadline_day,priority
n001,p002,repair,repair_30min,1,600,0,7,3
```

`deadline_day` is the last acceptable delivery day. Priority is 1–5 and applies
to a request, not a person. The matcher randomizes equal-priority ties using
the run seed, then considers deadlines, prices and lead times. It is a bounded
greedy allocator, not a proof of the globally optimal assignment.

### resource_limits.csv

```csv
resource_id,unit,quantity_cap
repair,repair_30min,8
```

This is a declared physical-output/capacity budget for the whole window.
It is independent of money/credit. A header-only table means these budgets
were not supplied. Committed capacity is counted even if delivery later
fails; it must not be interpreted as measured consumption or emissions.
Water, energy, raw-material use and lifecycle impacts need separate measurements
or an extension of the resource model. `energy_joules` remains null.

## Order and settlement lifecycle

1. The offer must match the resource/unit, date, price budget and delivery deadline.
2. Stock and daily capacity are reserved, within any supplied physical budget.
3. Buyer spending capacity is reserved. Pending incoming payments are not
   treated as spendable balances. Seller credit room and collective worst-case
   debt exposure are reserved as well.
4. Delivery either succeeds or fails at its scheduled date.
5. Successful delivery fulfills the request. Payment is posted only at its
   scheduled settlement date if settlement succeeds.

A delivery failure releases the financial lock, leaving the request unfulfilled.
A delivered but unpaid order remains a receivable/liability with its lock;
the model does not silently forgive it or invent a completed payment. A payment
scheduled beyond the observation window is pending, not defaulted. Default
resolution, write-offs, deposits and dispute procedures are not implemented.

Each posted exchange preserves zero-sum balances. The report distinguishes
posted gross credit from outstanding obligations and conservative reserved
debt exposure. None of these figures proves real resources exist.

## Reports and interpretation

- `report.json`: input hashes and origin, scenario assumptions, repeated-seed
  summaries, needs met, unpaid value, credit peaks and blocking attempts.
- `daily.csv`: representative-run posted credit/debt, reservations and defaults.
- `orders.json` and `balances.json`: optional local pseudonymous details with
  `--details`; omitted by default.

Quantities are reported separately by resource/unit: repairs and food baskets
must not be added as interchangeable physical units. Overall fulfillment
uses mean request fractions and mean buyer fractions. The least-served buyer
decile is an aggregate diagnostic, not an admission score. Blocking counts
are repeated matching attempts, not unique people or unmet units.

Incomplete runs that hit a computation limit are explicitly marked. Their
results must not be treated as an economic feasibility verdict. Min/max across
replications describe the selected seeds only.

## Decide acceptance criteria before reviewing results

The group should choose thresholds and a validation period for:

- fulfillment of essential needs within their deadlines;
- delivered value actually settled and time to payment;
- arrears and exposure compared with collectively accepted limits;
- access of the least-served participants and reasons for unmet requests;
- resource-budget compliance and measured environmental impacts;
- concentration of credits, recurring bottlenecks and recovery after shortages.

There is no universal pass threshold. All needs fulfilled in a synthetic
zero-default scenario does not establish real feasibility. A useful decision
requires capacity evidence, observed delivery/payment records, sensitivity
tests and independent later observations. An increase in token quantity alone
does not resolve a shortage of goods or useful services.
