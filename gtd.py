"""Streamlit dashboard for exploring GTD workbook time-series data."""

import re
import json
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from plotly.subplots import make_subplots

import platform

st.set_page_config(
    page_title="GTD Timeseries Dashboard",
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
    DEFAULT_ROOT = "/Volumes/staff-umbrella/DAPWELL DATA/13_production data/GTD"
elif platform.system() == "Windows":
    DEFAULT_ROOT = "U:\DAPWELL DATA\13_production data\GTD"
else:
    raise RuntimeError(f"Unsupported platform: {platform.system()}")


FILE_REGEX = re.compile(r"^GTD_(\d{8})_(\d{8})(?:\.xlsx|\.xlsm)?$", re.IGNORECASE)
MAX_PLOT_POINTS = 15000

MEASUREMENT_COLUMNS = [
    "Total flow rate (m3/s)",
    "ESP Frequency (Hz)",
    "Temperature Difference (C)",
    "Delivered Power (MW)",
    "Primary Electricity (kW)",
    "Return Temperature (C)",
    "Supply Temperature (C)",
    "Gas Flow (m3/s?)",
]

TIME_CANDIDATES = [
    "Timestamp",
    "timestamp",
    "Time",
    "time",
    "Datetime",
    "datetime",
    "DateTime",
    "date_time",
]

COLUMN_ALIASES = {
    "Temperature Difference ©": "Temperature Difference (C)",
    "Return Temperature ©": "Return Temperature (C)",
    "Supply Temperature ©": "Supply Temperature (C)",
    "Temperature Difference C": "Temperature Difference (C)",
    "Return Temperature C": "Return Temperature (C)",
    "Supply Temperature C": "Supply Temperature (C)",
}


def parse_file_window(file_name: str) -> tuple[Optional[datetime], Optional[datetime]]:
    """Extract the start and end dates encoded in a GTD filename.

    Returns ``(None, None)`` when the filename does not match the expected
    ``GTD_YYYYMMDD_YYYYMMDD`` pattern.
    """
    match = FILE_REGEX.match(file_name)
    if not match:
        return None, None

    start_dt = datetime.strptime(match.group(1), "%Y%m%d")
    end_dt = datetime.strptime(match.group(2), "%Y%m%d")
    return start_dt, end_dt


def empty_discovery_df() -> pd.DataFrame:
    """Return an empty discovery table with the expected schema."""
    return pd.DataFrame({"file": [], "path": [], "start": [], "end": [], "day": []})


def discover_files(root: str) -> pd.DataFrame:
    """Find GTD workbook files under a root directory and index their dates.

    The discovery table is used to populate the date picker and to determine
    the available plotting range.
    """
    root_path = Path(root)
    if not root_path.exists():
        return empty_discovery_df()

    rows: list[dict[str, object]] = []
    file_paths = sorted(root_path.glob("GTD_*.xlsx")) + sorted(
        root_path.glob("GTD_*.xlsm")
    )
    for file_path in sorted(file_paths):
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
    return pd.DataFrame(rows)


def notify_unreachable_root(root: str) -> None:
    """Show a popup notification when the default data directory is unreachable."""
    message = (
        "GTD data folder is not reachable: "
        f"{root}. Check network mount/access and try again."
    )

    alerted_root = st.session_state.get("unreachable_root_alerted")
    if alerted_root == root:
        return

    st.session_state["unreachable_root_alerted"] = root

    if hasattr(st, "dialog"):

        @st.dialog("Data Folder Unreachable")
        def _show_dialog() -> None:
            st.error(message)
            st.caption(
                "The dashboard cannot load GTD files until this path is reachable."
            )
            st.button("OK", key="unreachable_root_ok")

        _show_dialog()
    else:
        # Fallback for older Streamlit versions without modal dialog support.
        components.html(
            f"<script>alert({json.dumps(message)});</script>",
            height=0,
            width=0,
        )

    st.error(message)


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Canonicalize workbook headers so downstream lookups stay stable.

    This normalizes common copyright and accent variants that appear in GTD
    workbook exports so downstream metric selection stays predictable.
    """
    out = df.copy()
    normalized_columns: list[str] = []
    for col in out.columns:
        clean_col = str(col).strip()
        clean_col = clean_col.replace("°", "C").replace("º", "C").replace("©", "C")
        clean_col = clean_col.replace("( C)", "(C)")
        clean_col = " ".join(clean_col.split())

        # Canonicalize common GTD temperature header variants to expected names.
        if clean_col.endswith("Temperature C"):
            clean_col = clean_col.replace("Temperature C", "Temperature (C)")
        if clean_col == "Temperature Difference C":
            clean_col = "Temperature Difference (C)"

        clean_col = COLUMN_ALIASES.get(clean_col, clean_col)
        normalized_columns.append(clean_col)

    out.columns = normalized_columns
    return out


def detect_time_column(df: pd.DataFrame) -> Optional[str]:
    """Return the most likely timestamp column if one exists."""
    for col in TIME_CANDIDATES:
        if col in df.columns:
            return col

    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            return col

    return None


def normalize_time_column(df: pd.DataFrame, time_col: str) -> pd.DataFrame:
    """Convert a timestamp column to pandas datetime values."""
    out = df.copy()
    out[time_col] = pd.to_datetime(out[time_col], errors="coerce")
    return out


def filter_time_window(
    df: pd.DataFrame,
    time_col: str,
    start_dt: datetime,
    end_dt_exclusive: datetime,
) -> pd.DataFrame:
    """Return rows whose timestamps fall inside the selected day range."""
    time_values = pd.to_datetime(df[time_col], errors="coerce")
    mask = (time_values >= start_dt) & (time_values < end_dt_exclusive)
    return df.loc[mask].copy()


@st.cache_data(show_spinner=False)
def load_excel(path: str) -> pd.DataFrame:
    """Load one GTD workbook and normalize its columns."""
    return normalize_columns(pd.read_excel(path, engine="openpyxl"))


@st.cache_data(show_spinner=False)
def load_excels(paths: tuple[str, ...]) -> pd.DataFrame:
    """Load multiple GTD workbooks and concatenate them into one table."""
    frames = [load_excel(path) for path in paths]
    if len(frames) == 1:
        return frames[0]
    return pd.concat(frames, ignore_index=True)


def build_plot_df(df: pd.DataFrame, x_col: str, metrics: list[str]) -> pd.DataFrame:
    """Prepare a filtered dataframe for Plotly time-series rendering."""
    out = df[[x_col, *metrics]].copy()
    out[x_col] = pd.to_datetime(out[x_col], errors="coerce")
    for metric in metrics:
        out[metric] = pd.to_numeric(out[metric], errors="coerce")
    out = out.dropna(subset=[x_col]).sort_values(x_col)
    return out


def downsample_plot_df(
    df: pd.DataFrame, max_points: int = MAX_PLOT_POINTS
) -> tuple[pd.DataFrame, int]:
    """Reduce point count for large plots while reporting the sampling step."""
    if len(df) <= max_points:
        return df, 1

    step = max(2, (len(df) + max_points - 1) // max_points)
    return df.iloc[::step].copy(), step


def full_timeseries_figure(
    plot_df: pd.DataFrame,
    x_col: str,
    metrics: list[str],
    range_start: Optional[datetime] = None,
    range_end: Optional[datetime] = None,
) -> go.Figure:
    """Build the 2-column by 4-row GTD time-series figure.

    The subplot layout mirrors the dashboard's measurement groups so each
    metric always renders in the same location.
    """
    fig = make_subplots(
        rows=4,
        cols=2,
        shared_xaxes=True,
        vertical_spacing=0.09,
        horizontal_spacing=0.06,
        subplot_titles=[metric for metric in MEASUREMENT_COLUMNS],
    )

    for idx, metric in enumerate(MEASUREMENT_COLUMNS):
        row = idx // 2 + 1
        col = idx % 2 + 1

        if metric not in metrics:
            fig.add_annotation(
                text="No data",
                xref=f"x{idx + 1} domain",
                yref=f"y{idx + 1} domain",
                x=0.5,
                y=0.5,
                showarrow=False,
            )
            continue

        trace_df = plot_df[[x_col, metric]].dropna(subset=[x_col, metric])
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
                name=metric,
                showlegend=False,
                line=dict(width=1.5),
            ),
            row=row,
            col=col,
        )

    layout_kwargs = {
        "hovermode": "x unified",
        "margin": dict(l=20, r=12, t=70, b=18),
        "height": 900,
        "showlegend": False,
    }
    if "hoversubplots" in go.Layout()._valid_props:
        layout_kwargs["hoversubplots"] = "axis"
    fig.update_layout(**layout_kwargs)
    fig.update_annotations(font=dict(size=11))
    fig.update_xaxes(showspikes=True, spikemode="across", spikesnap="cursor")
    fig.update_xaxes(tickformat="%Y-%m-%d\n%H:%M", hoverformat="%Y-%m-%d %H:%M:%S")
    fig.update_xaxes(showticklabels=True)
    for i in [1, 2, 3, 4]:
        for j in [1, 2]:
            fig.update_xaxes(matches="x", row=i, col=j)

    fig.update_xaxes(rangeslider_visible=False)
    if range_start is not None and range_end is not None:
        fig.update_xaxes(range=[range_start, range_end])
    return fig


def main() -> None:
    """Run the Streamlit dashboard entry point."""
    root = DEFAULT_ROOT
    if not Path(root).exists():
        notify_unreachable_root(root)
        return

    files_df = discover_files(root)
    if files_df.empty:
        st.warning(
            "No GTD xlsx/xlsm files found. Check the folder path and file naming pattern: "
            "GTD_YYYYMMDD_YYYYMMDD.xlsx"
        )
        return

    all_paths = tuple(files_df["path"].tolist())
    with st.spinner("Loading GTD data..."):
        raw_df = load_excels(all_paths)

    raw_df = normalize_columns(raw_df)

    time_col = detect_time_column(raw_df)
    if not time_col:
        st.error("No timestamp column was detected, so plotting cannot be built.")
        st.dataframe(raw_df.head(50), use_container_width=True)
        return

    raw_df = normalize_time_column(raw_df, time_col)
    raw_df = raw_df.dropna(subset=[time_col])
    if raw_df.empty:
        st.warning("No GTD rows were found after parsing the timestamp column.")
        return

    available_days = sorted(raw_df[time_col].dt.date.dropna().unique().tolist())
    if not available_days:
        st.warning(
            "No valid dates were found in the timestamp values across GTD files."
        )
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

    day_start = datetime.combine(selected_start_day, time.min)
    day_end_exclusive = datetime.combine(selected_end_day + timedelta(days=1), time.min)

    selected_range_df = filter_time_window(
        raw_df, time_col, day_start, day_end_exclusive
    )
    if selected_range_df.empty:
        st.warning("No GTD rows were found in the selected date range.")
        return

    available_metrics = [
        col for col in MEASUREMENT_COLUMNS if col in selected_range_df.columns
    ]
    if not available_metrics:
        st.error("None of the expected GTD measurement columns were found.")
        st.dataframe(selected_range_df.head(50), use_container_width=True)
        return

    missing_metrics = [
        col for col in MEASUREMENT_COLUMNS if col not in selected_range_df.columns
    ]
    if missing_metrics:
        st.caption("Missing GTD columns: " + ", ".join(missing_metrics))

    single_plot_df = build_plot_df(selected_range_df, time_col, available_metrics)
    single_plot_df, sample_step = downsample_plot_df(single_plot_df)

    if selected_start_day == selected_end_day:
        expected_points = int((24 * 60) / 15)
        actual_points = len(single_plot_df)
        if actual_points < expected_points:
            st.caption(
                "Selected day appears partial in source data: "
                f"{actual_points}/{expected_points} points found."
            )

    if sample_step > 1:
        st.caption(
            f"Large range detected: plotting every {sample_step}th point for faster performance."
        )

    st.plotly_chart(
        full_timeseries_figure(
            single_plot_df,
            time_col,
            available_metrics,
            range_start=day_start,
            range_end=day_end_exclusive,
        ),
        use_container_width=True,
        config={"scrollZoom": True},
    )


if __name__ == "__main__":
    main()
