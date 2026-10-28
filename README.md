# Gamma map

A Streamlit dashboard that estimates dealer gamma exposure for QQQ (shown in NQ futures points) and SPX (shown in ES points), using CBOE's free delayed option chains.

Run locally: `pip install -r requirements.txt` then `streamlit run app.py`.

The dealer sign is an assumption (dealers long calls, short puts). Data is ~15 minutes delayed. Not trading advice.
