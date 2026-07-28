"""app.py — COVID-19 platform interactive dashboard.

Talks to the FastAPI backend (api/main.py) over HTTP rather than querying
Snowflake or MongoDB directly, so the dashboard has no database
credentials of its own — it only needs to know the API's URL.

Run (with the API already running on http://127.0.0.1:8000):
    python dashboard/app.py
Then open http://127.0.0.1:8050 in a browser.
"""

from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import requests
from dash import Dash, Input, Output, State, dcc, html

API_BASE_URL = "http://127.0.0.1:8000"

# The dataset's actual date range (see task2_data_exploration.sql). Date
# presets below are relative to this, not to today's real-world date,
# since the data itself stops in March 2023.
DATASET_START = "2020-01-22"
DATASET_END = "2023-03-09"

app = Dash(__name__)
app.title = "COVID-19 Platform Dashboard"


def fetch_countries() -> list[dict]:
    try:
        response = requests.get(f"{API_BASE_URL}/countries", timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return []


def fetch_cases(country: str, case_type: str, start_date: str | None, end_date: str | None) -> pd.DataFrame:
    params = {"country": country, "case_type": case_type}
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    try:
        response = requests.get(f"{API_BASE_URL}/cases", params=params, timeout=15)
        response.raise_for_status()
        return pd.DataFrame(response.json())
    except requests.RequestException:
        return pd.DataFrame(columns=["DATE", "CASES", "NEW_CASES"])


def fetch_rolling_average(country: str, start_date: str | None, end_date: str | None) -> pd.DataFrame:
    params = {"country": country, "case_type": "Confirmed"}
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    try:
        response = requests.get(f"{API_BASE_URL}/cases/rolling-average", params=params, timeout=15)
        response.raise_for_status()
        return pd.DataFrame(response.json())
    except requests.RequestException:
        return pd.DataFrame(columns=["DATE", "CASES", "NEW_CASES", "ROLLING_AVG_NEW_CASES"])


def fetch_vaccinations(country: str, start_date: str | None, end_date: str | None) -> pd.DataFrame:
    params = {"country": country}
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    try:
        response = requests.get(f"{API_BASE_URL}/vaccinations", params=params, timeout=15)
        response.raise_for_status()
        return pd.DataFrame(response.json())
    except requests.RequestException:
        return pd.DataFrame(columns=["DATE", "PEOPLE_FULLY_VACCINATED_PER_HUNDRED"])


def fetch_annotations(country: str) -> list[dict]:
    try:
        response = requests.get(f"{API_BASE_URL}/annotations", params={"country": country}, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return []


def fetch_forecast(country: str, horizon_days: int = 14) -> pd.DataFrame:
    try:
        response = requests.get(
            f"{API_BASE_URL}/cases/forecast",
            params={"country": country, "horizon_days": horizon_days},
            timeout=20,
        )
        response.raise_for_status()
        return pd.DataFrame(response.json())
    except requests.RequestException:
        return pd.DataFrame(columns=["DATE", "FORECAST_NEW_CASES"])


def fetch_clusters(n_clusters: int = 4) -> pd.DataFrame:
    try:
        response = requests.get(f"{API_BASE_URL}/clusters", params={"n_clusters": n_clusters}, timeout=30)
        response.raise_for_status()
        return pd.DataFrame(response.json())
    except requests.RequestException:
        return pd.DataFrame(
            columns=["COUNTRY_REGION", "ISO3166_1", "CASES_PER_100K", "PEAK_NEW_CASES_PER_100K", "CFR_PERCENT", "CLUSTER"]
        )


COUNTRIES = fetch_countries()
COUNTRY_OPTIONS = [
    {"label": row["COUNTRY_REGION"], "value": row["COUNTRY_REGION"]} for row in COUNTRIES
]
DEFAULT_COUNTRY = "United States" if any(o["value"] == "United States" for o in COUNTRY_OPTIONS) else (
    COUNTRY_OPTIONS[0]["value"] if COUNTRY_OPTIONS else None
)

app.layout = html.Div(
    style={"fontFamily": "Arial, sans-serif", "margin": "0 40px"},
    children=[
        html.H1("COVID-19 Platform Dashboard"),
        html.P("Infection rates, mortality rates, and vaccination coverage by country."),

        html.Div(
            style={"display": "flex", "gap": "20px", "marginBottom": "20px"},
            children=[
                html.Div(
                    children=[
                        html.Label("Country"),
                        dcc.Dropdown(
                            id="country-dropdown",
                            options=COUNTRY_OPTIONS,
                            value=DEFAULT_COUNTRY,
                            clearable=False,
                        ),
                    ],
                    style={"width": "300px"},
                ),
                html.Div(
                    children=[
                        html.Label("Date range"),
                        dcc.RadioItems(
                            id="date-preset",
                            options=[
                                {"label": "Last 30 days", "value": "30d"},
                                {"label": "Last 90 days", "value": "90d"},
                                {"label": "Last year", "value": "1y"},
                                {"label": "All time", "value": "all"},
                            ],
                            value="all",
                            inline=True,
                        ),
                    ]
                ),
                html.Div(
                    children=[
                        html.Label("Forecast"),
                        dcc.Checklist(
                            id="show-forecast",
                            options=[{"label": "Show 14-day forecast", "value": "show"}],
                            value=["show"],
                        ),
                    ]
                ),
            ],
        ),
        dcc.Store(id="date-range-store"),

        dcc.Graph(id="cases-graph"),
        dcc.Graph(id="mortality-graph"),
        dcc.Graph(id="vaccination-graph"),

        html.Hr(),
        html.H2("Country Clustering (Bonus)"),
        html.P(
            "Groups countries by how similar their COVID-19 outcomes are — total cases per 100k "
            "population, peak daily new cases per 100k population, and case fatality rate — using "
            "KMeans clustering computed on the fly."
        ),
        html.Button("Run clustering", id="run-clustering-button", n_clicks=0),
        dcc.Graph(id="cluster-graph"),

        html.Hr(),
        html.H2("Annotations"),
        html.P("Notes tied to this country, stored in MongoDB via the API."),
        html.Div(id="annotations-list"),

        html.H3("Add an annotation"),
        html.Div(
            style={"display": "flex", "flexDirection": "column", "gap": "8px", "maxWidth": "500px"},
            children=[
                dcc.Input(id="annotation-author", type="text", placeholder="Your name"),
                dcc.Input(id="annotation-date", type="text", placeholder="Date (YYYY-MM-DD)"),
                dcc.Textarea(id="annotation-text", placeholder="Comment"),
                dcc.Input(id="annotation-tags", type="text", placeholder="Tags, comma-separated"),
                html.Button("Add annotation", id="add-annotation-button", n_clicks=0),
                html.Div(id="annotation-status"),
            ],
        ),
    ],
)


@app.callback(
    Output("date-range-store", "data"),
    Input("date-preset", "value"),
)
def update_date_range(preset):
    end = date.fromisoformat(DATASET_END)
    if preset == "30d":
        start = end - timedelta(days=30)
    elif preset == "90d":
        start = end - timedelta(days=90)
    elif preset == "1y":
        start = end - timedelta(days=365)
    else:
        start = date.fromisoformat(DATASET_START)
    return {"start_date": start.isoformat(), "end_date": end.isoformat()}


@app.callback(
    Output("cases-graph", "figure"),
    Output("mortality-graph", "figure"),
    Output("vaccination-graph", "figure"),
    Input("country-dropdown", "value"),
    Input("date-range-store", "data"),
    Input("show-forecast", "value"),
)
def update_graphs(country, date_range, show_forecast):
    if not country:
        return go.Figure(), go.Figure(), go.Figure()

    start_date = date_range.get("start_date") if date_range else None
    end_date = date_range.get("end_date") if date_range else None

    # --- Infection rate: daily new cases + 7-day rolling average ---
    rolling = fetch_rolling_average(country, start_date, end_date)
    cases_fig = go.Figure()
    if not rolling.empty:
        cases_fig.add_trace(go.Bar(x=rolling["DATE"], y=rolling["NEW_CASES"], name="New cases", opacity=0.4))
        cases_fig.add_trace(
            go.Scatter(x=rolling["DATE"], y=rolling["ROLLING_AVG_NEW_CASES"], name="7-day rolling average")
        )

    # --- Task 6: forecast, computed on the fly by the API on request ---
    if show_forecast and "show" in show_forecast:
        forecast = fetch_forecast(country)
        if not forecast.empty:
            cases_fig.add_trace(
                go.Scatter(
                    x=forecast["DATE"],
                    y=forecast["FORECAST_NEW_CASES"],
                    name="14-day forecast",
                    line=dict(dash="dash"),
                )
            )

    cases_fig.update_layout(title=f"Daily new confirmed cases — {country}", xaxis_title="Date", yaxis_title="Cases")

    # --- Mortality rate: case fatality rate (deaths / confirmed cases) ---
    confirmed = fetch_cases(country, "Confirmed", start_date, end_date)
    deaths = fetch_cases(country, "Deaths", start_date, end_date)
    mortality_fig = go.Figure()
    if not confirmed.empty and not deaths.empty:
        merged = confirmed.merge(deaths, on="DATE", suffixes=("_CONFIRMED", "_DEATHS"))
        merged = merged[merged["CASES_CONFIRMED"] > 0]
        merged["CFR_PERCENT"] = merged["CASES_DEATHS"] / merged["CASES_CONFIRMED"] * 100
        mortality_fig.add_trace(go.Scatter(x=merged["DATE"], y=merged["CFR_PERCENT"], name="Case fatality rate (%)"))
    mortality_fig.update_layout(
        title=f"Case fatality rate over time — {country}", xaxis_title="Date", yaxis_title="CFR (%)"
    )

    # --- Vaccination coverage ---
    vax = fetch_vaccinations(country, start_date, end_date)
    vax_fig = go.Figure()
    if not vax.empty:
        vax_fig.add_trace(go.Scatter(x=vax["DATE"], y=vax["PEOPLE_FULLY_VACCINATED_PER_HUNDRED"], name="Fully vaccinated per 100"))
    vax_fig.update_layout(
        title=f"Vaccination coverage — {country}", xaxis_title="Date", yaxis_title="People fully vaccinated per 100"
    )

    return cases_fig, mortality_fig, vax_fig


@app.callback(
    Output("annotations-list", "children"),
    Input("country-dropdown", "value"),
    Input("annotation-status", "children"),
)
def update_annotations_list(country, _status):
    if not country:
        return html.P("Select a country to see annotations.")

    annotations = fetch_annotations(country)
    if not annotations:
        return html.P("No annotations yet for this country.")

    return html.Ul(
        [
            html.Li(
                f"[{(a.get('date') or '')[:10]}] {a.get('comment_text', '')} "
                f"— {a.get('author', 'unknown')} (tags: {', '.join(a.get('tags', []))})"
            )
            for a in annotations
        ]
    )


@app.callback(
    Output("annotation-status", "children"),
    Input("add-annotation-button", "n_clicks"),
    State("country-dropdown", "value"),
    State("annotation-author", "value"),
    State("annotation-date", "value"),
    State("annotation-text", "value"),
    State("annotation-tags", "value"),
    prevent_initial_call=True,
)
def add_annotation(n_clicks, country, author, date_value, comment_text, tags_value):
    if not all([country, author, date_value, comment_text]):
        return "Please fill in country, author, date, and a comment before submitting."

    country_row = next((c for c in COUNTRIES if c["COUNTRY_REGION"] == country), None)
    iso_code = country_row["ISO3166_1"] if country_row else ""
    tags = [t.strip() for t in tags_value.split(",")] if tags_value else []

    payload = {
        "country_region": country,
        "iso3166_1": iso_code,
        "date": date_value,
        "case_type": "Confirmed",
        "author": author,
        "comment_text": comment_text,
        "tags": tags,
    }

    try:
        response = requests.post(f"{API_BASE_URL}/annotations", json=payload, timeout=10)
        response.raise_for_status()
        return "Annotation added."
    except requests.RequestException as exc:
        return f"Failed to add annotation: {exc}"


@app.callback(
    Output("cluster-graph", "figure"),
    Input("run-clustering-button", "n_clicks"),
    prevent_initial_call=True,
)
def update_cluster_graph(n_clicks):
    clusters = fetch_clusters()
    fig = go.Figure()
    if clusters.empty:
        fig.update_layout(title="Clustering failed — check that the API is running.")
        return fig

    for cluster_id in sorted(clusters["CLUSTER"].unique()):
        subset = clusters[clusters["CLUSTER"] == cluster_id]
        fig.add_trace(
            go.Scatter(
                x=subset["CASES_PER_100K"],
                y=subset["CFR_PERCENT"],
                mode="markers",
                name=f"Cluster {cluster_id}",
                text=subset["COUNTRY_REGION"],
                marker=dict(size=10),
            )
        )
    fig.update_layout(
        title="Countries clustered by spread pattern and outcomes",
        xaxis_title="Total confirmed cases per 100k population",
        yaxis_title="Case fatality rate (%)",
    )
    return fig


if __name__ == "__main__":
    app.run(debug=True, port=8050)
