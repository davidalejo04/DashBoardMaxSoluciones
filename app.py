import streamlit as st
import pandas as pd
import pyodbc
import datetime
import time

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Dashboard de Asignación DB", layout="wide")
st.title("🗓️ Sistema de Gestión y Asignación de Labores")

# === EVITAR CONGELAMIENTOS EN INACTIVIDAD ===
pyodbc.pooling = False 

# --- CONFIGURACIÓN DE CONEXIÓN ---
CONN_STR = st.secrets["CONN_STR"]

def ejecutar_query(query, params=None):
    """Función de solo lectura con reintentos automáticos para manejar el despertar de Azure SQL."""
    intentos_maximos = 4
    
    for intento in range(intentos_maximos):
        try:
            with pyodbc.connect(CONN_STR, timeout=5) as conn:
                with conn.cursor() as cursor:
                    if params:
                        return pd.read_sql(query, conn, params=params)
                    else:
                        return pd.read_sql(query, conn)
                        
        except pyodbc.OperationalError:
            if intento == intentos_maximos - 1:
                st.cache_data.clear()
                st.error("🥶 El servidor de la base de datos tardó demasiado en responder. Por favor, refresca la página 🔄.")
                return pd.DataFrame()
            
            with st.spinner(f"⏳ El servidor de datos se estaba durmiendo. Despertándolo de forma segura... (Intento {intento + 1}/{intentos_maximos})"):
                time.sleep(4)

# --- DICCIONARIO DE COLORES PARA NOVEDADES (VISTA AGENDA) ---
COLOR_MAP = {
    'NORMAL': '#d4edda',   # Verde claro
    'D001': '#e2e3e5',     # Gris (Descanso)
    'I002': '#f8d7da',     # Rojo claro (Incapacidad)
    'CF003': '#fff3cd',    # Amarillo claro (Calamidad)
    'PNR04': '#ffeeba',    # Naranja (Permiso No Remunerado)
    'AU005': '#f5c6cb',    # Rojo Fuerte (Ausencia)
    'VA006': '#cce5ff',    # Azul claro (Vacaciones)
    'SU007': '#d6d8db'     # Gris oscuro (Suspensión)
}
DEFAULT_COLOR = '#e8daef'

# --- CARGA DE DATOS DESDE LA DB ---
@st.cache_data(ttl=600)
def cargar_datos_db():
    try:
        # CORRECCIÓN: Se incorpora el LEFT JOIN a Vigencia_Empleados (ve) para traer ID_Cargo de manera correcta
        query_principal = """
            SELECT 
                COALESCE(p.ID_Empleado, ej.ID_Empleado) AS ID_Empleado,
                COALESCE(e.Empleado_Nam, e_ej.Empleado_Nam) AS Empleado_Nam,
                COALESCE(p.ID_Unidad, ej.ID_Unidad) AS ID_Unidad,
                COALESCE(u.Unidad_Desc, u_ej.Unidad_Desc) AS Unidad_Desc,
                COALESCE(p.Fecha, ej.Fecha) AS Fecha,
                COALESCE(p.ID_Turno, ej.ID_Turno) AS ID_Turno,
                COALESCE(t.Punch_In, t_ej.Punch_In) AS Punch_In,
                COALESCE(t.Punch_Out, t_ej.Punch_Out) AS Punch_Out,
                ej.ID_Novedad,
                ve.ID_Cargo,
                ISNULL(ej.Duracion_Novedad, 0) AS Duracion_Novedad,
                CASE WHEN p.ID_Empleado IS NULL THEN 1 ELSE 0 END AS Es_Solo_Ejecucion
            FROM Programacion p
            LEFT JOIN N_Empleados e ON TRIM(p.ID_Empleado) = TRIM(e.ID_Empleado)
            LEFT JOIN N_Unidades u ON TRIM(p.ID_Unidad) = TRIM(u.ID_Unidad)
            LEFT JOIN N_Turnos t ON TRIM(p.ID_Turno) = TRIM(t.ID_Turno)
            FULL OUTER JOIN Ejecucion ej ON TRIM(p.ID_Empleado) = TRIM(ej.ID_Empleado) 
                                        AND TRIM(p.ID_Unidad) = TRIM(ej.ID_Unidad) 
                                        AND p.Fecha = ej.Fecha
                                        AND TRIM(p.ID_Turno) = TRIM(ej.ID_Turno)
            LEFT JOIN N_Turnos t_ej ON TRIM(ej.ID_Turno) = TRIM(t_ej.ID_Turno)
            LEFT JOIN N_Empleados e_ej ON TRIM(ej.ID_Empleado) = TRIM(e_ej.ID_Empleado)
            LEFT JOIN N_Unidades u_ej ON TRIM(ej.ID_Unidad) = TRIM(u_ej.ID_Unidad)
            LEFT JOIN Vigencia_Empleados ve ON TRIM(ve.ID_Empleado) = TRIM(COALESCE(p.ID_Empleado, ej.ID_Empleado))
            WHERE p.ID_Empleado IS NOT NULL OR TRIM(ve.ID_Cargo) = 'OV001'
        """
        df_completo = ejecutar_query(query_principal)
        
        query_novedades = "SELECT ID_Novedad, Novedad_Desc FROM N_Novedades"
        df_nov = ejecutar_query(query_novedades)
        
        if not df_completo.empty:
            df_completo['Fecha'] = pd.to_datetime(df_completo['Fecha'])
            df_completo['Año'] = df_completo['Fecha'].dt.year
            df_completo['Semana'] = df_completo['Fecha'].dt.isocalendar().week
            df_completo['Dia_Nombre'] = df_completo['Fecha'].dt.day_name().map({
                'Monday': '1-Lunes', 'Tuesday': '2-Martes', 'Wednesday': '3-Miércoles',
                'Thursday': '4-Jueves', 'Friday': '5-Viernes', 'Saturday': '6-Sábado', 'Sunday': '7-Domingo'
            })
        
        return df_completo, df_nov
    except Exception as e:
        st.error(f"⚠️ Error al procesar datos: {e}")
        return pd.DataFrame(), pd.DataFrame()

