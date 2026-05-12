import asyncio
import html
import json
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from nicegui import ui

from services.measurement_sync import sync_latest_measurements
from shared.styles import add_styles
from storage.measurements_store import graph_rows_all, graph_rows_history


MAX_BARS = 24
INITIAL_FETCH_LIMIT = 5000
SAMPLE_BASE_MIN = 5
SERVER_REFRESH_SECONDS = 60.0
MENU = [
    ('5 min', 5),
    ('15 min', 15),
    ('30 min', 30),
    ('1 hr', 60),
    ('2 hr', 120),
    ('4 hr', 240),
]

HISTORY_MENU = [
    ('5 min', 5),
    ('15 min', 15),
    ('30 min', 30),
    ('1 hr', 60),
    ('2 hr', 120),
    ('6 hr', 360),
    ('12 hr', 720),
    ('24 hr', 1440),
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
        ui.link('Gráficas del Historial', '/graficas/historial')
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
        .history-controls {
            background-color: #cce5dc;
            padding: 20px;
            margin: 20px auto;
            border-radius: 8px;
            max-width: 800px;
            text-align: center;
        }
        .history-select-label {
            margin-bottom: 8px;
            display: block;
            color: #000;
            font-size: 22px;
            font-weight: bold;
            text-align: center;
        }
        .history-slider-box {
            width: 100%;
            max-width: 900px;
            margin: 2em auto;
            padding: 2em 1em;
        }
        .double_range_slider {
            position: relative;
            width: 100%;
            height: 10px;
            background-color: #dddddd;
            border-radius: 10px;
            margin-top: 34px;
        }
        .range_track {
            position: absolute;
            height: 100%;
            background-color: #95d564;
            border-radius: 10px;
            z-index: 1;
        }
        .double_range_slider input[type="range"] {
            position: absolute;
            width: 100%;
            height: 10px;
            background: none;
            pointer-events: none;
            -webkit-appearance: none;
            appearance: none;
            top: 0;
            left: 0;
            margin: 0;
            z-index: 2;
        }
        .double_range_slider input.min { z-index: 3; }
        .double_range_slider input::-webkit-slider-thumb {
            height: 20px;
            width: 20px;
            border-radius: 50%;
            background: #95d564;
            border: 2px solid #2a2a2a;
            pointer-events: auto;
            -webkit-appearance: none;
            cursor: pointer;
        }
        .double_range_slider input::-moz-range-thumb {
            height: 20px;
            width: 20px;
            border-radius: 50%;
            background: #95d564;
            border: 2px solid #2a2a2a;
            pointer-events: auto;
            cursor: pointer;
        }
        .minvalue, .maxvalue {
            position: absolute;
            top: 24px;
            transform: translateX(-50%);
            color: #000;
            font-size: 14px;
            font-weight: bold;
            white-space: nowrap;
        }
        .history-range-label {
            color: #000;
            font-size: 16px;
            font-weight: bold;
            min-height: 22px;
        }
        .data-table-container {
            width: 100%;
            overflow-x: auto;
            margin-top: 24px;
        }
        .data-table-container table {
            width: 100%;
            border-collapse: separate;
            border-spacing: 0;
        }
        .data-table-container th,
        .data-table-container td {
            font-size: 20px;
            text-align: center;
            border: 1px solid black;
            border-radius: 10px;
            padding: 8px;
        }
        .data-table-container th { background-color: #80ffd4; }
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

    ui.timer(SERVER_REFRESH_SECONDS, refresh)
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


HISTORY_OPTIONS: dict[str, ChartSpec] = {
    'pm1p0': ChartSpec('pm1p0', 'PM1.0', 'µg/m³', '#ff0000'),
    'pm2p5': ChartSpec('pm2p5', 'PM2.5', 'µg/m³', '#bfa600'),
    'pm4p0': ChartSpec('pm4p0', 'PM4.0', 'µg/m³', '#00bfbf'),
    'pm10p0': ChartSpec('pm10p0', 'PM10.0', 'µg/m³', '#bf00ff'),
    'voc': ChartSpec('voc', 'VOC', 'Index', '#ff8000'),
    'nox': ChartSpec('nox', 'NOx', 'Index', '#00ff00'),
    'co2': ChartSpec('co2', 'CO2', 'ppm', '#990000'),
    'temp': ChartSpec('temp', 'Temperatura', '°C', '#006600'),
    'hum': ChartSpec('hum', 'Humedad', '%', '#0000cc', round_values=True),
}

HISTORY_SELECT_OPTIONS = {
    'pm1p0': 'PM1.0',
    'pm2p5': 'PM2.5',
    'pm4p0': 'PM4.0',
    'pm10p0': 'PM10.0',
    'voc': 'VOC',
    'nox': 'NOx',
    'co2': 'CO2',
    'temp': 'Temperatura',
    'hum': 'Humedad',
}


def _interval_label(minutes: int) -> str:
    for label, value in HISTORY_MENU:
        if value == minutes:
            return label
    return f'{minutes} min'


def _history_series_data(frame: Any, spec: ChartSpec, minutes: int) -> tuple[list[str], list[float], list[Any]]:
    import pandas as pd

    if frame.empty or spec.key not in frame:
        return [], [], []

    df = frame[['_dt', spec.key]].copy()
    df[spec.key] = pd.to_numeric(df[spec.key], errors='coerce')
    df = df.dropna(subset=[spec.key])
    if df.empty:
        return [], [], []

    if minutes == SAMPLE_BASE_MIN:
        labels = [_fmt_label(ts) for ts in df['_dt']]
        values = [float(v) for v in df[spec.key]]
        times = list(df['_dt'])
    else:
        rule = '1D' if minutes == 1440 else f'{minutes}min'
        df['_bin'] = df['_dt'].dt.floor(rule)
        grouped = df.groupby('_bin')[spec.key].agg(['mean', 'count']).reset_index()
        required = max(1, math.ceil((minutes / SAMPLE_BASE_MIN) * 0.90))
        grouped = grouped[grouped['count'] >= required]
        labels = [_fmt_label(ts) for ts in grouped['_bin']]
        values = [float(v) for v in grouped['mean']]
        times = list(grouped['_bin'])

    if spec.round_values:
        values = [round(v) for v in values]

    return labels, values, times


def _history_ticks(times: list[Any], minutes: int) -> tuple[list[Any], list[str]]:
    if not times:
        return [], []
    max_ticks = 10 if minutes == 1440 else 14
    if len(times) <= max_ticks:
        selected = list(range(len(times)))
    else:
        step = math.ceil(len(times) / max_ticks)
        selected = list(range(0, len(times), step))
        if selected[-1] != len(times) - 1:
            selected.append(len(times) - 1)

    tickvals = [times[i] for i in selected]
    ticktext: list[str] = []
    previous_date = ''
    for i in selected:
        ts = times[i]
        if minutes == 1440:
            ticktext.append(ts.strftime('%d-%m-%Y'))
            continue
        base = ts.strftime('%H:%M')
        date = ts.strftime('%d-%m-%Y')
        if date != previous_date:
            ticktext.append(f'{base}<br>{date}')
            previous_date = date
        else:
            ticktext.append(base)
    return tickvals, ticktext


def _history_time_to_json(ts: Any) -> str:
    return ts.isoformat() if hasattr(ts, 'isoformat') else str(ts)


def _build_history_figure(labels: list[str], values: list[float], times: list[Any], spec: ChartSpec, minutes: int) -> Any:
    import plotly.graph_objects as go

    finite = [v for v in values if isinstance(v, (int, float)) and math.isfinite(v) and v >= 0]
    upper = max(finite) * 2 if finite and max(finite) > 0 else 1
    tickvals, ticktext = _history_ticks(times, minutes)
    json_times = [_history_time_to_json(ts) for ts in times]
    json_tickvals = [_history_time_to_json(ts) for ts in tickvals]

    fig = go.Figure(data=[go.Bar(x=json_times, y=values, name=spec.title, marker={'color': spec.color})])
    fig.update_layout(
        height=600,
        margin={'t': 20, 'l': 60, 'r': 40, 'b': 95 if minutes == 1440 else 130},
        bargap=0.2,
        paper_bgcolor='#cce5dc',
        plot_bgcolor='#cce5dc',
        showlegend=False,
        font={'family': 'Arial', 'color': 'black'},
    )
    fig.update_xaxes(
        type='date',
        tickmode='array',
        tickvals=json_tickvals,
        ticktext=ticktext,
        tickangle=-30 if minutes == 1440 else -45,
        automargin=True,
        rangeslider={'visible': False},
        showgrid=False,
        zeroline=False,
        showline=True,
        title={
            'text': '<b>Fecha de Medición</b>' if minutes == 1440 else '<b>Fecha y Hora de Medición</b>',
            'font': {'size': 16, 'color': 'black', 'family': 'Arial'},
            'standoff': 36,
        },
        tickfont={'color': 'black', 'size': 14, 'family': 'Arial'},
    )
    fig.update_yaxes(
        title={'text': f'<b>{spec.y_title}</b>', 'font': {'size': 16, 'color': 'black', 'family': 'Arial'}},
        tickfont={'color': 'black', 'size': 14, 'family': 'Arial'},
        rangemode='tozero',
        range=[0, upper],
        fixedrange=False,
        showgrid=False,
        zeroline=False,
        showline=True,
    )
    return fig


def _history_slider_script() -> str:
    return """
    <script>
    (() => {
      if (window.__ecosensorHistorySliderReady) return;
      window.__ecosensorHistorySliderReady = true;

      function labelsFor(root) {
        try { return JSON.parse(root.dataset.labels || '[]'); }
        catch (e) { return []; }
      }

      function update(root) {
        if (!root) return;
        const labels = labelsFor(root);
        const minInput = root.querySelector('input.min');
        const maxInput = root.querySelector('input.max');
        const track = root.querySelector('.range_track');
        const minBubble = root.querySelector('.minvalue');
        const maxBubble = root.querySelector('.maxvalue');
        if (!minInput || !maxInput || !track || !minBubble || !maxBubble) return;

        const max = Number(maxInput.max || 0);
        const minGap = Math.min(6, max);
        let minVal = Number(minInput.value || 0);
        let maxVal = Number(maxInput.value || 0);

        if (maxVal - minVal < minGap) {
          if (document.activeElement === minInput) minVal = Math.max(0, maxVal - minGap);
          else maxVal = Math.min(max, minVal + minGap);
          minInput.value = minVal;
          maxInput.value = maxVal;
        }

        const denom = max || 1;
        const left = (minVal / denom) * 100;
        const right = 100 - (maxVal / denom) * 100;
        track.style.left = left + '%';
        track.style.right = right + '%';
        minBubble.style.left = left + '%';
        maxBubble.style.left = (maxVal / denom) * 100 + '%';
        minBubble.textContent = labels[Number(minVal)] || String(minVal);
        maxBubble.textContent = labels[Number(maxVal)] || String(maxVal);

        root.dispatchEvent(new CustomEvent('history-range-change', {
          bubbles: true,
          detail: { start: minVal, end: maxVal }
        }));
      }

      document.addEventListener('input', (event) => {
        const input = event.target;
        if (!(input instanceof HTMLInputElement)) return;
        const root = input.closest('.double_range_slider[data-history-slider=\"1\"]');
        if (root) update(root);
      });

      const observer = new MutationObserver(() => {
        document.querySelectorAll('.double_range_slider[data-history-slider=\"1\"]').forEach(update);
      });
      observer.observe(document.body, { childList: true, subtree: true });
      document.querySelectorAll('.double_range_slider[data-history-slider=\"1\"]').forEach(update);
    })();
    </script>
    """


def _history_slider_html(labels: list[str], start: int = 0, end: int | None = None) -> str:
    max_idx = max(0, len(labels) - 1)
    if end is None:
        end = max_idx
    start = max(0, min(start, max_idx))
    end = max(0, min(end, max_idx))
    if start > end:
        start, end = end, start
    labels_json = html.escape(json.dumps(labels, ensure_ascii=False), quote=True)
    return f'''
    <div class="double_range_slider_box">
      <div class="double_range_slider" id="historyRangeRoot" data-history-slider="1" data-labels="{labels_json}">
        <span class="range_track" id="historyRangeTrack"></span>
        <input type="range" class="max" min="0" max="{max_idx}" value="{end}" step="1" />
        <input type="range" class="min" min="0" max="{max_idx}" value="{start}" step="1" />
        <div class="minvalue">0</div>
        <div class="maxvalue">{max_idx}</div>
      </div>
    </div>
    '''


def _history_table_html(labels: list[str], values: list[float], spec: ChartSpec, minutes: int) -> str:
    unit_label = _interval_label(minutes)
    rows = []
    for idx, (label, value) in enumerate(zip(labels, values)):
        if spec.round_values:
            pretty = str(round(value))
        else:
            pretty = f'{value:.2f}'
        rows.append(f'<tr><td>{idx}</td><td>{label or "-"}</td><td>{pretty}</td></tr>')
    return (
        '<div class="data-table-container">'
        '<table id="uploadTable">'
        '<thead><tr>'
        '<th>#</th>'
        f'<th>Fecha y Hora ({unit_label})</th>'
        f'<th>{spec.title.upper()}</th>'
        '</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody>'
        '</table></div>'
    )


@ui.page('/graficas/historial')
def history_graph() -> None:
    ui.page_title('Gráficas del Historial')
    add_styles()
    _add_graph_styles()
    ui.add_body_html(_history_slider_script())

    frame_cache: Any | None = None
    current_labels: list[str] = []
    current_values: list[float] = []
    current_times: list[Any] = []
    current_minutes = SAMPLE_BASE_MIN
    range_start = 0
    range_end = 0

    with ui.element('div').classes('dashboard'):
        _nav()
        with ui.column().classes('items-center justify-center gap-3'):
            ui.label('LCT Didacticos').classes('brand-title')
            ui.image('/static/LCT.png').props('fit=contain no-spinner').classes('connect-logo')
        ui.label('Gráficas del Historial').classes('section-title')
        status = ui.label('Cargando historial...').classes('status-line mt-3')

        ui.separator()
        ui.label('Gráfica de Datos Historico').classes('section-title')
        with ui.column().classes('history-controls'):
            ui.label('Seleccionar Dato a Graficar:').classes('history-select-label')
            selector = ui.select(HISTORY_SELECT_OPTIONS, value='pm1p0').props('outlined dense').classes('w-full')

        with ui.column().classes('agg-toolbar-wrap'):
            ui.label('Historial').classes('agg-chart-title')
            ui.label('Seleccione el intervalo de lecturas').classes('agg-toolbar-label')
            interval_buttons: list[Any] = []
            with ui.row().classes('agg-toolbar'):
                for label, minutes in HISTORY_MENU:
                    button = ui.button(label).props('flat no-caps').classes('agg-btn')
                    interval_buttons.append(button)

                    async def select_interval(m: int = minutes) -> None:
                        nonlocal current_minutes
                        current_minutes = m
                        await rebuild()

                    button.on('click', select_interval)

        with ui.column().classes('history-slider-box'):
            ui.label('Seleccione el rango del historial').classes('history-select-label')
            slider_html = ui.html(_history_slider_html([])).classes('w-full')

        chart = ui.plotly({}).classes('w-full chart-card')
        table = ui.html('').classes('w-full')
        with ui.row().classes('justify-center gap-3 mt-4'):
            ui.button('Actualizar historial', on_click=lambda: ui.timer(0.1, load_history, once=True)).props('unelevated')
            ui.button('Descargar CSV', on_click=lambda: ui.navigate.to('/api/measurements.csv')).props('flat')

    def update_interval_buttons() -> None:
        for button, (_, minutes) in zip(interval_buttons, HISTORY_MENU):
            if minutes == current_minutes:
                button.classes(add='active')
            else:
                button.classes(remove='active')

    def slider_bounds() -> tuple[int, int]:
        if not current_labels:
            return 0, 0
        max_idx = len(current_labels) - 1
        start = max(0, min(range_start, max_idx))
        end = max(0, min(range_end, max_idx))
        if start > end:
            start, end = end, start
        return start, end

    async def redraw() -> None:
        if not current_labels:
            chart.figure = _build_history_figure([], [], [], HISTORY_OPTIONS[str(selector.value)], current_minutes)
            chart.update()
            table.set_content('')
            return
        start, end = slider_bounds()
        spec = HISTORY_OPTIONS[str(selector.value)]
        labels = current_labels[start:end + 1]
        values = current_values[start:end + 1]
        times = current_times[start:end + 1]
        chart.figure = _build_history_figure(labels, values, times, spec, current_minutes)
        chart.update()
        table.set_content(_history_table_html(labels, values, spec, current_minutes))

    async def rebuild() -> None:
        nonlocal current_labels, current_values, current_times, range_start, range_end
        if frame_cache is None:
            return
        spec = HISTORY_OPTIONS[str(selector.value)]
        current_labels, current_values, current_times = _history_series_data(frame_cache, spec, current_minutes)
        max_idx = max(0, len(current_labels) - 1)
        range_start = 0
        range_end = max_idx
        slider_html.set_content(_history_slider_html(current_labels, range_start, range_end))
        update_interval_buttons()
        await redraw()

    async def load_history() -> None:
        nonlocal frame_cache
        try:
            status.set_text('Cargando historial...')
            await sync_latest_measurements()
            rows = await asyncio.to_thread(graph_rows_all)
            frame_cache = _rows_to_frame(rows)
            if frame_cache.empty:
                status.set_text('Error al cargar historial: no hay registros utilizables.')
            else:
                total = len(frame_cache)
                last = frame_cache.iloc[-1]
                status.set_text(f'Historial cargado. Registros: {total}. Última medición: {last["fecha"]} {last["hora"]}')
            await rebuild()
        except ModuleNotFoundError as exc:
            status.set_text(f'Falta instalar el paquete Python: {exc.name or "plotly/pandas"}')
        except Exception as exc:
            status.set_text(f'Error al cargar historial: {exc}')

    async def on_history_range_change(e) -> None:
        nonlocal range_start, range_end
        args = getattr(e, 'args', None)
        if isinstance(args, dict):
            range_start = int(args.get('start', range_start))
            range_end = int(args.get('end', range_end))
        elif isinstance(args, (list, tuple)) and len(args) >= 2:
            range_start = int(args[0])
            range_end = int(args[1])
        await redraw()

    selector.on('update:model-value', lambda: ui.timer(0.1, rebuild, once=True))
    slider_html.on(
        'history-range-change',
        on_history_range_change,
        args=['event.detail.start', 'event.detail.end'],
    )
    ui.timer(0.1, load_history, once=True)
