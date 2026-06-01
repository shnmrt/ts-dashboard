# Geothermal Timeseries Dashboards

Streamlit dashboards for visualizing geothermal production timeseries from two data sources:

- GTD (Excel workbooks)
- ESP (Parquet files)

This repository shares the dashboard applications and their Python dependencies in [requirements.txt](requirements.txt).

## Repository Contents

- [gtd.py](gtd.py): GTD dashboard (Excel input, multi-panel timeseries)
- [esp.py](esp.py): ESP dashboard (Parquet input, multi-panel timeseries)
- [requirements.txt](requirements.txt): Python dependencies

## Features

- Date-range based plotting from sidebar controls
- Large-range point downsampling for responsive charts
- Fixed multi-panel layout for key process measurements
- Automatic notification when source root paths are unreachable
- Column normalization for known GTD header variants

## Data Expectations

### GTD

- Default root path:
  /Volumes/staff-umbrella/DAPWELL DATA/13_production data/GTD
- Supported file formats: .xlsx, .xlsm
- File naming pattern:
  GTD_YYYYMMDD_YYYYMMDD.xlsx
  GTD_YYYYMMDD_YYYYMMDD.xlsm

### ESP

- Default root path:
  /Volumes/staff-umbrella/DAPWELL DATA/13_production data/ESP
- Supported file format: .parquet
- File naming pattern:
  ESP_YYYYMMDDTHHMMSS_YYYYMMDDTHHMMSS.parquet

## Requirements

Python 3.10 or newer is recommended.

Dependencies are listed in [requirements.txt](requirements.txt), including:

- streamlit
- plotly
- polars-lts-cpu
- pyarrow
- duckdb
- pandas
- openpyxl

## Installation

1. Clone this repository.
2. Choose one environment manager below (venv, uv, or conda).
3. Install dependencies from [requirements.txt](requirements.txt).

### Option A: pip + venv

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Option B: uv

Install uv (macOS/Linux):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Create environment and install dependencies:

```bash
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

### Option C: conda

Create and activate a conda environment, then install from requirements:

```bash
conda create -n geothermal-dashboard python=3.11 -y
conda activate geothermal-dashboard
pip install -r requirements.txt
```

### Windows-specific setup

Use the following alternatives on Windows.

Option A (venv, PowerShell):

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Option A (venv, Command Prompt):

```bat
py -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
```

Option B (uv, PowerShell):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
uv venv
.\.venv\Scripts\Activate.ps1
uv pip install -r requirements.txt
```

Option C (conda, Anaconda Prompt or PowerShell):

```bat
conda create -n geothermal-dashboard python=3.11 -y
conda activate geothermal-dashboard
pip install -r requirements.txt
```

## Run the Dashboards

Run GTD dashboard:

```bash
streamlit run gtd.py
```

Run ESP dashboard:

```bash
streamlit run esp.py
```

Streamlit will print a local URL in the terminal (usually http://localhost:8501).

## Configuration

If your data location is different, update DEFAULT_ROOT in each script:

- [gtd.py](gtd.py)
- [esp.py](esp.py)

## Troubleshooting

- Unreachable source folder:
  The app shows a popup and an error message when DEFAULT_ROOT is not reachable.
- No files found:
  Verify path mount/access and confirm filename pattern matches expected format.
- Missing columns:
  Dashboards display missing metric columns in-app when source schema differs.

## Notes

- These apps are read-only visual dashboards.
- They are optimized for operational monitoring and quick timeseries inspection.

## License

Add your preferred license for open-source sharing (for example, MIT).
