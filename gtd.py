"""Streamlit dashboard for exploring new GTD workbook time-series data."""

from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import platform
import re

st.set_page_config(
    page_title="",
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

if platform.system() == "Linux" or platform.system() == "Darwin":
    DATA_DIR = Path("/Volumes/staff-umbrella/DAPWELL DATA/13_production data/GTD")
elif platform.system() == "Windows":
    DATA_DIR = Path(r"U:\DAPWELL DATA\13_production data\GTD")
else:
    raise RuntimeError(f"Unsupported platform: {platform.system()}")

FILE_REGEX = re.compile(r"^GTD_(\d{8})_(\d{8})(?:\.xlsx|\.xlsm)?$", re.IGNORECASE)
MAX_PLOT_POINTS = 15000

TIME_COLUMN = "Timestamp"
MEASUREMENT_COLUMNS = [
    "Flow Rate",
    "ESP Frequency",
    "Injection Pressure",
    "Bypass Valve",
    "Degasser Level",
    "Temperature Difference",
    "Power",
    "Degasser Pressure",
    "Production Line Temperature",
    "Injection Line Temperature",
    "WW1 Primary Flow",
    "WW2 Primary Flow",
    "WW3 Primary Flow",
]

MEASUREMENT_UNITS = {
    "Flow Rate": "m3/h",
    "ESP Frequency": "Hz",
    "Injection Pressure": "bar?",
    "Bypass Valve": "%?",
    "Degasser Level": "%?",
    "Temperature Difference": "degC",
    "Power": "MW",
    "Degasser Pressure": "bar?",
    "Production Line Temperature": "degC",
    "Injection Line Temperature": "degC",
    "WW1 Primary Flow": "m3/h",
    "WW2 Primary Flow": "m3/h",
    "WW3 Primary Flow": "m3/h",
}


def metric_label(metric: str) -> str:
    """Return display label with unit when available."""
    unit = MEASUREMENT_UNITS.get(metric)
    return f"{metric} ({unit})" if unit else metric


@st.cache_data(show_spinner=False)
def discover_files(data_dir: str) -> tuple[str, ...]:
    """Return all Excel files in the new_gtd directory."""
    folder = Path(data_dir)
    if not folder.exists():
        return tuple()

    files = sorted(folder.glob("*.xlsx")) + sorted(folder.glob("*.xlsm"))
    return tuple(str(file_path) for file_path in sorted(files))


@st.cache_data(show_spinner=False)
def load_excels(paths: tuple[str, ...]) -> pd.DataFrame:
    """Load and concatenate all workbook files."""
    if not paths:
        return pd.DataFrame()

    frames = [pd.read_excel(path, engine="openpyxl") for path in paths]
    if len(frames) == 1:
        return frames[0]
    return pd.concat(frames, ignore_index=True)


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Trim and normalize header names for stable column matching."""
    out = df.copy()
    out.columns = [" ".join(str(col).strip().split()) for col in out.columns]
    return out


def detect_time_column(df: pd.DataFrame) -> Optional[str]:
    """Detect the timestamp column name."""
    candidates = ["Timestamp", "timestamp", "Time", "time", "Datetime", "datetime"]
    for col in candidates:
        if col in df.columns:
            return col
    return None


def build_plot_df(df: pd.DataFrame, x_col: str, metrics: list[str]) -> pd.DataFrame:
    """Prepare cleaned dataframe used for plotting."""
    out = df[[x_col, *metrics]].copy()
    out[x_col] = pd.to_datetime(out[x_col], errors="coerce")
    for metric in metrics:
        out[metric] = pd.to_numeric(out[metric], errors="coerce")
    out = out.dropna(subset=[x_col]).sort_values(x_col)
    return out


def downsample_plot_df(
    df: pd.DataFrame, max_points: int = MAX_PLOT_POINTS
) -> tuple[pd.DataFrame, int]:
    """Downsample long time-series to keep the UI responsive."""
    if len(df) <= max_points:
        return df, 1

    step = max(2, (len(df) + max_points - 1) // max_points)
    return df.iloc[::step].copy(), step


def full_timeseries_figure(
    plot_df: pd.DataFrame, x_col: str, metrics: list[str]
) -> go.Figure:
    """Build a grid of subplots: each metric vs timestamp."""
    cols = 2
    rows = (len(MEASUREMENT_COLUMNS) + cols - 1) // cols

    fig = make_subplots(
        rows=rows,
        cols=cols,
        shared_xaxes=True,
        vertical_spacing=0.08,
        horizontal_spacing=0.06,
        subplot_titles=[metric_label(metric) for metric in MEASUREMENT_COLUMNS],
    )

    for idx, metric in enumerate(MEASUREMENT_COLUMNS):
        row = idx // cols + 1
        col = idx % cols + 1

        if metric not in metrics:
            fig.add_annotation(
                text="Missing column",
                xref=f"x{idx + 1} domain",
                yref=f"y{idx + 1} domain",
                x=0.5,
                y=0.5,
                showarrow=False,
            )
            continue

        trace_df = plot_df[[x_col, metric]].dropna(subset=[x_col, metric])
        axis_label = metric_label(metric)
        if trace_df.empty:
            fig.add_annotation(
                text="No data",
                xref=f"x{idx + 1} domain",
                yref=f"y{idx + 1} domain",
                x=0.5,
                y=0.5,
                showarrow=False,
            )
            continue

        fig.add_trace(
            go.Scattergl(
                x=trace_df[x_col].to_list(),
                y=trace_df[metric].to_list(),
                mode="lines",
                name=axis_label,
                showlegend=False,
                line=dict(width=1.5),
                hovertemplate=(
                    "Time: %{x|%Y-%m-%d %H:%M:%S}<br>"
                    + f"{axis_label}: "
                    + "%{y:.3f}<extra></extra>"
                ),
            ),
            row=row,
            col=col,
        )

    layout_kwargs = {
        "hovermode": "x unified",
        "margin": dict(l=20, r=12, t=70, b=18),
        "height": 1400,
        "showlegend": False,
    }
    if "hoversubplots" in go.Layout()._valid_props:
        layout_kwargs["hoversubplots"] = "axis"

    fig.update_layout(**layout_kwargs)
    fig.update_annotations(font=dict(size=11))
    fig.update_xaxes(showspikes=True, spikemode="across", spikesnap="cursor")
    fig.update_xaxes(tickformat="%Y-%m-%d\n%H:%M", hoverformat="%Y-%m-%d %H:%M:%S")
    fig.update_xaxes(showticklabels=True)

    for r in range(1, rows + 1):
        for c in range(1, cols + 1):
            fig.update_xaxes(matches="x", row=r, col=c)

    fig.update_xaxes(rangeslider_visible=False)
    return fig


def main() -> None:
    """Run the Streamlit dashboard entry point."""
    if not DATA_DIR.exists():
        st.error(f"Data folder not found: {DATA_DIR}")
        return

    file_paths = discover_files(str(DATA_DIR))
    if not file_paths:
        st.warning("No xlsx/xlsm files were found in the new_gtd folder.")
        return

    with st.spinner("Loading new GTD data..."):
        raw_df = load_excels(file_paths)

    if raw_df.empty:
        st.warning("No rows found after reading workbook files.")
        return

    raw_df = normalize_columns(raw_df)

    time_col = detect_time_column(raw_df)
    if not time_col:
        st.error("No timestamp column was detected. Expected column: Timestamp")
        st.dataframe(raw_df.head(50), use_container_width=True)
        return

    metrics = [col for col in MEASUREMENT_COLUMNS if col in raw_df.columns]
    missing_metrics = [col for col in MEASUREMENT_COLUMNS if col not in raw_df.columns]

    if not metrics:
        st.error("None of the expected measurement columns were found.")
        st.dataframe(raw_df.head(50), use_container_width=True)
        return

    parsed_df = raw_df.copy()
    parsed_df[time_col] = pd.to_datetime(parsed_df[time_col], errors="coerce")
    parsed_df = parsed_df.dropna(subset=[time_col])

    if parsed_df.empty:
        st.warning("No valid timestamp rows found after parsing data.")
        return

    available_days = sorted(parsed_df[time_col].dt.date.dropna().unique().tolist())
    if not available_days:
        st.warning("No valid dates were detected in the timestamp column.")
        return

    applied_plot_config = st.session_state.get("plot_config")
    if applied_plot_config and (
        applied_plot_config.get("start_day") not in available_days
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
            "start_day": start_day,
            "end_day": end_day,
        }
        applied_plot_config = st.session_state["plot_config"]

    if not applied_plot_config:
        st.info("Select start/end dates and click Plot to load data.")
        return

    selected_start_day = applied_plot_config["start_day"]
    selected_end_day = applied_plot_config["end_day"]
    range_start_dt = datetime.combine(selected_start_day, time.min)
    range_end_exclusive = datetime.combine(
        selected_end_day + timedelta(days=1), time.min
    )

    selected_df = parsed_df[
        (parsed_df[time_col] >= range_start_dt)
        & (parsed_df[time_col] < range_end_exclusive)
    ]
    if selected_df.empty:
        st.warning("No rows found for the selected date range.")
        return

    plot_df = build_plot_df(selected_df, time_col, metrics)
    if plot_df.empty:
        st.warning("No plottable rows found in the selected date range.")
        return

    sampled_df, step = downsample_plot_df(plot_df)

    # st.title("New GTD Time-Series Dashboard")
    # st.caption(f"Loaded {len(file_paths)} file(s) from {DATA_DIR.name}")

    if missing_metrics:
        st.info("Missing columns in source files: " + ", ".join(missing_metrics))

    if step > 1:
        st.caption(
            f"Displaying every {step}th point for performance "
            f"({len(sampled_df):,} of {len(plot_df):,} rows)."
        )

    fig = full_timeseries_figure(sampled_df, time_col, metrics)
    st.plotly_chart(fig, use_container_width=True)


if __name__ == "__main__":
    main()
