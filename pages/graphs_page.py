import asyncio
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from nicegui import ui

from services.measurement_sync import sync_latest_measurements
from shared.styles import add_styles
from storage.measurements_store import graph_rows_history


MAX_BARS = 24
INITIAL_FETCH_LIMIT = 5000
SAMPLE_BASE_MIN = 5
MENU = [
    ('5 min', 5),
    ('15 min', 15),
    ('30 min', 30),
    ('1 hr', 60),
    ('2 hr', 120),
    ('4 hr', 240),
]


@dataclass(frozen=True)
class ChartSpec:
    key: str
    title: str
    unit: str
    color: str
    coverage: float = 0.90
    round_values: bool = False

    @property
    def y_title(self) -> str:
        return f'{self.title} {self.unit}' if self.unit.startswith(('(', 'µ')) else f'{self.title} ({self.unit})'


PARTICLE_CHARTS = [
    ChartSpec('pm1p0', 'PM1.0', 'µg/m³', '#ff0000'),
    ChartSpec('pm2p5', 'PM2.5', 'µg/m³', '#bfa600'),
    ChartSpec('pm4p0', 'PM4.0', 'µg/m³', '#00bfbf'),
    ChartSpec('pm10p0', 'PM10.0', 'µg/m³', '#bf00ff'),
]

VOC_NOX_CHARTS = [
    ChartSpec('voc', 'VOC', 'Index', '#ff8000'),
    ChartSpec('nox', 'NOx', 'Index', '#00ff00'),
]

AMBIENT_CHARTS = [
    ChartSpec('co2', 'CO2', 'ppm', '#990000', coverage=0.85),
    ChartSpec('temp', 'Temperatura', '°C', '#006600', coverage=0.85),
    ChartSpec('hum', 'Humedad relativa', '%', '#0000cc', coverage=0.85, round_values=True),
]


def _nav() -> None:
    with ui.element('nav').classes('top-nav'):
        ui.link('Inicio', '/dashboard')
        ui.label('|')
        ui.link('Gráficas Partículas', '/graficas/particulas')
        ui.label('|')
        ui.link('Gráficas VOC & NOx', '/graficas/voc-nox')
        ui.label('|')
        ui.link('Gráficas CO2, Temperatura & Humedad', '/graficas/ambientales')
        ui.label('|')


def _add_graph_styles() -> None:
    ui.add_head_html(
        '''
        <style>
        .chart-card {
            width: 100%;
            max-width: 1200px;
            margin: 30px auto;
            background: #cce5dc;
            border-radius: 10px;
            padding: 20px;
            box-sizing: border-box;
        }
        .agg-toolbar-wrap {
            display: flex;
            flex-direction: column;
            gap: 6px;
            margin: 8px 0 4px 0;
            width: 100%;
        }
        .agg-chart-title {
            font-weight: bold;
            font-size: 20px;
            font-family: Arial, sans-serif;
            color: #000;
            text-align: center;
            line-height: 1.1;
        }
        .agg-toolbar-label {
            font-weight: bold;
            font-size: 16px;
            font-family: Arial, sans-serif;
            color: #000;
            text-align: left;
        }
        .agg-toolbar {
            display: flex;
            gap: 6px;
            flex-wrap: wrap;
            align-items: center;
            justify-content: flex-start;
        }
        .agg-btn {
            cursor: pointer;
            user-select: none;
            padding: 6px 10px;
            border-radius: 10px;
            background: #e9f4ef !important;
            border: 2px solid #2a2a2a !important;
            font-size: 12px !important;
            font-weight: 600 !important;
            font-family: Arial, sans-serif !important;
            color: #000 !important;
            width: 96px;
            text-align: center;
            min-height: unset !important;
            transition: transform 0.12s ease, box-shadow 0.12s ease, font-size 0.12s ease;
        }
        .agg-btn:hover { box-shadow: 0 1px 0 rgba(0,0,0,.35); }
        .agg-btn.active {
            transform: scale(1.25);
            font-weight: bold !important;
            font-size: 18px !important;
            background: #d9efe7 !important;
            z-index: 1;
        }
        </style>
        '''
    )


