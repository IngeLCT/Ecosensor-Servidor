import asyncio
from typing import Any

from nicegui import ui

from services.measurement_sync import sync_latest_measurements
from shared.styles import add_styles
from storage.measurements_store import graph_rows_history


Series = list[tuple[str, str, str]]


PARTICLE_SERIES: Series = [
    ('pm1p0', 'PM1.0', 'µg/m³'),
    ('pm2p5', 'PM2.5', 'µg/m³'),
    ('pm4p0', 'PM4.0', 'µg/m³'),
    ('pm10p0', 'PM10.0', 'µg/m³'),
]

VOC_NOX_SERIES: Series = [
    ('voc', 'VOC', 'Index'),
    ('nox', 'NOx', 'Index'),
]

AMBIENT_SERIES: Series = [
    ('co2', 'CO2', 'ppm'),
    ('temp', 'Temperatura', '°C'),
    ('hum', 'Humedad', '%'),
]


COLOR_MAP = {
    'pm1p0': '#2563eb',
    'pm2p5': '#16a34a',
    'pm4p0': '#f97316',
    'pm10p0': '#dc2626',
    'voc': '#7c3aed',
    'nox': '#0891b2',
    'co2': '#0f766e',
    'temp': '#ea580c',
    'hum': '#0284c7',
}


def _nav() -> None:
    with ui.element('nav').classes('top-nav'):
        ui.link('Mediciones', '/dashboard')
        ui.link('Partículas', '/graficas/particulas')
        ui.link('VOC NOx', '/graficas/voc-nox')
        ui.link('Ambientales', '/graficas/ambientales')


def _x_axis(rows: list[dict[str, Any]]) -> list[str]:
    labels: list[str] = []
    for row in rows:
        fecha = str(row.get('fecha') or '').strip()
        hora = str(row.get('hora') or '').strip()
        if fecha or hora:
            labels.append(f'{fecha} {hora}'.strip())
        else:
            labels.append(str(row.get('_row_id') or ''))
    return labels


def _build_figure(rows: list[dict[str, Any]], title: str, series: Series) -> Any:
    import pandas as pd
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    df = pd.DataFrame(rows)
    x_values = _x_axis(rows)
    fig = make_subplots(specs=[[{'secondary_y': title == 'Ambientales'}]])

    for key, label, unit in series:
        if key not in df:
            continue
        values = pd.to_numeric(df[key], errors='coerce')
        use_secondary_y = title == 'Ambientales' and key in {'temp', 'hum'}
        fig.add_trace(
            go.Scatter(
                x=x_values,
                y=values,
                mode='lines+markers',
                name=f'{label} ({unit})',
                line={'width': 2, 'color': COLOR_MAP.get(key)},
                marker={'size': 5},
                connectgaps=False,
            ),
            secondary_y=use_secondary_y,
        )

    fig.update_layout(
        title=title,
        template='plotly_white',
        height=620,
        margin={'l': 60, 'r': 60, 't': 70, 'b': 95},
        legend={'orientation': 'h', 'yanchor': 'bottom', 'y': 1.02, 'xanchor': 'center', 'x': 0.5},
        hovermode='x unified',
        paper_bgcolor='rgba(255,255,255,0)',
        plot_bgcolor='rgba(255,255,255,0.92)',
    )
    fig.update_xaxes(title_text='Medición', tickangle=-35, automargin=True)

    if title == 'Ambientales':
        fig.update_yaxes(title_text='CO2 (ppm)', secondary_y=False)
        fig.update_yaxes(title_text='Temperatura / Humedad', secondary_y=True)
    else:
        units = ', '.join(sorted({unit for _, _, unit in series}))
        fig.update_yaxes(title_text=units)

    return fig


def _empty_figure(title: str) -> Any:
    import plotly.graph_objects as go

    fig = go.Figure()
    fig.update_layout(
        title=title,
        template='plotly_white',
        height=620,
        annotations=[{
            'text': 'Aún no hay mediciones guardadas para graficar.',
            'showarrow': False,
            'xref': 'paper',
            'yref': 'paper',
            'x': 0.5,
            'y': 0.5,
            'font': {'size': 18},
        }],
    )
    return fig


async def _load_figure(title: str, series: Series, limit: int = 5000) -> tuple[Any | None, str | None]:
    try:
        await sync_latest_measurements()
        rows = await asyncio.to_thread(graph_rows_history, limit)
        if not rows:
            return _empty_figure(title), None
        return _build_figure(rows, title, series), None
    except ModuleNotFoundError as exc:
        missing = exc.name or 'plotly/pandas'
        return None, f'Falta instalar el paquete Python: {missing}'
    except Exception as exc:
        return None, f'No se pudo generar la gráfica: {exc}'


def _graph_page(route_title: str, page_title: str, series: Series) -> None:
    ui.page_title(page_title)
    add_styles()

    with ui.element('div').classes('dashboard'):
        _nav()
        with ui.column().classes('items-center justify-center gap-3'):
            ui.label('LCT Didacticos').classes('brand-title')
            ui.image('/static/LCT.png').props('fit=contain no-spinner').classes('connect-logo')
        ui.label(page_title).classes('section-title')
        status = ui.label('Cargando gráfica...').classes('status-line mt-3')
        chart_container = ui.column().classes('w-full mt-4')
        with ui.row().classes('justify-center gap-3 mt-4'):
            ui.button('Actualizar', on_click=lambda: ui.timer(0.1, refresh, once=True)).props('unelevated')
            ui.button('Descargar CSV', on_click=lambda: ui.navigate.to('/api/measurements.csv')).props('flat')

    chart: Any | None = None

    async def refresh() -> None:
        nonlocal chart
        figure, error = await _load_figure(route_title, series)
        if error:
            status.set_text(error)
            return
        status.set_text('')
        if chart is None:
            with chart_container:
                chart = ui.plotly(figure).classes('w-full')
        else:
            chart.figure = figure
            chart.update()

    ui.timer(8.0, refresh)
    ui.timer(0.1, refresh, once=True)


@ui.page('/graficas/particulas')
def particles_graph() -> None:
    _graph_page('Partículas', 'Gráficas de Partículas', PARTICLE_SERIES)


@ui.page('/graficas/voc-nox')
def voc_nox_graph() -> None:
    _graph_page('VOC NOx', 'Gráficas VOC NOx', VOC_NOX_SERIES)


@ui.page('/graficas/ambientales')
def ambient_graph() -> None:
    _graph_page('Ambientales', 'Gráficas Ambientales', AMBIENT_SERIES)
