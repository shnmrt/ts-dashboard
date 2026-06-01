import json
import re
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Optional

import duckdb
import plotly.graph_objects as go
import polars as pl
import streamlit as st
from plotly.subplots import make_subplots

import platform

if platform.system() == "Linux" or platform.system() == "Darwin":
    DEFAULT_ROOT = "/Volumes/staff-umbrella/DAPWELL DATA/13_production data/ESP"
elif platform.system() == "Windows":
    DEFAULT_ROOT = "U:\DAPWELL DATA\13_production data\ESP"
else:
    raise RuntimeError(f"Unsupported platform: {platform.system()}")


st.set_page_config(
    page_title="ESP Timeseries Dashboard",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
	<style>
	div.block-container {
		padding-top: 0.45rem;
		padding-bottom: 0.45rem;
	}
	</style>
	""",
    unsafe_allow_html=True,
)


FILE_REGEX = re.compile(
    r"^ESP_(\d{8}T\d{6})_(\d{8}T\d{6})\.parquet$",
    re.IGNORECASE,
)

DISCOVERY_SCHEMA = {
    "file": pl.String,
    "path": pl.String,
    "start": pl.Datetime,
    "end": pl.Datetime,
    "day": pl.Date,
}

MEASUREMENT_COLUMNS = [
    "Frequency",
    "Motor Current",
    "Motor Voltage",
    "Intake Pressure",
    "Intake Fluid Temp",
    "Motor Winding Temp",
    "Current Leakage",
    "X Axis Vibration",
    "Y Axis Vibration",
    "Well Head Press.",
    "Discharge Pressure",
]

TIME_CANDIDATES = ["Time"]

MEASUREMENT_UNITS = {
    "Frequency": "Hz",
    "Motor Current": "A",
    "Motor Voltage": "VAC",
    "Intake Pressure": "bar",
    "Intake Fluid Temp": "C",
    "Motor Winding Temp": "C",
    "Current Leakage": "mA",
    "X Axis Vibration": "g",
    "Y Axis Vibration": "g",
    "Well Head Press.": "bar",
    "Discharge Pressure": "bar",
}

TEMPERATURE_METRICS = {"Intake Fluid Temp", "Motor Winding Temp"}
TEMPERATURE_UPPER_THRESHOLD_C = 101.0
MAX_PLOT_POINTS = 15000


def show_unreachable_root_popup(root: str) -> None:
    """Show a one-time browser popup when the ESP root path is unreachable."""
    if st.session_state.get("default_root_unreachable_alerted", False):
        return

    message = (
        "ESP data folder is unreachable. \n\n"
        f"Path: {root}\n\n"
        "Please mount or verify the folder path, then rerun the app."
    )
    st.components.v1.html(
        f"<script>window.alert({json.dumps(message)});</script>",
        height=0,
    )
    st.session_state["default_root_unreachable_alerted"] = True


def metric_label(metric_name: str) -> str:
    """Return a display label for a metric, including unit when known."""
    unit = MEASUREMENT_UNITS.get(metric_name)
    return f"{metric_name} ({unit})" if unit else metric_name


def parse_file_window(file_name: str) -> tuple[Optional[datetime], Optional[datetime]]:
    """Parse start/end datetimes encoded in an ESP parquet filename."""
    match = FILE_REGEX.match(file_name)
    if not match:
        return None, None
    start_dt = datetime.strptime(match.group(1), "%Y%m%dT%H%M%S")
    end_dt = datetime.strptime(match.group(2), "%Y%m%dT%H%M%S")
    return start_dt, end_dt


def empty_discovery_df() -> pl.DataFrame:
    """Build an empty discovery dataframe with the expected schema."""
    return pl.DataFrame(
        {"file": [], "path": [], "start": [], "end": [], "day": []},
        schema=DISCOVERY_SCHEMA,
    )


def discover_files(root: str) -> pl.DataFrame:
    """Discover ESP parquet files and extract date metadata from filenames."""
    root_path = Path(root)
    if not root_path.exists():
        return empty_discovery_df()

    rows: list[dict[str, object]] = []
    for file_path in sorted(root_path.glob("ESP_*.parquet")):
        start_dt, end_dt = parse_file_window(file_path.name)
        rows.append(
            {
                "file": file_path.name,
                "path": str(file_path),
                "start": start_dt,
                "end": end_dt,
                "day": start_dt.date() if start_dt else None,
            }
        )

    if not rows:
        return empty_discovery_df()
    return pl.DataFrame(rows)


def detect_time_column(df: pl.DataFrame) -> Optional[str]:
    """Detect the most likely time axis column in an input dataframe."""
    for col in TIME_CANDIDATES:
        if col in df.columns:
            return col

    for col, dtype in zip(df.columns, df.dtypes, strict=True):
        if str(dtype).startswith(("Datetime", "Date", "Time")):
            return col

    return None


def normalize_time_column(df: pl.DataFrame, time_col: str) -> pl.DataFrame:
    """Coerce string-like time columns to datetimes when possible."""
    dtype = df.schema.get(time_col)
    if dtype in {pl.String, pl.Utf8}:
        return df.with_columns(pl.col(time_col).str.to_datetime(strict=False))
    return df


def filter_time_window(
    df: pl.DataFrame,
    time_col: str,
    start_dt: datetime,
    end_dt_exclusive: datetime,
) -> pl.DataFrame:
    """Filter rows to the requested half-open time window [start, end)."""
    dtype = df.schema.get(time_col)
    if dtype == pl.Date:
        return df.filter(
            (pl.col(time_col) >= pl.lit(start_dt.date()))
            & (pl.col(time_col) < pl.lit(end_dt_exclusive.date()))
        )
    if str(dtype).startswith("Time"):
        return df
    return df.filter(
        (pl.col(time_col) >= pl.lit(start_dt))
        & (pl.col(time_col) < pl.lit(end_dt_exclusive))
    )


@st.cache_data(show_spinner=False)
def load_parquet(path: str) -> pl.DataFrame:
    """Load one parquet file through DuckDB and return a Polars dataframe."""
    # Use DuckDB as the parquet scan engine, then convert to Polars for downstream transforms.
    return duckdb.read_parquet(path).pl()


@st.cache_data(show_spinner=False)
def load_parquets(paths: tuple[str, ...]) -> pl.DataFrame:
    """Load one or more parquet files with schema-tolerant union behavior."""
    if len(paths) == 1:
        return load_parquet(paths[0])

    # union_by_name keeps schema evolution tolerant across files.
    return duckdb.read_parquet(list(paths), union_by_name=True).pl()


def build_plot_df(df: pl.DataFrame, x_col: str, metrics: list[str]) -> pl.DataFrame:
    """Prepare plotting dataframe with numeric metrics and temp threshold masking."""
    exprs: list[pl.Expr] = [pl.col(x_col)]
    for metric in metrics:
        expr = pl.col(metric).cast(pl.Float64).fill_nan(None)
        if metric in TEMPERATURE_METRICS:
            expr = (
                pl.when(expr <= TEMPERATURE_UPPER_THRESHOLD_C)
                .then(expr)
                .otherwise(None)
            )
        exprs.append(expr.alias(metric))

    out = df.select(exprs)
    if x_col in out.columns:
        out = out.sort(x_col)
    return out


def downsample_plot_df(
    df: pl.DataFrame, max_points: int = MAX_PLOT_POINTS
) -> tuple[pl.DataFrame, int]:
    """Downsample rows to cap chart point count, returning step size used."""
    if df.height <= max_points:
        return df, 1

    step = max(2, (df.height + max_points - 1) // max_points)
    sampled_df = (
        df.with_row_index("_row_idx")
        .filter(pl.col("_row_idx") % step == 0)
        .drop("_row_idx")
    )
    return sampled_df, step


def panel_layout() -> list[str | tuple[str, str]]:
    """Define fixed panel order for the 5x2 timeseries subplot grid."""
    return [
        "Frequency",
        "Motor Current",
        "Motor Voltage",
        "Intake Pressure",
        "Intake Fluid Temp",
        "Motor Winding Temp",
        "Current Leakage",
        ("X Axis Vibration", "Y Axis Vibration"),
        "Well Head Press.",
        "Discharge Pressure",
    ]


def full_timeseries_figure(
    plot_df: pl.DataFrame, x_col: str, metrics: list[str]
) -> go.Figure:
    """Build the multi-panel full-range figure for all configured ESP metrics."""
    layout = panel_layout()
    subplot_titles: list[str] = []
    for item in layout:
        if isinstance(item, tuple):
            subplot_titles.append(" + ".join(metric_label(m) for m in item))
        else:
            subplot_titles.append(metric_label(item))

    fig = make_subplots(
        rows=5,
        cols=2,
        shared_xaxes=True,
        vertical_spacing=0.07,
        horizontal_spacing=0.1,
        subplot_titles=subplot_titles,
    )

    for idx, item in enumerate(layout):
        row = idx // 2 + 1
        col = idx % 2 + 1
        metrics_in_panel = list(item) if isinstance(item, tuple) else [item]

        panel_has_data = False
        for metric in metrics_in_panel:
            if metric not in metrics:
                continue
            trace_df = plot_df.select([pl.col(x_col), pl.col(metric)]).drop_nulls(
                subset=[x_col, metric]
            )
            if trace_df.height == 0:
                continue
            panel_has_data = True
            fig.add_trace(
                go.Scattergl(
                    x=trace_df.get_column(x_col).to_list(),
                    y=trace_df.get_column(metric).to_list(),
                    mode="lines",
                    name=metric_label(metric),
                    legendgroup=metric,
                    showlegend=False,
                ),
                row=row,
                col=col,
            )

        if not panel_has_data:
            fig.add_annotation(
                text="No data",
                xref=f"x{idx + 1} domain",
                yref=f"y{idx + 1} domain",
                x=0.5,
                y=0.5,
                showarrow=False,
            )

    fig.update_layout(
        hovermode="x unified",
        margin=dict(l=28, r=20, t=46, b=18),
        height=900,
        showlegend=False,
    )
    fig.update_xaxes(showspikes=True, spikemode="across", spikesnap="cursor")
    return fig


# def weekly_figure(
#     plot_df: pl.DataFrame, time_col: str, metrics: list[str]
# ) -> go.Figure:
#     week_col = "week_start"
#     weekly_df = plot_df.with_columns(pl.col(time_col).dt.truncate("1w").alias(week_col))
#     weeks = weekly_df.get_column(week_col).drop_nulls().unique().sort().to_list()

#     if not weeks:
#         fig = go.Figure()
#         fig.add_annotation(
#             text="No weekly data in selected date range", x=0.5, y=0.5, showarrow=False
#         )
#         fig.update_layout(height=300, margin=dict(l=28, r=20, t=50, b=25))
#         return fig

#     layout = panel_layout()
#     subplot_titles: list[str] = []
#     for item in layout:
#         if isinstance(item, tuple):
#             subplot_titles.append(" + ".join(metric_label(m) for m in item))
#         else:
#             subplot_titles.append(metric_label(item))

#     fig = make_subplots(
#         rows=5,
#         cols=2,
#         shared_xaxes=True,
#         vertical_spacing=0.07,
#         horizontal_spacing=0.1,
#         subplot_titles=subplot_titles,
#     )

#     week_labels = [f"{w:%Y-%m-%d}" for w in weeks]
#     for idx, item in enumerate(layout):
#         row = idx // 2 + 1
#         col = idx % 2 + 1
#         metrics_in_panel = list(item) if isinstance(item, tuple) else [item]

#         panel_has_data = False
#         for metric in metrics_in_panel:
#             if metric not in metrics:
#                 continue
#             for week_idx, week_start in enumerate(weeks):
#                 week_slice = weekly_df.filter(pl.col(week_col) == pl.lit(week_start))
#                 trace_df = week_slice.select(
#                     [pl.col(time_col), pl.col(metric)]
#                 ).drop_nulls(subset=[time_col, metric])
#                 if trace_df.height == 0:
#                     continue
#                 panel_has_data = True
#                 fig.add_trace(
#                     go.Scatter(
#                         x=trace_df.get_column(time_col).to_list(),
#                         y=trace_df.get_column(metric).to_list(),
#                         mode="lines",
#                         name=f"{metric_label(metric)} | Week {week_labels[week_idx]}",
#                         legendgroup=f"{metric}-{week_labels[week_idx]}",
#                         showlegend=False,
#                     ),
#                     row=row,
#                     col=col,
#                 )

#         if not panel_has_data:
#             fig.add_annotation(
#                 text="No data",
#                 xref=f"x{idx + 1} domain",
#                 yref=f"y{idx + 1} domain",
#                 x=0.5,
#                 y=0.5,
#                 showarrow=False,
#             )

#     fig.update_layout(
#         hovermode="x unified",
#         margin=dict(l=28, r=20, t=70, b=25),
#         height=800,
#         showlegend=False,
#     )
#     fig.update_xaxes(tickformat="%Y-%m-%d\n%H:%M", hoverformat="%Y-%m-%d %H:%M:%S")
#     return fig


def main() -> None:
    """Run the Streamlit ESP dashboard UI and render the selected date range."""
    root = DEFAULT_ROOT
    if not Path(root).exists():
        show_unreachable_root_popup(root)
        st.error(f"Default ESP root folder is unreachable: {root}")
        st.info("Mount the source location and refresh the app.")
        return

    st.session_state.pop("default_root_unreachable_alerted", None)

    files_df = discover_files(root)
    if files_df.height == 0:
        st.warning(
            "No ESP parquet files found. Check the folder path and file naming pattern: "
            "ESP_YYYYMMDDTHHMMSS_YYYYMMDDTHHMMSS.parquet"
        )
        return

    files_df = files_df.sort("start", descending=False, nulls_last=True)

    available_days = files_df.get_column("day").drop_nulls().unique().sort().to_list()
    if not available_days:
        st.warning("No valid date metadata was parsed from ESP file names.")
        return

    applied_plot_config = st.session_state.get("plot_config")
    if applied_plot_config and (
        applied_plot_config.get("root") != root
        or applied_plot_config.get("start_day") not in available_days
        or applied_plot_config.get("end_day") not in available_days
    ):
        applied_plot_config = None
        st.session_state.pop("plot_config", None)

    default_start_day = (
        applied_plot_config["start_day"] if applied_plot_config else available_days[-1]
    )
    default_end_day = (
        applied_plot_config["end_day"] if applied_plot_config else available_days[-1]
    )

    st.sidebar.markdown("### Date Selection")
    start_day = st.sidebar.selectbox(
        "Start date",
        options=available_days,
        index=available_days.index(default_start_day),
        format_func=lambda d: d.strftime("%Y-%m-%d"),
    )
    end_day = st.sidebar.selectbox(
        "End date",
        options=available_days,
        index=available_days.index(default_end_day),
        format_func=lambda d: d.strftime("%Y-%m-%d"),
    )
    plot_clicked = st.sidebar.button("Plot", type="primary", use_container_width=True)

    if start_day > end_day:
        st.sidebar.error("Start date must be before or equal to end date.")
        return

    if plot_clicked:
        st.session_state["plot_config"] = {
            "root": root,
            "start_day": start_day,
            "end_day": end_day,
        }
        applied_plot_config = st.session_state["plot_config"]

    if not applied_plot_config:
        st.info("Select start/end dates and click Plot to load data.")
        return

    selected_start_day = applied_plot_config["start_day"]
    selected_end_day = applied_plot_config["end_day"]

    all_paths = tuple(files_df.get_column("path").to_list())
    with st.spinner("Loading ESP data..."):
        raw_df = load_parquets(all_paths)

    time_col = detect_time_column(raw_df)
    if time_col:
        raw_df = normalize_time_column(raw_df, time_col)

    available_metrics = [col for col in MEASUREMENT_COLUMNS if col in raw_df.columns]
    if not available_metrics:
        st.error("None of the expected ESP measurement columns were found.")
        st.dataframe(raw_df.head(50).to_pandas(), use_container_width=True)
        return

    if not time_col:
        st.error("No timestamp column was detected, so plotting cannot be built.")
        return

    range_start_dt = datetime.combine(selected_start_day, time.min)
    range_end_exclusive = datetime.combine(
        selected_end_day + timedelta(days=1), time.min
    )
    if (
        selected_start_day == available_days[0]
        and selected_end_day == available_days[-1]
    ):
        selected_range_df = raw_df
    else:
        selected_range_df = filter_time_window(
            raw_df, time_col, range_start_dt, range_end_exclusive
        )
    single_plot_df = build_plot_df(selected_range_df, time_col, available_metrics)
    single_plot_df, sample_step = downsample_plot_df(single_plot_df)

    missing_metrics = [m for m in MEASUREMENT_COLUMNS if m not in raw_df.columns]
    if missing_metrics:
        st.caption("Missing ESP columns: " + ", ".join(missing_metrics))

    if sample_step > 1:
        st.caption(
            f"Large range detected: plotting every {sample_step}th point for faster performance."
        )

    st.plotly_chart(
        full_timeseries_figure(single_plot_df, time_col, available_metrics),
        use_container_width=True,
    )


if __name__ == "__main__":
    main()