def _parse_row_datetime(row: dict[str, Any]) -> datetime | None:
    fecha = str(row.get('fecha') or '').strip()
    hora = str(row.get('hora') or '').strip() or '00:00:00'
    if not fecha:
        return None

    fecha = fecha.replace('/', '-').replace('.', '-')
    parts = fecha.split('-')
    if len(parts) == 3 and len(parts[0]) != 4:
        fecha = f'{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}'
    elif len(parts) == 3:
        fecha = f'{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}'

    hora = hora.rstrip('Z').split('+', 1)[0]
    if len(hora) == 5:
        hora = f'{hora}:00'

    try:
        return datetime.fromisoformat(f'{fecha}T{hora[:8]}')
    except ValueError:
        return None


def _rows_to_frame(rows: list[dict[str, Any]]) -> Any:
    import pandas as pd

    prepared: list[dict[str, Any]] = []
    for row in rows:
        dt = _parse_row_datetime(row)
        if dt is None:
            continue
        item = dict(row)
        item['_dt'] = pd.Timestamp(dt)
        prepared.append(item)

    frame = pd.DataFrame(prepared)
    if frame.empty:
        return frame
    return frame.sort_values('_dt')


def _fmt_label(ts: Any) -> str:
    return ts.strftime('%Y-%m-%d %H:%M')


def _tick_text(labels: list[str], minutes: int) -> list[str]:
    out: list[str] = []
    last_date = ''
    for label in labels:
        if not label:
            out.append('')
            continue
        date_part, time_part = label.split(' ', 1)
        display = time_part[:5]
        if date_part != last_date:
            display = f'{display}<br>{date_part.split("-")[2]}-{date_part.split("-")[1]}-{date_part.split("-")[0]}'
            last_date = date_part
        out.append(display)
    return out


def _series_data(frame: Any, spec: ChartSpec, minutes: int) -> tuple[list[str], list[float | None]]:
    import pandas as pd

    empty = ([''] * MAX_BARS, [None] * MAX_BARS)
    if frame.empty or spec.key not in frame:
        return empty

    df = frame[['_dt', spec.key]].copy()
    df[spec.key] = pd.to_numeric(df[spec.key], errors='coerce')
    df = df.dropna(subset=[spec.key])
    if df.empty:
        return empty

    if minutes == SAMPLE_BASE_MIN:
        take = df.tail(MAX_BARS)
        labels = [_fmt_label(ts) for ts in take['_dt']]
        values = [float(v) for v in take[spec.key]]
    else:
        width = pd.Timedelta(minutes=minutes)
        last_ts = df['_dt'].max()
        df['_bin'] = df['_dt'].dt.floor(f'{minutes}min')
        grouped = df.groupby('_bin')[spec.key].agg(['mean', 'count']).reset_index()
        grouped = grouped[(grouped['_bin'] + width) <= last_ts]
        required = max(1, math.ceil((minutes / SAMPLE_BASE_MIN) * spec.coverage))
        grouped = grouped[grouped['count'] >= required]
        take = grouped.tail(MAX_BARS)
        labels = [_fmt_label(ts) for ts in take['_bin']]
        values = [float(v) for v in take['mean']]

    if spec.round_values:
        values = [round(v) if v is not None else None for v in values]

    if len(labels) > MAX_BARS:
        labels = labels[-MAX_BARS:]
        values = values[-MAX_BARS:]

    while len(labels) < MAX_BARS:
        labels.append('')
    while len(values) < MAX_BARS:
        values.append(None)

    return labels, values


def _build_figure(frame: Any, spec: ChartSpec, minutes: int) -> Any:
    import plotly.graph_objects as go

    labels, values = _series_data(frame, spec, minutes)
    finite = [v for v in values if isinstance(v, (int, float)) and math.isfinite(v) and v >= 0]
    upper = max(finite) * 2 if finite and max(finite) > 0 else 1
    x_values = list(range(MAX_BARS))

    fig = go.Figure(
        data=[
            go.Bar(
                x=x_values,
                y=values,
                name=spec.y_title,
                marker={'color': spec.color},
            )
        ]
    )
    fig.update_layout(
        height=600,
        margin={'t': 20, 'l': 60, 'r': 40, 'b': 110},
        bargap=0.2,
        paper_bgcolor='#cce5dc',
        plot_bgcolor='#cce5dc',
        showlegend=False,
        font={'family': 'Arial', 'color': 'black'},
    )
    fig.update_xaxes(
        type='category',
        tickmode='array',
        tickvals=x_values,
        ticktext=_tick_text(labels, minutes),
        tickangle=-45,
        automargin=True,
        gridcolor='black',
        linecolor='black',
        title={'text': '<b>Fecha y Hora de Medición</b>', 'font': {'size': 16, 'color': 'black', 'family': 'Arial'}, 'standoff': 30},
        tickfont={'color': 'black', 'size': 14, 'family': 'Arial'},
    )
    fig.update_yaxes(
        title={'text': f'<b>{spec.y_title}</b>', 'font': {'size': 16, 'color': 'black', 'family': 'Arial'}},
        tickfont={'color': 'black', 'size': 14, 'family': 'Arial'},
        rangemode='tozero',
        gridcolor='black',
        linecolor='black',
        range=[0, upper],
        fixedrange=False,
    )
    return fig


