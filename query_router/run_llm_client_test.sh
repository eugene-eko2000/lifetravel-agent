#!/bin/bash

python test_llm_client.py \
    "Please find a flight and a hotel for a trip to London from Zurich from 15.03.2026 to 21.03.2026.
    The flight cost should be max. 200 GBP per traveller for the whole trip, the hotel cost is max. 300 GBP per day per person.
    The flight should be economy class.
    We would like to find a hotel close to the shard skyscraper.
    There will be three travelers on this trip. Every traveller should stay in a single room."

python test_llm_client.py \
    "Please find a flight and a hotel for a trip to London from Zurich.
    The flight cost should be max. 200 GBP per traveller for the whole trip, the hotel cost is max. 300 GBP per day per person.
    The flight should be economy class.
    There will be three travelers on this trip. Every traveller should stay in a single room."

python test_llm_client.py \
    "Please plan my trip from Zurich at 12.03.2026 to Beijing, staying there for three days,
    then flight to Hong Kong, staying there for two days,
    then to Singapore with 2 days staying,
    then to New Delhi with 5 days staying, then back to Zurich.
    The total flight budget is 3000 CHF, the hotel budget is 300 CHF per day per person."