# Cargar la información global
df, df_novedades = cargar_datos_db()

if df.empty:
    st.warning("No hay datos disponibles para mostrar.")
    st.stop()

# --- FUNCIÓN EXTRACTORA DE HORAS ---
def expandir_horas(row):
    try:
        def parse_hora(val):
            if isinstance(val, datetime.time):
                return val.hour
            return int(str(val).split(':')[0])

        start_h = parse_hora(row['Punch_In'])
        end_h = parse_hora(row['Punch_Out'])
        if end_h <= start_h:
            end_h += 24
        return [f"{h % 24:02d}:00" for h in range(start_h, end_h)]
    except:
        return []

# ==============================================================================
# --- CREACIÓN DE PESTAÑAS PRINCIPALES ---
# ==============================================================================
tab_agenda, tab_resumen = st.tabs(["📅 Vista de Agenda Semanal", "📊 Resumen Consolidado de Horas"])

# ------------------------------------------------------------------------------
# PESTAÑA 1: VISTA DE AGENDA SEMANAL
# ------------------------------------------------------------------------------
with tab_agenda:
    st.sidebar.header("Filtros: Agenda Semanal")
    anos_disponibles = sorted(df['Año'].dropna().unique())
    ano_seleccionado = st.sidebar.selectbox("Seleccione el Año", anos_disponibles, key="sb_ano")

    df_ano = df[df['Año'] == ano_seleccionado].copy()
    semanas_disponibles = sorted(df_ano['Semana'].dropna().unique())

    def formatear_opcion_semana(num_semana):
        try:
            lunes = datetime.date.fromisocalendar(int(ano_seleccionado), int(num_semana), 1)
            domingo = datetime.date.fromisocalendar(int(ano_seleccionado), int(num_semana), 7)
            return f"Semana {num_semana} ({lunes.strftime('%d/%m/%Y')} al {domingo.strftime('%d/%m/%Y')})"
        except:
            return f"Semana {num_semana}"

    semana_seleccionada = st.sidebar.selectbox(
        "Seleccione la Semana", semanas_disponibles, format_func=formatear_opcion_semana, key="sb_semana"
    )

    vista_seleccionada = st.sidebar.radio(
        "Modalidad de Agenda", ("1. Por Trabajador (Ver Unidades)", "2. Por Unidad (Ver Trabajadores)"), key="sb_vista"
    )

    df_semana = df_ano[df_ano['Semana'] == semana_seleccionada].copy()

    if "Por Trabajador" in vista_seleccionada:
        lista_empleados = sorted(df_semana['Empleado_Nam'].dropna().unique())
        entidad_seleccionada = st.sidebar.selectbox("Seleccione el Trabajador", lista_empleados, key="sb_emp")
        df_filtrado = df_semana[df_semana['Empleado_Nam'] == entidad_seleccionada]
        col_a_mostrar = 'Unidad_Desc'
    else:
        lista_unidades = sorted(df_semana['Unidad_Desc'].dropna().unique())
        entidad_seleccionada = st.sidebar.selectbox("Seleccione la Unidad", lista_unidades, key="sb_uni")
        df_filtrado = df_semana[df_semana['Unidad_Desc'] == entidad_seleccionada]
        col_a_mostrar = 'Empleado_Nam'

    try:
        fecha_lunes = datetime.date.fromisocalendar(int(ano_seleccionado), int(semana_seleccionada), 1)
        fecha_domingo = datetime.date.fromisocalendar(int(ano_seleccionado), int(semana_seleccionada), 7)
        rango_fechas_str = f"{fecha_lunes.strftime('%d/%m/%Y')} al {fecha_domingo.strftime('%d/%m/%Y')}"
    except:
        rango_fechas_str = "Rango no disponible"

    if not df_filtrado.empty:
        df_filtrado['Hora'] = df_filtrado.apply(expandir_horas, axis=1)
        df_horario = df_filtrado.explode('Hora').dropna(subset=['Hora'])

        if not df_horario.empty:
            def construir_celda(row):
                texto = str(row[col_a_mostrar])
                if pd.notna(row['ID_Novedad']) and str(row['ID_Novedad']).strip() != '':
                    texto += f" [{row['ID_Novedad'].strip()}]"
                return texto

            df_horario['Celda_Texto'] = df_horario.apply(construir_celda, axis=1)
            
            def asignar_color_celda(r):
                cargo = str(r['ID_Cargo']).strip() if pd.notna(r['ID_Cargo']) else ''
                nov = str(r['ID_Novedad']).strip() if pd.notna(r['ID_Novedad']) else ''
                if cargo == 'OV001' and nov == 'AS001':
                    return COLOR_MAP['NORMAL']
                return COLOR_MAP.get(nov, DEFAULT_COLOR) if nov != '' else COLOR_MAP['NORMAL']

            df_horario['Color_Celda'] = df_horario.apply(asignar_color_celda, axis=1)

            pivot_text = df_horario.pivot_table(index='Hora', columns='Dia_Nombre', values='Celda_Texto', aggfunc=lambda x: ' / '.join(set(x)))
            pivot_color = df_horario.pivot_table(index='Hora', columns='Dia_Nombre', values='Color_Celda', aggfunc='first')

            horas_dia = [f"{h:02d}:00" for h in range(24)]
            dias_semana = ['1-Lunes', '2-Martes', '3-Miércoles', '4-Jueves', '5-Viernes', '6-Sábado', '7-Domingo']
            
            pivot_text = pivot_text.reindex(index=horas_dia, columns=dias_semana).fillna('')
            pivot_color = pivot_color.reindex(index=horas_dia, columns=dias_semana).fillna('')

            columnas_limpias = [c.split('-')[1] for c in pivot_text.columns]
            pivot_text.columns = columnas_limpias
            pivot_color.columns = columnas_limpias

            def aplicar_estilos_matriz(x):
                styles = pd.DataFrame('', index=x.index, columns=x.columns)
                for col in x.columns:
                    if col in pivot_color.columns:
                        styles[col] = pivot_color[col].apply(
                            lambda color: f'background-color: {color}; color: #222; font-weight: bold;' if color else ''
                        )
                return styles

            st.subheader(f"📅 Agenda: {entidad_seleccionada} — Semana {semana_seleccionada} ({rango_fechas_str})")
            df_estilizado = pivot_text.style.apply(aplicar_estilos_matriz, axis=None)
            st.dataframe(df_estilizado, use_container_width=True, height=550)
        else:
            st.info("El turno asignado no cuenta con horas configuradas en la tabla de turnos.")
    else:
        st.warning("No se encontraron registros de asignación para los filtros seleccionados.")

    st.sidebar.markdown("---")
    if st.sidebar.button("🔄 Sincronizar / Refrescar Datos", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# ------------------------------------------------------------------------------
# PESTAÑA 2: RESUMEN CONSOLIDADO DE HORAS
# ------------------------------------------------------------------------------
with tab_resumen:
    st.subheader("📊 Reporte Consolidado de Horas y Control de Novedades")
    st.markdown("Filtre por el rango de fechas deseado utilizando el selector de calendario interactivo:")

    col_f1, col_f2, col_f3 = st.columns([2, 2, 3])
    
    fecha_min_db = df['Fecha'].min().date()
    fecha_max_db = df['Fecha'].max().date()
    
    fecha_inicio = col_f1.date_input("📆 Fecha Inicial", value=fecha_min_db, min_value=fecha_min_db, max_value=fecha_max_db)
    fecha_final = col_f2.date_input("📆 Fecha Final", value=fecha_max_db, min_value=fecha_min_db, max_value=fecha_max_db)
    
    vista_resumen = col_f3.radio(
        "Visualizar Métricas por:", ("Trabajador", "Unidad"), horizontal=True, key="radio_resumen_tab"
    )

    if fecha_inicio > fecha_final:
        st.error("❌ Error: La Fecha Inicial no puede ser mayor que la Fecha Final.")
    else:
        df_filtrado_fechas = df[(df['Fecha'].dt.date >= fecha_inicio) & (df['Fecha'].dt.date <= fecha_final)].copy()
        
        if df_filtrado_fechas.empty:
            st.warning("⏳ No se encontraron datos registrados dentro de este rango de fechas.")
        else:
            df_filtrado_fechas['Horas_Totales_Fila'] = df_filtrado_fechas.apply(lambda r: len(expandir_horas(r)), axis=1)
            
            def evaluar_es_novedad(r):
                cargo = str(r['ID_Cargo']).strip() if pd.notna(r['ID_Cargo']) else ''
                nov = str(r['ID_Novedad']).strip() if pd.notna(r['ID_Novedad']) else ''
                if cargo == 'OV001' and nov == 'AS001':
                    return False
                return nov != '' and nov != 'NORMAL'

            df_filtrado_fechas['Es_Novedad'] = df_filtrado_fechas.apply(evaluar_es_novedad, axis=1)
            
            def calcular_horas_planeadas(r):
                cargo = str(r['ID_Cargo']).strip() if pd.notna(r['ID_Cargo']) else ''
                nov = str(r['ID_Novedad']).strip() if pd.notna(r['ID_Novedad']) else ''
                if r['Es_Solo_Ejecucion'] == 1:
                    if cargo == 'OV001' and nov == 'AS001':
                        return r['Horas_Totales_Fila']
                    return 0
                return r['Horas_Totales_Fila']

            def calcular_horas_trabajadas(r):
                if r['Es_Novedad']:
                    return 0
                cargo = str(r['ID_Cargo']).strip() if pd.notna(r['ID_Cargo']) else ''
                nov = str(r['ID_Novedad']).strip() if pd.notna(r['ID_Novedad']) else ''
                if r['Es_Solo_Ejecucion'] == 1:
                    if cargo == 'OV001' and nov == 'AS001':
                        return r['Horas_Totales_Fila']
                    return 0
                return r['Horas_Totales_Fila']

            df_filtrado_fechas['Horas_Planeadas'] = df_filtrado_fechas.apply(calcular_horas_planeadas, axis=1)
            df_filtrado_fechas['Horas_Novedad'] = df_filtrado_fechas.apply(lambda r: r['Horas_Totales_Fila'] if r['Es_Novedad'] else 0, axis=1)
            df_filtrado_fechas['Horas_Trabajadas'] = df_filtrado_fechas.apply(calcular_horas_trabajadas, axis=1)
            df_filtrado_fechas['Cantidad_Novedades'] = df_filtrado_fechas['Es_Novedad'].astype(int)
            
            df_filtrado_fechas['Duracion_Novedad_Num'] = pd.to_numeric(df_filtrado_fechas['Duracion_Novedad'], errors='coerce').fillna(0)

            col_grupo = 'Empleado_Nam' if vista_resumen == "Trabajador" else 'Unidad_Desc'
            col_label = 'Trabajador' if vista_resumen == "Trabajador" else 'Unidad'

            df_resumen_grouped = df_filtrado_fechas.groupby(col_grupo).agg(
                Horas_Planeadas=('Horas_Planeadas', 'sum'),
                Horas_Trabajadas=('Horas_Trabajadas', 'sum'),
                Horas_Novedades=('Horas_Novedad', 'sum'),
                Duracion_Novedad_Total=('Duracion_Novedad_Num', 'sum'),
                Cantidad_Novedades=('Cantidad_Novedades', 'sum')
            ).reset_index()

            total_horas_trabajadas_global = df_resumen_grouped['Horas_Trabajadas'].sum()

            df_resumen_grouped['% Horas Trabajadas'] = df_resumen_grouped.apply(
                lambda r: (r['Horas_Trabajadas'] / r['Horas_Planeadas'] * 100.0) if r['Horas_Planeadas'] > 0 else 0.0, axis=1
            )

            df_resumen_grouped['% Aporte'] = df_resumen_grouped.apply(
                lambda r: (r['Horas_Trabajadas'] / total_horas_trabajadas_global * 100.0) if total_horas_trabajadas_global > 0 else 0.0, axis=1
            )

            df_resumen_final = df_resumen_grouped.rename(columns={
                col_grupo: col_label,
                'Horas_Planeadas': 'Horas Planeadas',
                'Horas_Trabajadas': 'Horas Trabajadas',
                'Horas_Novedades': 'Horas de Novedades',
                'Duracion_Novedad_Total': 'Suma Duración Novedad',
                'Cantidad_Novedades': 'Cantidad de Novedades'
            })

            columnas_ordenadas = [
                col_label, '% Aporte', 'Horas Planeadas', 'Horas Trabajadas', 
                'Horas de Novedades', 'Suma Duración Novedad', 'Cantidad de Novedades', '% Horas Trabajadas'
            ]
            df_resumen_final = df_resumen_final[columnas_ordenadas]

            st.markdown(f"### Conteo consolidado del **{fecha_inicio.strftime('%d/%m/%Y')}** al **{fecha_final.strftime('%d/%m/%Y')}**")
            
            st.dataframe(
                df_resumen_final,
                column_config={
                    col_label: st.column_config.TextColumn(f"👤 {col_label}" if col_label == "Trabajador" else f"🏢 {col_label}", width="medium"),
                    "% Aporte": st.column_config.ProgressColumn(
                        "📈 % Aporte (vs Total)",
                        help="Porcentaje de aporte que representan las horas trabajadas de este registro sobre el total global de la operación.",
                        format="%.1f%%",
                        min_value=0.0,
                        max_value=100.0
                    ),
                    "Horas Planeadas": st.column_config.NumberColumn("⏱️ Hrs Planeadas", format="%d hrs"),
                    "Horas Trabajadas": st.column_config.NumberColumn("✅ Hrs Trabajadas", format="%d hrs"),
                    "Horas de Novedades": st.column_config.NumberColumn("⚠️ Hrs Novedades", format="%d hrs"),
                    "Suma Duración Novedad": st.column_config.NumberColumn("⏳ Suma Duración", format="%.1f hrs"),
                    "Cantidad de Novedades": st.column_config.NumberColumn("🚨 Cant. Novedades", format="%d"),
                    "% Horas Trabajadas": st.column_config.ProgressColumn(
                        "📊 % Horas Trabajadas",
                        help="Representación porcentual de horas efectivas laboradas respecto a su total planeado.",
                        format="%.1f%%",
                        min_value=0.0,
                        max_value=100.0
                    )
                },
                use_container_width=True,
                hide_index=True,
                height=500
            )

# --- LEYENDA DINÁMICA GLOBAL DE NOVEDADES ---
st.markdown("---")
st.markdown("### 🎨 Código de Colores y Referencia de Novedades")
columnas_leyenda = st.columns(4)
lista_leyenda = [('NORMAL', 'Programación Normal (Sin Novedad)')]
for r in df_novedades.itertuples():
    lista_leyenda.append((str(r.ID_Novedad).strip(), str(r.Novedad_Desc)))

for idx, (cod_nov, desc_nov) in enumerate(lista_leyenda):
    color_hex = COLOR_MAP.get(cod_nov, DEFAULT_COLOR)
    col = columnas_leyenda[idx % 4]
    col.markdown(
        f"<div style='background-color: {color_hex}; padding: 8px; border-radius: 6px; text-align: center; margin-bottom: 8px; border: 1px solid #ccc; color: #111; font-size: 13px;'>"
        f"<strong>{cod_nov}</strong>: {desc_nov}</div>", 
        unsafe_allow_html=True
    )