async def _load_frame(limit: int = INITIAL_FETCH_LIMIT) -> tuple[Any | None, str | None]:
    try:
        await sync_latest_measurements()
        rows = await asyncio.to_thread(graph_rows_history, limit)
        return _rows_to_frame(rows), None
    except ModuleNotFoundError as exc:
        missing = exc.name or 'plotly/pandas'
        return None, f'Falta instalar el paquete Python: {missing}'
    except Exception as exc:
        return None, f'No se pudieron cargar las mediciones: {exc}'


def _graph_page(page_title: str, charts: list[ChartSpec]) -> None:
    ui.page_title(page_title)
    add_styles()
    _add_graph_styles()

    states = {spec.key: SAMPLE_BASE_MIN for spec in charts}
    plot_widgets: dict[str, Any] = {}
    buttons: dict[str, list[Any]] = {spec.key: [] for spec in charts}
    frame_cache: Any | None = None

    with ui.element('div').classes('dashboard'):
        _nav()
        with ui.column().classes('items-center justify-center gap-3'):
            ui.label('LCT Didacticos').classes('brand-title')
            ui.image('/static/LCT.png').props('fit=contain no-spinner').classes('connect-logo')
        ui.label(page_title).classes('section-title')
        status = ui.label('Cargando gráficas...').classes('status-line mt-3')

        for spec in charts:
            with ui.column().classes('chart-card'):
                ui.label(spec.y_title).classes('agg-chart-title')
                ui.label('Seleccione el intervalo de lecturas').classes('agg-toolbar-label')
                with ui.row().classes('agg-toolbar'):
                    for label, minutes in MENU:
                        button = ui.button(label).props('flat no-caps').classes('agg-btn')
                        buttons[spec.key].append(button)

                        async def select_interval(m: int = minutes, s: ChartSpec = spec) -> None:
                            states[s.key] = m
                            await redraw_one(s)

                        button.on('click', select_interval)
                plot_widgets[spec.key] = ui.plotly({}).classes('w-full')

        with ui.row().classes('justify-center gap-3 mt-4'):
            ui.button('Actualizar', on_click=lambda: ui.timer(0.1, refresh, once=True)).props('unelevated')
            ui.button('Descargar CSV', on_click=lambda: ui.navigate.to('/api/measurements.csv')).props('flat')

    def update_active_buttons(spec: ChartSpec) -> None:
        active_minutes = states[spec.key]
        for button, (_, minutes) in zip(buttons[spec.key], MENU):
            if minutes == active_minutes:
                button.classes(add='active')
            else:
                button.classes(remove='active')

    async def redraw_one(spec: ChartSpec) -> None:
        if frame_cache is None:
            return
        try:
            figure = _build_figure(frame_cache, spec, states[spec.key])
            plot_widgets[spec.key].figure = figure
            plot_widgets[spec.key].update()
            update_active_buttons(spec)
        except ModuleNotFoundError as exc:
            status.set_text(f'Falta instalar el paquete Python: {exc.name or "plotly/pandas"}')
        except Exception as exc:
            status.set_text(f'No se pudo generar {spec.y_title}: {exc}')

    async def refresh() -> None:
        nonlocal frame_cache
        frame, error = await _load_frame()
        if error:
            status.set_text(error)
            return
        frame_cache = frame
        status.set_text('')
        for spec in charts:
            await redraw_one(spec)

    ui.timer(8.0, refresh)
    ui.timer(0.1, refresh, once=True)


@ui.page('/graficas/particulas')
def particles_graph() -> None:
    _graph_page('Gráficas Tiempo Real - Partículas', PARTICLE_CHARTS)


@ui.page('/graficas/voc-nox')
def voc_nox_graph() -> None:
    _graph_page('Gráficas Tiempo Real - VOC & NOx', VOC_NOX_CHARTS)


@ui.page('/graficas/ambientales')
def ambient_graph() -> None:
    _graph_page('Gráficas Tiempo Real - CO2, Temperatura & Humedad', AMBIENT_CHARTS)
